from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.database import Base, Reminder, Transaction, make_database, utcnow
from app.exports import export_finance
from app.memory import conversation_context, remember_conversation, retrieve, set_memory
from app.reminders import change_reminder, create_reminder
from app.schemas import Entities
from app.telegram import Gateway
from app.validation import Clarification


async def test_records_survive_a_fresh_database_connection(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'ponke.db'}"
    engine, sessions = make_database(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions.begin() as db:
        db.add(
            Transaction(
                user_id=123,
                date=utcnow(),
                amount=48000,
                currency="IDR",
                merchant="Coffee shop",
                category="Food & Drinks",
                confidence=1,
                source_message_id="restart-expense",
                original_input="Spent 48k on coffee",
            )
        )
        await set_memory(db, 123, "preference.reply_style", "short and direct")
        await remember_conversation(db, 123, "Spent 48k on coffee", "Logged Rp48,000")
    await engine.dispose()

    reopened_engine, reopened_sessions = make_database(url)
    try:
        async with reopened_sessions() as db:
            transaction = await db.scalar(select(Transaction).where(Transaction.user_id == 123))
            assert transaction.amount == 48000
            assert (await retrieve(db, 123, "preference."))["preference.reply_style"] == "short and direct"
            assert len(await conversation_context(db, 123)) == 2
    finally:
        await reopened_engine.dispose()


async def test_allowed_users_cannot_read_or_change_each_others_records(env, future):
    settings, sessions, model, _, service = env
    model.route("finance.log_expense", amount="48k", merchant="Private cafe", category="Food & Drinks")
    await service.handle(123, "private-expense", "Spent 48k at Private cafe")
    async with sessions.begin() as db:
        await set_memory(db, 123, "preference.nickname", "Aldo")
        reminder = await create_reminder(
            db,
            123,
            Entities(title="Private reminder", start=future.isoformat()),
            "private-reminder",
            settings,
        )
        reminder_id = reminder.id
        transaction_id = (await db.scalar(select(Transaction).where(Transaction.user_id == 123))).id

    model.route("finance.query")
    calls_before_other_user = len(model.calls)
    other_summary = await service.handle(456, "other-summary", "What did I spend this month?")
    assert "Transactions: 0" in other_summary.text
    assert "Private cafe" not in other_summary.text
    assert all("Private cafe" not in str(call[2]) for call in model.calls[calls_before_other_user:])
    async with sessions() as db:
        other_export, _ = await export_finance(db, 456, "csv")
        assert "Private cafe" not in other_export.decode("utf-8-sig")
        assert await retrieve(db, 456, "preference.") == {}
        assert all("Private cafe" not in item["text"] for item in await conversation_context(db, 456))
        with pytest.raises(Clarification):
            await change_reminder(db, 456, reminder_id, "cancelled")

    model.route("finance.delete", target_id=transaction_id)
    pending_delete = await service.handle(456, "other-delete", "Delete that transaction")
    assert pending_delete.confirmation_id
    other_delete = await service.confirm(456, pending_delete.confirmation_id, True)
    assert "could not find" in other_delete.text
    async with sessions() as db:
        assert await db.scalar(select(Transaction).where(Transaction.id == transaction_id))
        assert (await db.scalar(select(Reminder).where(Reminder.id == reminder_id))).status == "active"


async def test_id_command_reveals_only_private_senders_own_id(env):
    settings, _, model, _, service = env
    gateway = Gateway(settings, service)
    response = AsyncMock()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=789),
        effective_chat=SimpleNamespace(id=789, type="private"),
        effective_message=SimpleNamespace(reply_text=response),
    )
    await gateway.id_command(update, None)
    response.assert_awaited_once_with(
        "Your Telegram user ID is 789. The bot owner can add this ID to the allowlist."
    )
    update.effective_chat = SimpleNamespace(id=-789, type="group")
    await gateway.id_command(update, None)
    response.assert_awaited_once()
    assert not model.calls
