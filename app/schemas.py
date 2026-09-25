from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


Intent = Literal[
    "calendar.create",
    "calendar.query",
    "calendar.modify",
    "calendar.delete",
    "calendar.connect",
    "reminder.create",
    "reminder.query",
    "reminder.complete",
    "reminder.cancel",
    "finance.log_expense",
    "finance.query",
    "finance.receipt",
    "finance.export",
    "finance.delete",
    "finance.delete_all",
    "finance.account",
    "finance.category",
    "finance.budget",
    "finance.investment_analysis",
    "portfolio.holding",
    "portfolio.trade",
    "portfolio.price",
    "decision.request",
    "decision.history",
    "decision.outcome",
    "decision.details",
    "personal_analysis",
    "daily_briefing",
    "memory.set",
    "task.create",
    "task.query",
    "task.update",
    "task.complete",
    "project.create",
    "project.query",
    "market.quote",
    "market.macro",
    "investment.research",
    "data.sources",
    "council.calibration",
    "decision.follow_up",
    "general_question",
    "clarify",
]


class Entities(Strict):
    title: str | None = None
    amount: str | None = None
    currency: str | None = None
    merchant: str | None = None
    description: str | None = None
    category: str | None = None
    subcategory: str | None = None
    transaction_type: (
        Literal["expense", "income", "transfer", "investment", "dividend", "interest"] | None
    ) = None
    account: str | None = None
    account_type: Literal["bank", "cash", "ewallet", "brokerage", "crypto", "deposit", "liability"] | None = (
        None
    )
    payment_method: str | None = None
    start: str | None = None
    end: str | None = None
    recurrence: str | None = None
    target_id: str | None = None
    search: str | None = None
    format: Literal["xlsx", "csv"] | None = None
    symbol: str | None = None
    asset_type: Literal["stock", "crypto", "deposit", "bond", "mutual_fund", "cash", "other"] | None = None
    quantity: str | None = None
    price: str | None = None
    fees: str | None = None
    side: Literal["buy", "sell"] | None = None
    decision_type: Literal["investment", "purchase", "health", "career", "other"] | None = None
    satisfaction: int | None = Field(default=None, ge=0, le=100)
    actual_action: str | None = None
    result_amount: str | None = None
    memory_key: str | None = None
    memory_value: str | None = None
    analysis_depth: Literal["fast", "deep"] | None = None
    priority: Literal["low", "medium", "high", "critical"] | None = None
    status: Literal["todo", "in_progress", "blocked", "done", "cancelled"] | None = None
    project: str | None = None
    estimated_minutes: int | None = Field(default=None, ge=1, le=10080)


class IntentResult(Strict):
    intent: Intent
    confidence: float = Field(ge=0, le=1)
    entities: Entities
    requires_confirmation: bool
    clarification: str | None = None


class ReceiptItem(Strict):
    description: str
    quantity: str | None
    amount: str | None


class ReceiptData(Strict):
    merchant: str | None
    date: str | None
    time: str | None
    items: list[ReceiptItem]
    subtotal: str | None
    tax: str | None
    discounts: str | None
    total: str | None
    payment_method: str | None
    currency: str
    category: str
    subcategory: str | None
    confidence: float = Field(ge=0, le=1)
    total_confidence: float = Field(ge=0, le=1)


class Opinion(Strict):
    position: Literal["support", "oppose", "neutral", "conditional"]
    confidence: int = Field(ge=0, le=100)
    score: int = Field(ge=0, le=100)
    key_argument: str
    upside: list[str]
    downside: list[str]
    assumptions: list[str]
    risks: list[str]
    missing_information: list[str]
    what_would_change_my_mind: list[str]
    recommended_action: str
    strongest_opposing_argument: str | None
    overlooked_information: list[str]
    changed_position: bool


class Weights(Strict):
    macro: int = Field(ge=0, le=100)
    risk: int = Field(ge=0, le=100)
    lifestyle: int = Field(ge=0, le=100)
    health: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def sum_to_100(self):
        if sum(self.model_dump().values()) != 100:
            raise ValueError("Council relevance weights must sum to 100")
        return self


class Verdict(Strict):
    decision_type: str
    decision: Literal["PROCEED", "WAIT", "AVOID", "CONDITIONAL", "NEED INFORMATION"]
    confidence: int = Field(ge=0, le=100)
    weights: Weights
    relevance_explanation: str
    recommended_action: str
    common_ground: str = ""
    reasons: list[str]
    facts: list[str]
    assumptions: list[str]
    main_disagreement: str
    missing_evidence: list[str]
    what_would_change: list[str]


class Answer(Strict):
    text: str = Field(max_length=10000)


class SpecialistView(Strict):
    position: Literal["support", "oppose", "neutral", "conditional"]
    key_argument: str
    risks: list[str]
    missing_information: list[str]
    recommended_action: str


class DecisionSynthesis(Strict):
    decision_type: str
    decision: Literal["PROCEED", "WAIT", "AVOID", "CONDITIONAL", "NEED INFORMATION"]
    recommended_action: str
    common_ground: str
    main_disagreement: str
    missing_evidence: list[str]
