from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openpyxl import Workbook
from sqlalchemy import func, select

from app.council import Council, record_outcome
from app.database import (
    Decision,
    DecisionOutcome,
    MarketCache,
    SpreadsheetSyncOutbox,
    Task,
    Transaction,
    utcnow,
)
from app.investment import cagr, purchase_scenario, statement_metrics, valuation
from app.market import normalized_symbol
from app.schemas import Entities
from app.sheets import SheetsWorker
from app.statements import parse_statement
from app.voice import preference_correction, voice_instruction


def test_common_indonesian_ticker_is_resolved_to_idx_listing():
    assert normalized_symbol("BBCA") == "BBCA.JK"
    assert normalized_symbol("BBCA.JK") == "BBCA.JK"


@pytest.mark.asyncio
async def test_task_lifecycle_is_separate_from_reminders(env):
    settings, sessions, model, _, service = env
    model.route("task.create", title="Finish internship report", priority="high")
    result = await service.handle(123, "task-1", "Finish internship report by Friday")
    assert "Added task" in result.text
    async with sessions() as db:
        task = await db.scalar(select(Task).where(Task.user_id == 123))
        assert task.title == "Finish internship report"
    model.route("task.complete", target_id=task.id)
    result = await service.handle(123, "task-2", "Mark internship report done")
    assert "done" in result.text
    async with sessions() as db:
        assert (await db.scalar(select(Task).where(Task.id == task.id))).status == "done"


@pytest.mark.asyncio
async def test_statement_preview_and_confirm(env):
    _, sessions, _, _, service = env
    csv_file = b"date,description,debit,credit,currency\n2026-09-14,Coffee,48000,,IDR\n2026-09-15,Refund,,12000,IDR\n"
    preview = await service.handle(123, "statement-1", "", document=csv_file, filename="bank.csv")
    assert "2 ready" in preview.text
    assert preview.confirmation_id
    async with sessions() as db:
        assert await db.scalar(select(func.count(Transaction.id))) == 0
    result = await service.confirm(123, preview.confirmation_id, True)
    assert "Imported 2" in result.text
    async with sessions() as db:
        rows = (await db.scalars(select(Transaction).where(Transaction.user_id == 123))).all()
        assert {row.transaction_type for row in rows} == {"expense", "income"}
        assert await db.scalar(select(func.count(SpreadsheetSyncOutbox.id))) >= 1
    second = await service.confirm(123, preview.confirmation_id, True)
    assert "already been used" in second.text


def test_unsigned_statement_amount_requires_review():
    rows = parse_statement("statement.csv", b"date,description,amount\n2026-09-14,Unknown direction,48000\n")
    assert rows[0]["status"] == "review"


def test_xlsx_statement_parser_uses_same_validation():
    book = Workbook()
    sheet = book.active
    sheet.append(["date", "description", "debit", "credit", "currency"])
    sheet.append(["2026-09-14", "Lunch", 75000, None, "IDR"])
    output = BytesIO()
    book.save(output)
    rows = parse_statement("bank.xlsx", output.getvalue())
    assert rows[0]["status"] == "ready"
    assert rows[0]["amount"] == "75000"


@pytest.mark.asyncio
async def test_market_cache_and_source(env):
    settings, sessions, _, _, service = env
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"date": "2026-09-23", "rate": 16700.0})

    service.market.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service.market.fx.client = service.market.client
    async with sessions.begin() as db:
        value = await service.market.get(db, 123, "fx", "USD/IDR")
        assert value["freshness"] == "LIVE"
    async with sessions.begin() as db:
        cached = await service.market.get(db, 123, "fx", "USD/IDR")
        assert cached["freshness"] == "CACHED"
        assert cached["as_of"] == "2026-09-23"
        assert await db.scalar(select(func.count(MarketCache.id))) == 1
    assert len(calls) == 1
    data = await service.handle(123, "show-data-sources", "/data")
    assert "Frankfurter" in data.text
    assert "2026-09-23" in data.text


@pytest.mark.asyncio
async def test_stale_market_cache_is_labeled(env):
    _, sessions, _, _, service = env
    async with sessions.begin() as db:
        db.add(
            MarketCache(
                provider="Frankfurter",
                cache_key="fx:USD/IDR",
                payload={
                    "symbol": "USD/IDR",
                    "rate": "16000",
                    "as_of": "2026-09-20",
                    "source": "Frankfurter",
                },
                fetched_at=utcnow() - timedelta(days=3),
                expires_at=utcnow() - timedelta(days=2),
            )
        )

    async def fail(request):
        raise httpx.ConnectError("offline")

    service.market.client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
    service.market.fx.client = service.market.client
    async with sessions.begin() as db:
        value = await service.market.get(db, 123, "fx", "USD/IDR")
    assert value["stale"] is True
    assert value["freshness"] == "CACHED"


@pytest.mark.asyncio
async def test_sheets_outage_does_not_undo_finance(env):
    settings, sessions, model, calendar, service = env
    model.route(
        "finance.log_expense", amount="48k", merchant="Coffee", start="2026-09-24T12:00:00", currency="IDR"
    )
    reply = await service.handle(123, "expense-with-sheets-outage", "Spent 48k on coffee")
    assert "Logged" in reply.text
    worker = SheetsWorker(
        sessions,
        settings.model_copy(update={"google_sheets_enabled": True, "google_finance_sheet_id": "fake"}),
        calendar,
    )

    async def unavailable(_):
        raise httpx.ConnectError("offline")

    worker.ensure_tabs = unavailable
    await worker.tick()
    async with sessions() as db:
        assert await db.scalar(select(func.count(Transaction.id))) == 1
        queued = (await db.scalars(select(SpreadsheetSyncOutbox))).all()
        assert queued and all(row.status == "pending" for row in queued)
        assert any(row.attempts == 1 for row in queued)


@pytest.mark.asyncio
async def test_sheets_upserts_by_stable_user_key(env):
    settings, sessions, _, _, _ = env
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"values": [["123:tx1"]]}
                if len([r for r in requests if r.method == "GET"]) > 1
                else {"values": []},
            )
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    calendar = SimpleNamespace(access_token=AsyncMock(return_value="fake"), http=client)
    worker = SheetsWorker(sessions, settings.model_copy(update={"google_finance_sheet_id": "fake"}), calendar)
    await worker.upsert(123, "Transactions", "tx1", ["2026-09-24", "48000"])
    await worker.upsert(123, "Transactions", "tx1", ["2026-09-24", "48000"])
    assert [request.method for request in requests] == ["GET", "POST", "GET", "PUT"]
    assert b"123:tx1" in requests[1].content
    await client.aclose()


def test_research_calculations_do_not_invent_values():
    assert cagr(Decimal(100), Decimal(121), 2) == Decimal("0.1")
    assert cagr(Decimal(0), Decimal(121), 2) is None
    assert valuation({"eps": "-1", "pe": "9"})["pe"]["current"] is None
    snapshot = {
        "holdings": [{"symbol": "BBCA.JK", "currency": "IDR", "value": "10000000"}],
        "available_cash_snapshots": {"IDR": Decimal("20000000")},
        "unknown_cash_accounts": [],
    }
    scenario = purchase_scenario(snapshot, "BBCA.JK", "IDR", Decimal("5000000"))
    assert scenario["position_after"] == "15000000"
    assert scenario["cash_remaining"] == "15000000"
    metrics, direction = statement_metrics(
        {
            "annual_reports": {
                "INCOME_STATEMENT": [
                    {"totalRevenue": "121", "netIncome": "12"},
                    {"totalRevenue": "110", "netIncome": "11"},
                    {"totalRevenue": "100", "netIncome": "10"},
                ],
                "CASH_FLOW": [{"operatingCashflow": "20", "capitalExpenditures": "-5"}],
                "BALANCE_SHEET": [],
            }
        }
    )
    assert metrics["free_cash_flow"] == "15"
    assert direction["revenue_cagr"] is not None
    assert metrics["debt"] is None


@pytest.mark.asyncio
async def test_deep_council_has_bounded_two_rounds(env):
    _, _, model, _, _ = env
    council = Council(model)
    _, first, second = await council.run("Should I buy a car?", {}, "purchase", "deep")
    assert set(first) == {"lifestyle", "risk"}
    assert set(second) == set(first)
    assert len([call for call in model.calls if call[0].__name__ == "SpecialistView"]) == 4


@pytest.mark.asyncio
async def test_decision_outcome_records_action_currency_and_stops_followup(env):
    _, sessions, _, _, _ = env
    async with sessions.begin() as db:
        decision = Decision(
            user_id=123,
            user_question="Buy BTC?",
            decision_type="investment",
            context_snapshot={},
            final_recommendation={"decision": "WAIT", "recommended_action": "Wait."},
            final_confidence=0,
            follow_up_date=utcnow() + timedelta(days=30),
        )
        db.add(decision)
        await db.flush()
        await record_outcome(
            db,
            123,
            Entities(
                target_id=decision.id,
                description="Waited and saved",
                actual_action="waited",
                result_amount="-50000",
                currency="IDR",
                satisfaction=80,
            ),
        )
    async with sessions() as db:
        outcome = await db.scalar(select(DecisionOutcome).where(DecisionOutcome.user_id == 123))
        assert outcome.user_action == "waited"
        assert outcome.measurable_result == Decimal("-50000")
        assert outcome.result_currency == "IDR"
        assert (await db.get(Decision, decision.id)).follow_up_date is None


def test_voice_preferences_are_stable_and_finance_is_english(env):
    settings, _, _, _, _ = env
    assert preference_correction("Be shorter.") == {"verbosity": "concise"}
    prompt = voice_instruction(
        settings, {"preference.language": "en", "preference.finance_basics": "skip"}, "finance"
    )
    assert "language=en" in prompt
    assert "Do not explain basic finance terms" in prompt
    assert "No cheerleading" in prompt
