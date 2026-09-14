import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import Account, Transaction, make_database, utcnow


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for PostgreSQL integration"
)
async def test_postgres_migrated_schema_and_decimal_round_trip():
    engine, sessions = make_database(os.environ["TEST_DATABASE_URL"])
    async with sessions() as db:
        async with db.begin():
            account = Account(user_id=987654321, name="test-" + uuid4().hex, currency="IDR", type="bank")
            db.add(account)
            await db.flush()
            transaction = Transaction(
                user_id=987654321,
                account_id=account.id,
                date=utcnow(),
                amount=Decimal("123456.7891"),
                currency="IDR",
                category="Food & Drinks",
                confidence=0.99,
                source_message_id=uuid4().hex,
                original_input="test",
            )
            db.add(transaction)
            await db.flush()
            identifier = transaction.id
            db.expire_all()
            result = await db.scalar(select(Transaction).where(Transaction.id == identifier))
            assert result.amount == Decimal("123456.7891")
            await db.rollback()
    await engine.dispose()
