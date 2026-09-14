from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import Activity, DecisionOutcome, Memory, utcnow
from app.finance import financial_context, month_range, summary
from app.reminders import list_reminders
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
    return "\n\n".join(lines)


async def daily_briefing(sessions, calendar, user_id, settings):
    now = utcnow().astimezone(ZoneInfo(settings.user_timezone))
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    enabled = set(settings.daily_briefing_sections.split(","))
    blocks = [f"GOOD MORNING\n{now:%A, %d %B}"]
    if "today" in enabled:
        try:
            events = await calendar.get_events(user_id, start, end)
            entries = []
            from datetime import datetime

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
        if "priorities" in enabled and due:
            blocks.append(
                "PRIORITIES\n" + "\n".join(f"{index}. {r.text}" for index, r in enumerate(due[:3], 1))
            )
    return "\n\n".join(blocks)
