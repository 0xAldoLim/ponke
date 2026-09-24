import io
import os
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from PIL import Image
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.database import Base, make_database
from app.orchestrator import Orchestrator
from app.schemas import Answer, Entities, IntentResult, Opinion, ReceiptData, Verdict


@pytest.fixture(autouse=True)
def isolate_application_environment(monkeypatch):
    """Never let a developer's live .env change test behavior or supply API keys."""
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)


class FakeModel:
    def __init__(self):
        self.intent = IntentResult(
            intent="general_question", confidence=1, entities=Entities(), requires_confirmation=False
        )
        self.calls = []
        self.failure = None
        self.receipt = ReceiptData(
            merchant="Starbucks",
            date="2026-09-14",
            time=None,
            items=[],
            subtotal=None,
            tax=None,
            discounts=None,
            total="78000",
            payment_method="BCA",
            currency="IDR",
            category="Food & Drinks",
            subcategory="Coffee",
            confidence=0.97,
            total_confidence=0.99,
        )

    async def structured(self, schema, instruction, data, **kwargs):
        self.calls.append((schema, instruction, data, kwargs))
        if self.failure:
            raise self.failure
        if schema is IntentResult:
            return self.intent
        if schema is ReceiptData:
            return self.receipt
        if schema is Opinion:
            return Opinion(
                position="conditional",
                confidence=70,
                score=60,
                key_argument="Liquidity is unknown.",
                upside=["Useful upgrade"],
                downside=["Opportunity cost"],
                assumptions=["No urgent failure"],
                risks=["Unknown reserves"],
                missing_information=["Monthly income"],
                what_would_change_my_mind=["Evidence of sufficient reserves"],
                recommended_action="Wait for data",
                strongest_opposing_argument="Utility may be high" if data["round_1"] else None,
                overlooked_information=["Urgency"] if data["round_1"] else [],
                changed_position=False,
            )
        if schema is Verdict:
            return Verdict(
                decision_type="purchase",
                decision="NEED INFORMATION",
                confidence=70,
                weights={"macro": 10, "risk": 30, "lifestyle": 50, "health": 10},
                relevance_explanation="Purchase utility and affordability dominate.",
                recommended_action="Confirm your reserves before buying.",
                reasons=["Liquidity unknown"],
                facts=[],
                assumptions=["No urgent failure"],
                main_disagreement="Utility versus unknown reserves",
                missing_evidence=["Current balances"],
                what_would_change=["Sufficient reserve data"],
            )
        return Answer(text="Based on recorded data only.")

    def route(self, intent, **entities):
        self.intent = IntentResult(
            intent=intent, confidence=1, entities=Entities(**entities), requires_confirmation=False
        )


class FakeCalendar:
    def __init__(self):
        self.events, self.calls = [], []
        self.failure = False

    async def get_events(self, user_id, start, end, search=None):
        self.calls.append(("get", user_id, start, end, search))
        if self.failure:
            raise TimeoutError()
        return [
            e
            for e in self.events
            if (not search or search.lower() in e["summary"].lower())
            and datetime.fromisoformat(e["start"]["dateTime"]) < end
            and datetime.fromisoformat(e["end"]["dateTime"]) > start
        ]

    async def get_event(self, user_id, identifier):
        return next(e.copy() for e in self.events if e["id"] == identifier)

    async def create_event(self, user_id, title, start, end, operation_id):
        if self.failure:
            raise TimeoutError()
        self.calls.append(("create", user_id, operation_id))
        value = {
            "id": "event123",
            "summary": title,
            "etag": "v1",
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        self.events.append(value)
        return value

    async def update_event(self, user_id, identifier, title, start, end, etag):
        self.calls.append(("update", identifier))
        value = next(e for e in self.events if e["id"] == identifier)
        value.update(start={"dateTime": start.isoformat()}, end={"dateTime": end.isoformat()}, etag="v2")
        return value

    async def delete_event(self, user_id, identifier):
        self.calls.append(("delete", identifier))
        self.events = [e for e in self.events if e["id"] != identifier]

    async def connect_url(self, user_id):
        return "https://accounts.google.com/mock"


@pytest.fixture
async def env():
    settings = Settings(
        _env_file=None,
        app_secret_key=Fernet.generate_key().decode(),
        allowed_telegram_user_ids="123,456",
        telegram_bot_token="123456:fake",
        openai_api_key="fake",
        daily_briefing_enabled=False,
    )
    url = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    engine, sessions = make_database(url)
    connection, transaction = None, None
    if engine.dialect.name == "postgresql":
        if not engine.url.database.endswith("_test"):
            raise RuntimeError("TEST_DATABASE_URL must use a disposable database ending in _test")
        connection = await engine.connect()
        transaction = await connection.begin()
        sessions = async_sessionmaker(
            connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
    else:

        @event.listens_for(engine.sync_engine, "connect")
        def enforce_foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        async with engine.begin() as connection_for_schema:
            await connection_for_schema.run_sync(Base.metadata.create_all)
    model, calendar = FakeModel(), FakeCalendar()
    service = Orchestrator(sessions, settings, model, calendar)
    yield settings, sessions, model, calendar, service
    if transaction:
        await transaction.rollback()
        await connection.close()
    await engine.dispose()


@pytest.fixture
def receipt_image():
    buffer = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def future():
    return (datetime.now(UTC) + timedelta(days=1)).replace(hour=13, minute=0, second=0, microsecond=0)
