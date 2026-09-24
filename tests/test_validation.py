from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings
from app.schemas import Entities, IntentResult, Weights
from app.validation import Clarification, money, parse_datetime, recurrence_next


@pytest.mark.parametrize(
    "value,expected",
    [
        ("48k", 48000),
        ("50rb", 50000),
        ("1jt", 1000000),
        ("1.5m", 1500000),
        ("1.2 juta", 1200000),
        ("Rp75,000", 75000),
        ("75.000", 75000),
        ("1,5jt", 1500000),
        ("2 million", 2000000),
        ("10ribu", 10000),
    ],
)
def test_indonesian_money(value, expected):
    assert money(value) == expected


@pytest.mark.parametrize(
    "value", ["-12", "0", "nan", "inf", "1,23,456", "1.2.3", "10 billion", "coffee", "1e6", "1.23456"]
)
def test_invalid_money(value):
    with pytest.raises(Clarification):
        money(value)


def test_currency_ambiguity():
    with pytest.raises(Clarification):
        money("1m", "USD")
    assert money("12.50", "USD") == Decimal("12.50")


def test_local_time_and_offset():
    assert parse_datetime("2026-09-15T20:00:00", "Asia/Jakarta") == datetime(2026, 9, 15, 13, tzinfo=UTC)
    assert parse_datetime("2026-09-15T20:00:00+07:00", "Asia/Jakarta").hour == 13


@pytest.mark.parametrize("value", ["2026-03-08T02:30:00", "2026-11-01T01:30:00"])
def test_dst_nonexistent_and_ambiguous(value):
    with pytest.raises(Clarification):
        parse_datetime(value, "America/New_York")


def test_recurring_preserves_wall_clock():
    start = datetime(2026, 3, 6, 9, tzinfo=ZoneInfo("America/New_York"))
    result = recurrence_next("FREQ=WEEKLY;BYDAY=FR", start, start, "America/New_York")
    assert result == datetime(2026, 3, 13, 13, tzinfo=UTC)


def test_count_and_month_end():
    start = datetime(2026, 1, 31, 13, tzinfo=UTC)
    assert recurrence_next("FREQ=MONTHLY;COUNT=2", start, start, "UTC") == datetime(
        2026, 3, 31, 13, tzinfo=UTC
    )
    assert recurrence_next("FREQ=DAILY;COUNT=1", start, start, "UTC") is None


@pytest.mark.parametrize(
    "rule", ["FREQ=SECONDLY", "FREQ=DAILY;INTERVAL=0", "FREQ=DAILY;BYHOUR=2", "FREQ=DAILY\nBAD"]
)
def test_bad_recurrence(rule):
    with pytest.raises(Clarification):
        recurrence_next(rule, datetime.now(UTC), datetime.now(UTC), "UTC")


def test_model_schema_rejects_arbitrary_tools():
    with pytest.raises(ValidationError):
        IntentResult(intent="shell.execute", confidence=1, entities=Entities(), requires_confirmation=False)
    with pytest.raises(ValidationError):
        Entities(sql="DROP TABLE transactions")


def test_dynamic_weight_validation():
    for weights in [(30, 40, 20, 10), (10, 25, 50, 15), (0, 10, 10, 80)]:
        assert (
            sum(
                Weights(**dict(zip(["macro", "risk", "lifestyle", "health"], weights, strict=True)))
                .model_dump()
                .values()
            )
            == 100
        )
    with pytest.raises(ValidationError):
        Weights(macro=100, risk=100, lifestyle=100, health=100)


def test_fail_closed_configuration():
    with pytest.raises(ValueError, match="ALLOWED"):
        Settings(_env_file=None).validate_runtime()


def test_runtime_requires_selected_provider_key():
    base = dict(
        _env_file=None,
        allowed_telegram_user_ids="123",
        telegram_bot_token="fake-telegram-token",
        app_secret_key=Fernet.generate_key().decode(),
    )
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        Settings(**base).validate_runtime()
    Settings(**base, gemini_api_key="fake-gemini-key").validate_runtime()
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        Settings(**base, ai_provider="openai", gemini_api_key="fake-gemini-key").validate_runtime()
    Settings(**base, ai_provider="openai", openai_api_key="fake-openai-key").validate_runtime()
