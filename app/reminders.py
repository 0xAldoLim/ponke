from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import Activity, Decision, Delivery, Reminder, utcnow
from app.validation import Clarification, aware, parse_datetime, recurrence_next


async def create_reminder(db, user_id, e, source, settings):
    if not e.title or not e.start:
        raise Clarification("What should I remind you about, and when?")
    due = parse_datetime(e.start, settings.user_timezone)
    if due <= utcnow():
        raise Clarification("That reminder time is in the past. What future time should I use?")
    if e.recurrence:
        recurrence_next(e.recurrence, due, due - timedelta(seconds=1), settings.user_timezone)
    reminder = Reminder(
        user_id=user_id,
        text=e.title,
        due_at=due,
        start_at=due,
        timezone=settings.user_timezone,
        recurrence=e.recurrence,
        source_message_id=source,
    )
    db.add(reminder)
    await db.flush()
    return reminder


async def list_reminders(db, user_id):
    return list(
        (
            await db.scalars(
                select(Reminder)
                .where(Reminder.user_id == user_id, Reminder.status.in_(["active", "awaiting_completion"]))
                .order_by(Reminder.due_at)
                .limit(50)
            )
        ).all()
    )


async def change_reminder(db, user_id, reminder_id, status):
    reminder = await db.scalar(
        select(Reminder).where(Reminder.user_id == user_id, Reminder.id == reminder_id)
    )
    if not reminder:
        raise Clarification("I could not find that reminder. Ask to see your reminders first.")
    if reminder.status in {"completed", "cancelled"}:
        return f"Reminder already {reminder.status}: {reminder.text}"
    # Done acknowledges an occurrence; Cancel stops the recurrence.
    if not (status == "completed" and reminder.recurrence and reminder.status == "active"):
        reminder.status = status
    pending = (
        await db.scalars(
            select(Delivery).where(
                Delivery.user_id == user_id, Delivery.reminder_id == reminder.id, Delivery.status == "pending"
            )
        )
    ).all()
    for item in pending:
        item.status = "cancelled"
    db.add(
        Activity(
            user_id=user_id,
            kind="reminder." + status,
            reference=reminder.id,
            detail={"due_at": aware(reminder.due_at).isoformat(), "acted_at": utcnow().isoformat()},
        )
    )
    return f"Reminder {status}: {reminder.text}"


class SchedulerWorker:
    """Single-process producer and durable outbox; never schedule hundreds of future rows."""

    def __init__(self, sessions, settings, messenger, briefing):
        self.sessions, self.settings = sessions, settings
        self.messenger, self.briefing = messenger, briefing

    async def enqueue(self, now=None):
        now = now or utcnow()
        async with self.sessions.begin() as db:
            rows = (
                await db.scalars(
                    select(Reminder)
                    .where(
                        Reminder.status == "active",
                        Reminder.due_at <= now,
                        Reminder.user_id.in_(self.settings.allowed_ids),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for reminder in rows:
                key = f"reminder:{reminder.id}:{aware(reminder.due_at).isoformat()}"
                exists = await db.scalar(
                    select(Delivery.id).where(
                        Delivery.user_id == reminder.user_id, Delivery.delivery_key == key
                    )
                )
                if not exists:
                    db.add(
                        Delivery(
                            user_id=reminder.user_id,
                            delivery_key=key,
                            reminder_id=reminder.id,
                            text="Reminder: " + reminder.text,
                        )
                    )
                following = (
                    recurrence_next(reminder.recurrence, reminder.start_at, now, reminder.timezone)
                    if reminder.recurrence
                    else None
                )
                if following:
                    reminder.due_at = following
                else:
                    reminder.status = "awaiting_completion"
            decisions = (
                await db.scalars(
                    select(Decision)
                    .where(
                        Decision.follow_up_date <= now,
                        Decision.follow_up_date.is_not(None),
                        Decision.user_id.in_(self.settings.allowed_ids),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for decision in decisions:
                key = f"decision-follow-up:{decision.id}"
                exists = await db.scalar(
                    select(Delivery.id).where(
                        Delivery.user_id == decision.user_id, Delivery.delivery_key == key
                    )
                )
                if not exists:
                    db.add(
                        Delivery(
                            user_id=decision.user_id,
                            delivery_key=key,
                            text=f"How did this decision turn out? {decision.user_question[:180]}\nDecision ID: {decision.id}",
                        )
                    )
                decision.follow_up_date = None
        if self.settings.daily_briefing_enabled:
            local = now.astimezone(ZoneInfo(self.settings.user_timezone))
            if local.strftime("%H:%M") >= self.settings.daily_briefing_time:
                for user_id in self.settings.allowed_ids:
                    key = "briefing:" + local.date().isoformat()
                    async with self.sessions() as db:
                        exists = await db.scalar(
                            select(Delivery.id).where(
                                Delivery.user_id == user_id, Delivery.delivery_key == key
                            )
                        )
                    if not exists:
                        text = await self.briefing(user_id)
                        async with self.sessions.begin() as db:
                            db.add(Delivery(user_id=user_id, delivery_key=key, text=text))

    async def send_pending(self, now=None):
        now = now or utcnow()
        async with self.sessions() as db:
            rows = (
                await db.scalars(
                    select(Delivery)
                    .where(
                        Delivery.status == "pending",
                        Delivery.retry_at <= now,
                        Delivery.user_id.in_(self.settings.allowed_ids),
                    )
                    .order_by(Delivery.created_at)
                    .limit(50)
                )
            ).all()
        for item in rows:
            try:
                await self.messenger.send(item.user_id, item.text, reminder_id=item.reminder_id)
            except Exception:
                async with self.sessions.begin() as db:
                    delivery = await db.get(Delivery, item.id)
                    delivery.attempts += 1
                    delivery.retry_at = now + timedelta(
                        seconds=min(3600, 30 * 2 ** min(delivery.attempts, 7))
                    )
                continue
            async with self.sessions.begin() as db:
                delivery = await db.get(Delivery, item.id)
                delivery.status, delivery.sent_at = "sent", now

    async def tick(self):
        import structlog

        try:
            await self.enqueue()
            await self.send_pending()
        except Exception as exc:
            structlog.get_logger().error("scheduler_failed", error_type=type(exc).__name__)
