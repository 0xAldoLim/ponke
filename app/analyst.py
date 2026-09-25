from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.database import Activity, AgentOpinion, Decision, DecisionOutcome, Memory, Task, Transaction, utcnow
from app.finance import financial_context, month_range, summary
from app.reminders import list_reminders
from app.tasks import OPEN, priority_score
from app.validation import aware, cash


def evidence_insights(context):
    lines = []
    current = context["this_month"]
    for currency, values in current["by_currency"].items():
        lines.append("FACT: Recorded spending this month: " + cash(values["expense"], currency) + ".")
        avg = context["recorded_monthly_average"].get(currency)
        n = context["average_sample_months"].get(currency, 0)
        if avg and n >= 3 and values["expense"] > avg:
            change = (values["expense"] - avg) / avg * 100
            lines.append(
                f"FACT: Partial-month spending is {change:.1f}% above the average of {n} recorded complete months ({currency})."
            )
    for candidate in context["possible_recurring_expenses"][:3]:
        lines.append(
            f"POSSIBLE PATTERN: {candidate['merchant']} has {candidate['count']} expenses of "
            f"{cash(candidate['amount'], candidate['currency'])}. This may be recurring."
        )
    return lines or ["FACT: There is not enough recorded activity for a spending insight yet."]


async def personal_analysis(db, user_id, settings):
    context = await financial_context(db, user_id, settings)
    lines = evidence_insights(context)
    start = month_range(utcnow(), settings.user_timezone, -3)[0]
    expenses = (
        await db.scalars(
            select(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == "expense",
                Transaction.date >= start,
            )
            .limit(5000)
        )
    ).all()
    category_months = {}
    for item in expenses:
        month = aware(item.date).astimezone(ZoneInfo(settings.user_timezone)).strftime("%Y-%m")
        key = (item.category, item.currency)
        buckets = category_months.setdefault(key, {})
        buckets[month] = buckets.get(month, Decimal(0)) + item.amount
    current_month = utcnow().astimezone(ZoneInfo(settings.user_timezone)).strftime("%Y-%m")
    for (category, currency), months in category_months.items() if len(expenses) < 5000 else []:
        previous = [amount for month, amount in months.items() if month != current_month]
        current = months.get(current_month)
        if current is not None and len(previous) == 3 and sum(previous) > 0:
            average = sum(previous) / 3
            if current > average * Decimal("1.2"):
                lines.append(
                    f"FACT: Recorded {category} spending is {((current / average) - 1) * 100:.0f}% above its average across 3 recorded complete months ({currency}); the current month is partial."
                )
    activity_counts = dict(
        (
            await db.execute(
                select(Activity.kind, func.count())
                .where(
                    Activity.user_id == user_id,
                    Activity.created_at >= utcnow() - timedelta(days=30),
                )
                .group_by(Activity.kind)
            )
        ).all()
    )
    calendar_actions = sum(
        activity_counts.get(kind, 0) for kind in ("calendar.create", "calendar.modify", "calendar.delete")
    )
    if calendar_actions:
        grammar = "change was" if calendar_actions == 1 else "changes were"
        lines.append(
            f"FACT: {calendar_actions} calendar {grammar} made through Ponke in the last 30 days; changes made directly in Google Calendar are not counted."
        )
    if trades := activity_counts.get("portfolio.trade", 0):
        lines.append(
            f"FACT: {trades} user-reported investment trades were recorded in the last 30 days; Ponke did not place them."
        )
    if questions := activity_counts.get("general_question", 0):
        lines.append(f"FACT: You asked Ponke {questions} general questions in the last 30 days.")
    outcomes = (
        await db.scalars(
            select(DecisionOutcome)
            .where(DecisionOutcome.user_id == user_id)
            .order_by(DecisionOutcome.created_at.desc())
            .limit(50)
        )
    ).all()
    bad = [o for o in outcomes if o.user_satisfaction is not None and o.user_satisfaction < 40]
    if outcomes:
        lines.append(
            f"FACT: {len(bad)} of {len(outcomes)} recorded decision outcomes have satisfaction below 40/100. No automatic council calibration is active."
        )
        ids = [row.decision_id for row in outcomes]
        decisions = {
            row.id: row
            for row in (
                await db.scalars(select(Decision).where(Decision.user_id == user_id, Decision.id.in_(ids)))
            ).all()
        }
        for category in {decision.decision_type for decision in decisions.values()}:
            rated = [
                o.user_satisfaction
                for o in outcomes
                if o.user_satisfaction is not None
                and decisions.get(o.decision_id)
                and decisions[o.decision_id].decision_type == category
            ]
            if len(rated) >= 3:
                lines.append(
                    f"FACT: {category} decisions have average reported satisfaction {sum(rated) / len(rated):.0f}/100 across {len(rated)} outcomes. This is descriptive, not a recommendation score."
                )
        waited = [
            o.user_satisfaction
            for o in outcomes
            if o.user_satisfaction is not None
            and decisions.get(o.decision_id)
            and decisions[o.decision_id].final_recommendation.get("decision") == "WAIT"
        ]
        if len(waited) >= 5:
            lines.append(
                f"FACT: WAIT recommendations have average reported satisfaction {sum(waited) / len(waited):.0f}/100 across {len(waited)} outcomes; selection effects prevent a causal claim."
            )
    activity = (
        await db.scalars(
            select(Activity)
            .where(Activity.user_id == user_id, Activity.kind == "reminder.completed")
            .order_by(Activity.created_at.desc())
            .limit(100)
        )
    ).all()
    if activity:
        lines.append(f"FACT: {len(activity)} reminder completions are recorded (up to the latest 100).")
    tasks = (
        await db.scalars(
            select(Task).where(Task.user_id == user_id).order_by(Task.created_at.desc()).limit(200)
        )
    ).all()
    if len(tasks) >= 5:
        completed = [task for task in tasks if task.status == "done"]
        overdue = [
            task for task in tasks if task.status in OPEN and task.due_at and aware(task.due_at) < utcnow()
        ]
        lines.append(
            f"FACT: {len(completed)} of the latest {len(tasks)} tasks are done; {len(overdue)} open tasks are overdue. This is a recorded-task sample, not a productivity diagnosis."
        )
        delays = [
            (aware(task.completed_at) - aware(task.due_at)).total_seconds()
            for task in completed
            if task.completed_at and task.due_at
        ]
        if len(delays) >= 5:
            lines.append(
                f"FACT: {sum(delay > 0 for delay in delays)} of {len(delays)} completed tasks with deadlines finished after their due date."
            )
    return "\n\n".join(lines)


async def calibration_report(db, user_id):
    outcomes = (
        await db.scalars(
            select(DecisionOutcome)
            .where(DecisionOutcome.user_id == user_id, DecisionOutcome.user_satisfaction.is_not(None))
            .limit(500)
        )
    ).all()
    if len(outcomes) < 20:
        return f"There isn't enough outcome data for calibration yet ({len(outcomes)}/20 rated outcomes). No council weights have changed."
    ids = [row.decision_id for row in outcomes]
    opinions = (await db.scalars(select(AgentOpinion).where(AgentOpinion.decision_id.in_(ids)))).all()
    roles = {row.decision_id: set() for row in outcomes}
    for opinion in opinions:
        roles[opinion.decision_id].add(opinion.agent_name)
    lines = [
        f"Informational calibration from {len(outcomes)} rated outcomes (0–100 satisfaction). No automatic reweighting:"
    ]
    for role in ("macro", "risk", "lifestyle", "health"):
        values = [row.user_satisfaction for row in outcomes if role in roles[row.decision_id]]
        if values:
            lines.append(
                f"{role}: {len(values)} outcomes, average satisfaction {sum(values) / len(values):.0f}/100. Roles can overlap, so this is descriptive, not causal."
            )
    return "\n".join(lines)


async def daily_briefing(sessions, calendar, user_id, settings):
    now = utcnow().astimezone(ZoneInfo(settings.user_timezone))
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    enabled = set(settings.daily_briefing_sections.split(","))
    blocks = [f"GOOD MORNING\n{now:%A, %d %B}"]
    free_minutes = None
    if "today" in enabled:
        try:
            events = await calendar.get_events(user_id, start, end)
            from datetime import datetime

            window_start = max(now, now.replace(hour=9, minute=0, second=0, microsecond=0))
            window_end = now.replace(hour=18, minute=0, second=0, microsecond=0)
            busy = 0
            for event in events:
                if event.get("transparency") == "transparent":
                    continue
                begin, finish = event.get("start", {}), event.get("end", {})
                if "dateTime" not in begin or "dateTime" not in finish:
                    continue
                left = max(
                    window_start,
                    datetime.fromisoformat(begin["dateTime"]).astimezone(ZoneInfo(settings.user_timezone)),
                )
                right = min(
                    window_end,
                    datetime.fromisoformat(finish["dateTime"]).astimezone(ZoneInfo(settings.user_timezone)),
                )
                busy += max(0, int((right - left).total_seconds() / 60))
            free_minutes = max(0, min(540, int((window_end - window_start).total_seconds() / 60)) - busy)
            entries = []

            for event in events[:8]:
                value = event.get("start", {})
                when = (
                    datetime.fromisoformat(value["dateTime"])
                    .astimezone(ZoneInfo(settings.user_timezone))
                    .strftime("%H:%M")
                    if "dateTime" in value
                    else "All day"
                )
                entries.append("• " + when + " " + event.get("summary", "Untitled"))
            blocks.append("TODAY\n" + ("\n".join(entries) or "No calendar events."))
        except Exception:
            blocks.append("TODAY\nCalendar unavailable; schedule could not be checked.")
    async with sessions() as db:
        reminders = await list_reminders(db, user_id)
        due = [r for r in reminders if aware(r.due_at) < end]
        if "reminders" in enabled:
            blocks.append("REMINDERS\n" + ("\n".join("• " + r.text for r in due[:5]) or "No reminders due."))
        if "finance" in enabled:
            yesterday = await summary(db, user_id, start - timedelta(days=1), start)
            lo, hi = month_range(now, settings.user_timezone)
            month = await summary(db, user_id, lo, hi)
            currency = settings.default_currency
            y = yesterday["by_currency"].get(currency, {}).get("expense", Decimal(0))
            m = month["by_currency"].get(currency, {}).get("expense", Decimal(0))
            text = f"FINANCE\nYesterday: {cash(y, currency)}\n{now:%B}: {cash(m, currency)} (recorded)"
            budget = await db.scalar(
                select(Memory).where(Memory.user_id == user_id, Memory.key == "finance.budget." + currency)
            )
            if budget:
                text += "\nBudget remaining: " + cash(Decimal(budget.value) - m, currency)
            blocks.append(text)
        if "notable" in enabled:
            context = await financial_context(db, user_id, settings)
            blocks.append("NOTABLE\n" + "\n".join(evidence_insights(context)[:2]))
        tasks = (
            await db.scalars(select(Task).where(Task.user_id == user_id, Task.status.in_(OPEN)).limit(100))
        ).all()
        tasks.sort(key=lambda task: -priority_score(task, utcnow(), free_minutes))
        if "tasks" in enabled:
            blocks.append(
                "TASKS\n" + ("\n".join(f"• {task.title}" for task in tasks[:5]) or "No open tasks.")
            )
        if "priorities" in enabled:
            priorities = [task.title for task in tasks[:3]] or [r.text for r in due[:3]]
            blocks.append(
                "PRIORITIES\n"
                + (
                    "\n".join(f"{index}. {title}" for index, title in enumerate(priorities, 1))
                    or "No pressing items recorded."
                )
            )
    return "\n\n".join(blocks)
