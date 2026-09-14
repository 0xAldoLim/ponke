from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.database import Account, PendingAction, Reminder, Transaction
from app.portfolio import portfolio_snapshot, update_portfolio
from app.reminders import SchedulerWorker, change_reminder
from app.schemas import Entities


async def test_portfolio_precision_liabilities_and_allocation(env):
    settings, sessions, _, _, _ = env
    async with sessions.begin() as db:
        db.add(Account(user_id=123, name="BCA", type="bank", currency="IDR", current_balance=20000000))
        db.add(Account(user_id=123, name="Debt", type="liability", currency="IDR", current_balance=2000000))
        db.add(Account(user_id=123, name="Binance", type="crypto", currency="IDR"))
    async with sessions.begin() as db:
        await update_portfolio(
            db,
            123,
            "portfolio.holding",
            Entities(
                symbol="BTC",
                asset_type="crypto",
                currency="IDR",
                account="Binance",
                quantity="0.0123456789",
                price="900000000",
            ),
            "p1",
        )
        await update_portfolio(db, 123, "portfolio.price", Entities(symbol="BTC", price="1000000000"), "p2")
    async with sessions() as db:
        result = await portfolio_snapshot(db, 123)
        assert result["portfolio_totals"]["IDR"] == Decimal("12345678.9000000000")
        assert result["reported_net_worth"]["IDR"] == Decimal("30345678.9000000000")
        assert Decimal(result["holdings"][0]["allocation_pct"]) == 100


async def test_corrected_receipt_still_checks_duplicates(env, receipt_image):
    _, sessions, model, _, service = env
    await service.handle(123, "original", "", receipt_image, "file1")
    model.receipt.total = None
    model.receipt.total_confidence = 0.1
    await service.handle(123, "blurry2", "", receipt_image, "file2")
    async with sessions() as db:
        pending = await db.scalar(select(PendingAction).where(PendingAction.status == "clarification"))
    model.route("finance.receipt", amount="78k", target_id=pending.id)
    corrected = await service.handle(123, "correction2", "78k")
    duplicate = await service.confirm(123, corrected.confirmation_id, True)
    assert "appears to match" in duplicate.text and duplicate.confirmation_id
    async with sessions() as db:
        assert len((await db.scalars(select(Transaction))).all()) == 1


async def test_completing_recurring_occurrence_preserves_recurrence(env, future):
    settings, sessions, model, _, service = env
    model.route(
        "reminder.create", title="Review", start=future.isoformat(), recurrence="FREQ=WEEKLY;BYDAY=FR"
    )
    reply = await service.handle(123, "weekly", "Remind me every Friday")
    worker = SchedulerWorker(sessions, settings, None, service.briefing)
    await worker.enqueue(future + timedelta(seconds=1))
    async with sessions.begin() as db:
        await change_reminder(db, 123, reply.reminder_id, "completed")
    async with sessions() as db:
        reminder = await db.get(Reminder, reply.reminder_id)
        assert reminder.status == "active"


async def test_google_auth_link_not_in_model_context(env):
    _, _, model, _, service = env
    await service.handle(123, "connect", "/connect_calendar")
    await service.handle(123, "next", "Hello")
    assert all("accounts.google.com" not in str(call[2]) for call in model.calls)


async def test_bulk_delete_only_reviewed_records(env):
    _, sessions, model, _, service = env
    model.route("finance.log_expense", amount="10k")
    await service.handle(123, "bulk-old", "10k")
    model.route("finance.delete_all")
    pending = await service.handle(123, "bulk-request", "Delete all my transactions")
    assert pending.confirmation_id and "1 currently recorded" in pending.text
    model.route("finance.log_expense", amount="20k")
    await service.handle(123, "bulk-new", "20k")
    reply = await service.confirm(123, pending.confirmation_id, True)
    assert "Deleted 1 reviewed" in reply.text
    async with sessions() as db:
        remaining = (await db.scalars(select(Transaction))).all()
        assert len(remaining) == 1 and remaining[0].amount == 20000
