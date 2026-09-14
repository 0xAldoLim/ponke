import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr


class Clarification(ValueError):
    """A safe, user-visible validation message."""


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def parse_datetime(value: str, timezone: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise Clarification("Please give an unambiguous date and time.") from exc
    if result.tzinfo is None:
        local = result.replace(tzinfo=ZoneInfo(timezone))
        if local.astimezone(UTC).astimezone(ZoneInfo(timezone)).replace(tzinfo=None) != result:
            raise Clarification("That local time does not exist due to daylight saving. Choose another time.")
        if local.utcoffset() != local.replace(fold=1).utcoffset():
            raise Clarification("That local time occurs twice. Please include a UTC offset.")
        result = local
    return result.astimezone(UTC)


def money(value: str | Decimal | int, currency: str = "IDR") -> Decimal:
    """Parse a single extracted monetary token; never classify intent with regex."""
    text = str(value).strip().lower()
    text = re.sub(r"^(rp\.?|idr|usd|eur)\s*", "", text).strip()
    match = re.fullmatch(r"([0-9][0-9.,]*)(?:\s*(k|rb|ribu|jt|juta|million|m))?", text)
    if not match:
        raise Clarification("Please specify a positive amount, for example 48k IDR.")
    number, suffix = match.groups()
    if suffix == "m" and currency != "IDR":
        raise Clarification("Does m mean million? Please write the full amount.")
    if suffix:
        if "." in number and "," in number:
            raise Clarification("Please write the amount without mixed separators.")
        if "," in number:
            number = number.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+", number):
        number = number.replace(",", "")
    elif currency == "IDR" and re.fullmatch(r"\d{1,3}(\.\d{3})+", number):
        number = number.replace(".", "")
    elif "," in number:
        raise Clarification("Please clarify the amount using digits without grouping separators.")
    try:
        amount = (
            Decimal(number)
            * {
                "k": 1000,
                "rb": 1000,
                "ribu": 1000,
                "jt": 1000000,
                "juta": 1000000,
                "million": 1000000,
                "m": 1000000,
                None: 1,
            }[suffix]
        )
    except InvalidOperation as exc:
        raise Clarification("I could not read that amount.") from exc
    if not amount.is_finite() or amount <= 0 or amount >= Decimal("1e18"):
        raise Clarification("The amount is outside the supported range.")
    if amount != amount.quantize(Decimal("0.0001")):
        raise Clarification("Amounts support at most four decimal places.")
    return amount


def cash(value, currency="IDR"):
    prefix = "Rp" if currency == "IDR" else currency + " "
    return prefix + (f"{Decimal(value):,.0f}" if currency == "IDR" else f"{Decimal(value):,.2f}")


def recurrence_next(rule: str, start: datetime, after: datetime, timezone: str):
    # Restrict to bounded-cost daily/weekly/monthly/yearly RFC5545 rules.
    if len(rule) > 250 or "\n" in rule or not re.fullmatch(r"[A-Z0-9=;,+\-:TZ]+", rule):
        raise Clarification("Please use a simple daily, weekly, monthly or yearly recurrence.")
    parts = dict(part.split("=", 1) for part in rule.removeprefix("RRULE:").split(";"))
    if parts.get("FREQ") not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}:
        raise Clarification("Recurring reminders must be daily or less frequent.")
    if set(parts) - {"FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY", "BYMONTH", "COUNT", "UNTIL", "WKST"}:
        raise Clarification("That recurrence option is not supported.")
    if not 1 <= int(parts.get("INTERVAL", 1)) <= 100:
        raise Clarification("Recurrence interval must be between 1 and 100.")
    if "COUNT" in parts and not 1 <= int(parts["COUNT"]) <= 10000:
        raise Clarification("Recurrence count must be between 1 and 10000.")
    try:
        parsed = rrulestr(rule, dtstart=aware(start).astimezone(ZoneInfo(timezone)))
        result = parsed.after(aware(after).astimezone(ZoneInfo(timezone)), inc=False)
        return result.astimezone(UTC) if result else None
    except (ValueError, TypeError) as exc:
        raise Clarification("I could not validate that recurrence.") from exc
