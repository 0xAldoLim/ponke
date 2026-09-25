from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(UTC)


def uid():
    return uuid4().hex


class Base(DeclarativeBase):
    pass


class Owned:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Account(Owned, Base):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("user_id", "name"),)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(30), default="bank")
    currency: Mapped[str] = mapped_column(String(3), default="IDR")
    current_balance: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    balance_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Category(Owned, Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "name", "subcategory"),)
    name: Mapped[str] = mapped_column(String(100))
    subcategory: Mapped[str] = mapped_column(String(100), default="")


class MerchantRule(Owned, Base):
    __tablename__ = "merchant_rules"
    __table_args__ = (UniqueConstraint("user_id", "merchant"),)
    merchant: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100))
    subcategory: Mapped[str] = mapped_column(String(100), default="")


class Receipt(Owned, Base):
    __tablename__ = "receipts"
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    telegram_file_id: Mapped[str] = mapped_column(String(200))
    perceptual_hash: Mapped[str] = mapped_column(String(16))
    extracted: Mapped[dict] = mapped_column(JSON)


class Transaction(Owned, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("user_id", "source_message_id"),
        Index("ix_transaction_user_date", "user_id", "date"),
    )
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    currency: Mapped[str] = mapped_column(String(3))
    merchant: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100))
    subcategory: Mapped[str] = mapped_column(String(100), default="")
    transaction_type: Mapped[str] = mapped_column(String(30), default="expense")
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"))
    payment_method: Mapped[str] = mapped_column(String(100), default="")
    source: Mapped[str] = mapped_column(String(30), default="telegram")
    source_message_id: Mapped[str] = mapped_column(String(100))
    receipt_id: Mapped[str | None] = mapped_column(ForeignKey("receipts.id"))
    confidence: Mapped[float]
    notes: Mapped[str] = mapped_column(Text, default="")
    original_input: Mapped[str] = mapped_column(Text)


class Reminder(Owned, Base):
    __tablename__ = "reminders"
    text: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    timezone: Mapped[str] = mapped_column(String(60))
    recurrence: Mapped[str | None] = mapped_column(String(300))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="active")
    source_message_id: Mapped[str] = mapped_column(String(100))


class Delivery(Owned, Base):
    __tablename__ = "deliveries"
    __table_args__ = (UniqueConstraint("user_id", "delivery_key"),)
    delivery_key: Mapped[str] = mapped_column(String(150))
    text: Mapped[str] = mapped_column(Text)
    reminder_id: Mapped[str | None] = mapped_column(ForeignKey("reminders.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Asset(Owned, Base):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("user_id", "symbol"),)
    symbol: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    asset_type: Mapped[str] = mapped_column(String(30))
    currency: Mapped[str] = mapped_column(String(3))
    manual_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    price_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Holding(Owned, Base):
    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("user_id", "asset_id", "account_id"),)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    average_cost: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    purchase_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvestmentTransaction(Owned, Base):
    __tablename__ = "investment_transactions"
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    side: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    fees: Mapped[Decimal] = mapped_column(Numeric(24, 4), default=0)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_message_id: Mapped[str] = mapped_column(String(100))
    __table_args__ = (UniqueConstraint("user_id", "source_message_id"),)


class Decision(Owned, Base):
    __tablename__ = "decisions"
    user_question: Mapped[str] = mapped_column(Text)
    decision_type: Mapped[str] = mapped_column(String(40))
    context_snapshot: Mapped[dict] = mapped_column(JSON)
    final_recommendation: Mapped[dict] = mapped_column(JSON)
    final_confidence: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="recommended")
    follow_up_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentOpinion(Base):
    __tablename__ = "agent_opinions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"), index=True)
    agent_name: Mapped[str] = mapped_column(String(60))
    round: Mapped[int] = mapped_column(Integer)
    position: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[int] = mapped_column(Integer)
    score: Mapped[int] = mapped_column(Integer)
    summarized_reasoning: Mapped[dict] = mapped_column(JSON)
    recommended_action: Mapped[str] = mapped_column(Text)


class DecisionOutcome(Owned, Base):
    __tablename__ = "decision_outcomes"
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"))
    outcome_description: Mapped[str] = mapped_column(Text)
    measurable_result: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    result_currency: Mapped[str | None] = mapped_column(String(3))
    user_action: Mapped[str | None] = mapped_column(String(250))
    user_satisfaction: Mapped[int | None] = mapped_column(Integer)


class Memory(Owned, Base):
    __tablename__ = "memories"
    __table_args__ = (UniqueConstraint("user_id", "key"),)
    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[str] = mapped_column(Text)


class Activity(Owned, Base):
    __tablename__ = "activities"
    kind: Mapped[str] = mapped_column(String(60))
    reference: Mapped[str] = mapped_column(String(100), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Conversation(Owned, Base):
    __tablename__ = "conversations"
    role: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)


class PendingAction(Owned, Base):
    __tablename__ = "pending_actions"
    payload: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending")


class OAuthToken(Owned, Base):
    __tablename__ = "oauth_tokens"
    __table_args__ = (UniqueConstraint("user_id"),)
    encrypted: Mapped[str] = mapped_column(Text)


class OAuthState(Owned, Base):
    __tablename__ = "oauth_states"
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    verifier_encrypted: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Inbound(Owned, Base):
    __tablename__ = "inbound"
    __table_args__ = (UniqueConstraint("user_id", "message_key"),)
    message_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="processing")
    reply: Mapped[str | None] = mapped_column(Text)


class MarketCache(Base):
    __tablename__ = "market_cache"
    __table_args__ = (UniqueConstraint("provider", "cache_key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    provider: Mapped[str] = mapped_column(String(60))
    cache_key: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Project(Owned, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("user_id", "name"),)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active")


class Task(Owned, Base):
    __tablename__ = "tasks"
    title: Mapped[str] = mapped_column(String(250))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="todo")
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"))
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StatementImport(Owned, Base):
    __tablename__ = "statement_imports"
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(250))
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"))
    status: Mapped[str] = mapped_column(String(20), default="preview")
    rows: Mapped[dict] = mapped_column(JSON)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)


class SpreadsheetSyncOutbox(Owned, Base):
    __tablename__ = "spreadsheet_sync_outbox"
    __table_args__ = (UniqueConstraint("user_id", "entity_type", "entity_id", "operation"),)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(32))
    operation: Mapped[str] = mapped_column(String(20))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    last_error: Mapped[str] = mapped_column(Text, default="")


def make_database(url: str):
    engine = create_async_engine(url, pool_pre_ping=True, echo=False)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
