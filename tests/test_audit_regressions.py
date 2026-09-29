from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select

from app.analyst import cross_domain_periods
from app.config import Settings
from app.database import Account, Asset, Decision, SpreadsheetSyncOutbox, Task, Transaction, utcnow
from app.finance import month_range, summary
from app.investment import purchase_scenario, research
from app.market import (
    AlphaVantageAdapter,
    canonical_macro_series,
    normalize_fundamentals_payload,
    resolve_equity_symbol,
)
from app.orchestrator import explicit_deep_request
from app.sheets import SheetsWorker
from app.statements import (
    commit_statement,
    parse_amount,
    parse_statement,
    preview_statement,
    review_row,
    review_rows,
    statement_utc_date,
)
from app.tasks import priority_score
from app.validation import Clarification


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("48.000", "48000"),
        ("1.250.000", "1250000"),
        ("1.250.000,50", "1250000.50"),
        ("48,000", "48000"),
        ("1,250,000", "1250000"),
        ("1,250,000.50", "1250000.50"),
        ("48,50", "48.50"),
        ("48.50", "48.50"),
        ("Rp48.000", "48000"),
        ("IDR 1.250.000", "1250000"),
        ("$1,250.50", "1250.50"),
        ("(48.000)", "-48000"),
        ("-48.000", "-48000"),
    ],
)
def test_statement_amount_formats(raw, expected):
    assert parse_amount(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["1.2.3", "1,2,3", "abc", "12.34.567", "1,23.456", "48.000x"])
def test_malformed_amount_is_never_imported(raw):
    assert parse_amount(raw) is None
    content = f"date,description,debit,credit,currency\n2026-09-14,Coffee,{raw},,IDR\n".encode()
    if "," in raw:
        content = f'date,description,debit,credit,currency\n2026-09-14,Coffee,"{raw}",,IDR\n'.encode()
    assert parse_statement("bank.csv", content)[0]["status"] == "review"


def test_indonesian_bank_amount_is_48000_not_48():
    rows = parse_statement(
        "bank.csv", b"date,description,debit,credit,currency\n2026-09-14,Coffee,48.000,,IDR\n"
    )
    assert rows[0]["status"] == "ready"
    assert rows[0]["amount"] == "48000"


def test_missing_currency_is_reviewed_instead_of_assumed_idr():
    rows = parse_statement("bank.csv", b"date,description,debit\n2026-09-14,Coffee,48.000\n")
    assert rows[0]["status"] == "review"
    assert rows[0]["currency"] is None


def test_explicit_rupiah_prefix_supplies_currency():
    rows = parse_statement("bank.csv", b"date,description,debit\n2026-09-14,Coffee,Rp48.000\n")
    assert rows[0]["status"] == "ready"
    assert rows[0]["currency"] == "IDR"


def test_unquoted_decimal_comma_cannot_silently_truncate_amount():
    rows = parse_statement(
        "bank.csv", b"date,description,debit,credit,currency\n2026-09-14,Coffee,1.250.000,50,,IDR\n"
    )
    assert rows[0]["status"] == "review"


def test_malformed_debit_cannot_be_ignored_when_credit_is_valid():
    rows = parse_statement(
        "bank.csv", b"date,description,debit,credit,currency\n2026-09-14,Transfer,1.2.3,500,IDR\n"
    )
    assert rows[0]["status"] == "review"
    assert rows[0]["amount"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker", ["BBCA", "BYAN", "BUMI", "DCII", "BREN", "CUAN", "BRMS", "DSSA", "TPIA"])
async def test_idx_symbol_resolution_needs_context_or_record(env, ticker):
    _, sessions, _, _, _ = env
    async with sessions.begin() as db:
        assert (await resolve_equity_symbol(db, 123, ticker + ".JK")).provider_symbol == ticker + ".JK"
        assert (
            await resolve_equity_symbol(db, 123, ticker, "Analyze this IDX stock")
        ).provider_symbol == ticker + ".JK"
        with pytest.raises(Clarification):
            await resolve_equity_symbol(db, 123, ticker)


@pytest.mark.asyncio
async def test_saved_idx_asset_controls_provider_lookup(env):
    _, sessions, _, _, service = env
    async with sessions.begin() as db:
        db.add(
            Asset(
                user_id=123,
                symbol="BYAN",
                exchange="IDX",
                provider_symbol="BYAN.JK",
                name="BYAN",
                asset_type="stock",
                currency="IDR",
            )
        )
    calls = []

    async def fetch(kind, key):
        calls.append((kind, key))
        return {"symbol": key, "price": "100", "currency": "IDR", "source": "mock", "as_of": "2026-09-29"}

    service.market.equity.fetch = fetch
    async with sessions.begin() as db:
        assert (await resolve_equity_symbol(db, 123, "BYAN.JK")).resolution_source == "user_asset"
        value = await service.market.get(db, 123, "equity", "BYAN")
    assert calls == [("equity", "BYAN.JK")]
    assert value["canonical_symbol"] == "BYAN"
    assert value["exchange"] == "IDX"
    assert value["provider_symbol"] == "BYAN.JK"
    assert value["fetched_at"] and value["stale"] is False


@pytest.mark.asyncio
async def test_legacy_idr_stock_resolves_without_double_jk_suffix(env):
    _, sessions, _, _, _ = env
    async with sessions.begin() as db:
        db.add(
            Asset(
                user_id=123,
                symbol="BYAN",
                provider_symbol="BYAN",
                name="BYAN",
                asset_type="stock",
                currency="IDR",
            )
        )
    async with sessions() as db:
        identity = await resolve_equity_symbol(db, 123, "BYAN.JK")
    assert identity.provider_symbol == "BYAN.JK"
    assert identity.canonical_symbol == "BYAN"


@pytest.mark.asyncio
async def test_two_saved_listings_require_exchange_for_bare_symbol(env):
    _, sessions, _, _, _ = env
    async with sessions.begin() as db:
        db.add_all(
            [
                Asset(
                    user_id=123,
                    symbol="ABC",
                    exchange="NASDAQ",
                    provider_symbol="ABC",
                    name="US ABC",
                    asset_type="stock",
                    currency="USD",
                ),
                Asset(
                    user_id=123,
                    symbol="ABC.JK",
                    exchange="IDX",
                    provider_symbol="ABC.JK",
                    name="IDX ABC",
                    asset_type="stock",
                    currency="IDR",
                ),
            ]
        )
    async with sessions() as db:
        with pytest.raises(Clarification):
            await resolve_equity_symbol(db, 123, "ABC")


def test_partial_portfolio_and_cash_shortfall_are_explicit():
    portfolio = {
        "holdings": [
            {"symbol": "BBCA", "provider_symbol": "BBCA.JK", "currency": "IDR", "value": "20000000"},
            {"symbol": "BYAN", "provider_symbol": "BYAN.JK", "currency": "IDR", "value": "30000000"},
            {"symbol": "XYZ", "provider_symbol": "XYZ.JK", "currency": "IDR", "value": None},
        ],
        "available_cash_snapshots": {"IDR": Decimal("5000000")},
        "unknown_cash_accounts": [],
    }
    result = purchase_scenario(portfolio, "BBCA.JK", "IDR", Decimal("10000000"))
    assert result["position_before_known"] == "20000000"
    assert result["position_after_known"] == "30000000"
    assert result["known_portfolio_value_before"] == "50000000"
    assert result["known_concentration_before"] == "40.0"
    assert result["true_total_concentration_known"] is False
    assert result["concentration_before_percent"] is None
    assert result["missing_prices"] == ["XYZ"]
    assert result["affordable_from_recorded_cash"] is False
    assert result["cash_shortfall"] == "5000000"
    assert result["cash_remaining"] == "-5000000"
    portfolio["holdings"].pop()
    assert purchase_scenario(portfolio, "BBCA.JK", "IDR", 1)["true_total_concentration_known"] is True
    portfolio["available_cash_snapshots"] = {}
    assert purchase_scenario(portfolio, "BBCA.JK", "IDR", 1)["affordable_from_recorded_cash"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("timezone", ["Asia/Jakarta", "Asia/Kuala_Lumpur", "America/New_York"])
async def test_statement_local_date_survives_utc_storage_and_monthly_query(env, timezone):
    _, sessions, _, _, _ = env
    content = b"date,description,debit,credit,currency\n2026-09-14,Coffee,48.000,,IDR\n"
    async with sessions.begin() as db:
        identifier, _ = await preview_statement(db, 123, "bank.csv", content, timezone=timezone)
    async with sessions.begin() as db:
        await commit_statement(db, 123, identifier, timezone)
    async with sessions() as db:
        transaction = await db.scalar(select(Transaction).where(Transaction.user_id == 123))
        assert (
            transaction.date.replace(tzinfo=UTC).astimezone(ZoneInfo(timezone)).date().isoformat()
            == "2026-09-14"
        )
        assert transaction.date.replace(tzinfo=UTC) == statement_utc_date("2026-09-14", timezone)
        start, end = month_range(datetime(2026, 9, 14, tzinfo=UTC), timezone)
        totals = await summary(db, 123, start, end)
        assert totals["by_currency"]["IDR"]["expense"] == Decimal("48000")


@pytest.mark.asyncio
async def test_review_row_becomes_importable_only_after_explicit_direction(env):
    _, sessions, _, _, _ = env
    content = b"date,description,amount,currency\n2026-09-14,STARBUCKS,48.000,IDR\n"
    async with sessions.begin() as db:
        identifier, _ = await preview_statement(db, 123, "bank.csv", content)
    async with sessions() as db:
        assert "Row 2" in await review_rows(db, 123)
    async with sessions.begin() as db:
        assert "ready" in await review_row(db, 123, 2, "expense")
    async with sessions.begin() as db:
        assert "Imported 1" in await commit_statement(db, 123, identifier)
    async with sessions() as db:
        row = await db.scalar(select(Transaction).where(Transaction.user_id == 123))
        assert row.amount == Decimal("48000") and row.transaction_type == "expense"


def test_config_and_example_briefing_sections_agree():
    expected = "today,reminders,tasks,finance,notable,priorities"
    assert Settings(_env_file=None).daily_briefing_sections == expected
    assert f"DAILY_BRIEFING_SECTIONS={expected}" in Path(".env.example").read_text()


def test_priority_respects_urgency_and_blocks_over_calendar_convenience():
    now = utcnow()
    short = Task(user_id=123, title="Short", status="todo", priority="low", estimated_minutes=20)
    long = Task(user_id=123, title="Long", status="todo", priority="low", estimated_minutes=120)
    overdue = Task(
        user_id=123, title="Overdue", status="todo", priority="medium", due_at=now - timedelta(days=1)
    )
    critical = Task(user_id=123, title="Critical", status="todo", priority="critical")
    blocked = Task(user_id=123, title="Blocked", status="blocked", priority="medium")
    assert priority_score(short, now, 30) > priority_score(long, now, 30)
    assert priority_score(overdue, now, 30) > priority_score(short, now, 30)
    assert priority_score(critical, now, 30) > priority_score(short, now, 30)
    assert priority_score(blocked, now, 30) < priority_score(short, now, 30)


@pytest.mark.parametrize(
    "text",
    [
        "deep council: should I buy this?",
        "run the full council",
        "give me a deep decision analysis",
        "analyze this deeply using the council",
        "use deep council mode",
    ],
)
def test_explicit_deep_requests(text):
    assert explicit_deep_request(text)


def test_normal_decision_is_fast():
    assert not explicit_deep_request("Should I buy this?")


def test_legacy_cached_fundamental_names_are_normalized():
    data = normalize_fundamentals_payload({"eps": "12", "revenue_ttm": "500", "market_cap": "1000"})
    assert data["eps_ttm"] == "12"
    assert data["revenue_ttm"] == "500"
    assert data["market_cap"] == "1000"
    assert data["net_income_ttm"] is None


def test_indonesian_macro_never_substitutes_us_series():
    assert canonical_macro_series("US_FED_FUNDS", "What is the BI rate?") == "ID_BI_RATE"
    assert canonical_macro_series("US_CPI", "Indonesia inflation") == "ID_CPI"


@pytest.mark.asyncio
async def test_partial_fundamentals_are_retained_without_false_missing_flags(env):
    _, sessions, _, _, service = env
    overview = {
        "Symbol": "BYAN.JK",
        "MarketCapitalization": "1000",
        "EPS": "12",
        "PERatio": "8",
        "RevenueTTM": "500",
    }
    normalized = AlphaVantageAdapter.fundamentals(overview)
    assert normalized["revenue_ttm"] == "500"
    assert normalized["eps_ttm"] == "12"

    async def fetch(kind, key):
        if kind == "fundamentals":
            return {"symbol": key, **normalized, "source": "mock", "as_of": "2026-09-29"}
        return {"symbol": key, "price": "100", "currency": "IDR", "source": "mock", "as_of": "2026-09-29"}

    service.market.equity.fetch = fetch
    async with sessions.begin() as db:
        report = await research(db, 123, service.market, "BYAN.JK", context="Analyze BYAN.JK")
    assert report.fundamentals["revenue_ttm"] == "500"
    assert report.fundamentals["eps_ttm"] == "12"
    assert report.fundamentals["pe"] == "8"
    assert "revenue_ttm" not in report.missing_data
    assert "eps_ttm" not in report.missing_data
    assert "net_income_ttm" in report.missing_data


@pytest.mark.asyncio
async def test_category_correction_and_deletion_refresh_sheets_outbox(env):
    _, sessions, model, _, service = env
    model.route("finance.log_expense", amount="48000", merchant="Cafe", currency="IDR")
    await service.handle(123, "audit-expense", "Spent 48000 at Cafe")
    async with sessions.begin() as db:
        transaction = await db.scalar(select(Transaction).where(Transaction.user_id == 123))
        tx_id = transaction.id
        outbox = await db.scalar(
            select(SpreadsheetSyncOutbox).where(
                SpreadsheetSyncOutbox.user_id == 123,
                SpreadsheetSyncOutbox.entity_type == "transaction",
                SpreadsheetSyncOutbox.entity_id == tx_id,
                SpreadsheetSyncOutbox.operation == "upsert",
            )
        )
        outbox.status = "done"
    model.route("finance.category", target_id=tx_id, category="Travel")
    await service.handle(123, "audit-category", "Change that transaction to Travel")
    async with sessions() as db:
        outbox = await db.scalar(
            select(SpreadsheetSyncOutbox).where(
                SpreadsheetSyncOutbox.user_id == 123,
                SpreadsheetSyncOutbox.entity_type == "transaction",
                SpreadsheetSyncOutbox.entity_id == tx_id,
                SpreadsheetSyncOutbox.operation == "upsert",
            )
        )
        assert outbox.status == "pending"
    model.route("finance.delete", target_id=tx_id)
    pending = await service.handle(123, "audit-delete", "Delete that transaction")
    await service.confirm(123, pending.confirmation_id, True)
    async with sessions() as db:
        deletion = await db.scalar(
            select(SpreadsheetSyncOutbox).where(
                SpreadsheetSyncOutbox.user_id == 123,
                SpreadsheetSyncOutbox.entity_type == "transaction",
                SpreadsheetSyncOutbox.entity_id == tx_id,
                SpreadsheetSyncOutbox.operation == "delete",
            )
        )
        assert deletion and deletion.status == "pending"


@pytest.mark.asyncio
async def test_account_holding_and_decision_mutations_queue_sheets(env):
    _, sessions, model, _, service = env
    model.route(
        "finance.account", account="Broker", account_type="brokerage", currency="IDR", amount="5000000"
    )
    pending = await service.handle(123, "audit-account", "Broker has 5m IDR")
    await service.confirm(123, pending.confirmation_id, True)
    async with sessions() as db:
        account = await db.scalar(select(Account).where(Account.user_id == 123, Account.name == "Broker"))
        assert await db.scalar(
            select(SpreadsheetSyncOutbox).where(
                SpreadsheetSyncOutbox.entity_type == "account", SpreadsheetSyncOutbox.entity_id == account.id
            )
        )
    model.route(
        "portfolio.holding",
        symbol="BYAN",
        exchange="IDX",
        asset_type="stock",
        currency="IDR",
        account="Broker",
        quantity="2",
        price="100000",
    )
    pending = await service.handle(123, "audit-holding", "I own 2 BYAN shares on IDX")
    await service.confirm(123, pending.confirmation_id, True)
    async with sessions() as db:
        asset = await db.scalar(select(Asset).where(Asset.user_id == 123, Asset.symbol == "BYAN"))
        assert asset.provider_symbol == "BYAN.JK" and asset.exchange == "IDX"
        assert await db.scalar(
            select(SpreadsheetSyncOutbox).where(SpreadsheetSyncOutbox.entity_type == "investment")
        )
    async with sessions.begin() as db:
        decision = Decision(
            user_id=123,
            user_question="Buy BYAN?",
            decision_type="investment",
            context_snapshot={},
            final_recommendation={"decision": "WAIT"},
            final_confidence=0,
        )
        db.add(decision)
        await db.flush()
        decision_id = decision.id
    model.route("decision.outcome", target_id=decision_id, description="I waited", satisfaction=80)
    await service.handle(123, "audit-outcome", "I waited on that decision")
    async with sessions() as db:
        assert await db.scalar(
            select(SpreadsheetSyncOutbox).where(
                SpreadsheetSyncOutbox.entity_type == "decision",
                SpreadsheetSyncOutbox.entity_id == decision_id,
            )
        )


@pytest.mark.asyncio
async def test_sheets_degrades_after_repeated_failures_without_hammering(env):
    settings, sessions, model, calendar, service = env
    model.route("finance.log_expense", amount="48000", merchant="Cafe", currency="IDR")
    await service.handle(123, "audit-sheets", "Spent 48000 at Cafe")
    async with sessions.begin() as db:
        row = await db.scalar(
            select(SpreadsheetSyncOutbox).where(SpreadsheetSyncOutbox.entity_type == "transaction")
        )
        row.attempts = 7
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
        row = await db.scalar(
            select(SpreadsheetSyncOutbox).where(SpreadsheetSyncOutbox.entity_type == "transaction")
        )
        assert row.status == "degraded" and row.attempts == 8
        assert row.last_error == "ConnectError" and row.last_attempt_at is not None
        assert row.next_attempt_at > row.last_attempt_at + timedelta(hours=5)


@pytest.mark.asyncio
async def test_cross_domain_foundation_does_not_claim_pattern_on_sparse_data(env):
    _, sessions, _, _, _ = env
    async with sessions() as db:
        sample = await cross_domain_periods(db, 123, "Asia/Kuala_Lumpur")
    assert sample == {"periods": {}, "enough_periods_for_correlation": False}
