from datetime import timedelta

from sqlalchemy import delete, select

from app.database import Conversation, Memory, utcnow
from app.validation import Clarification


async def conversation_context(db, user_id):
    rows = (
        await db.scalars(
            select(Conversation)
            .where(Conversation.user_id == user_id, Conversation.created_at >= utcnow() - timedelta(days=7))
            .order_by(Conversation.created_at.desc())
            .limit(8)
        )
    ).all()
    return [{"role": r.role, "text": r.text[:3000]} for r in reversed(rows)]


async def remember_conversation(db, user_id, question, response):
    db.add(Conversation(user_id=user_id, role="user", text=question[:6000]))
    db.add(Conversation(user_id=user_id, role="assistant", text=response[:6000]))
    await db.execute(
        delete(Conversation).where(
            Conversation.user_id == user_id, Conversation.created_at < utcnow() - timedelta(days=7)
        )
    )


async def retrieve(db, user_id, prefix):
    rows = (
        await db.scalars(
            select(Memory)
            .where(Memory.user_id == user_id, Memory.key.startswith(prefix, autoescape=True))
            .limit(20)
        )
    ).all()
    return {row.key: row.value for row in rows}


async def set_memory(db, user_id, key, value):
    if not key or not value or len(key) > 100 or len(value) > 2000:
        raise Clarification("Please provide a short preference and its value.")
    row = await db.scalar(select(Memory).where(Memory.user_id == user_id, Memory.key == key))
    if not row:
        row = Memory(user_id=user_id, key=key)
        db.add(row)
    row.value = value
