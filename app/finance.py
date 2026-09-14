from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.database import Account, Category, MerchantRule, Transaction, utcnow
from app.portfolio import portfolio_snapshot
from app.validation import Clarification, money, parse_datetime

CATEGORIES = [
    "Food & Drinks",
    "Transport",
    "Shopping",
    "Sports",
    "Entertainment",
    "Gaming",
    "Healthcare",
    "Education",
    "Housing",
    "Utilities",
    "Subscriptions",
    "Travel",
    "Investment",
    "Gifts",
    "Miscellaneous",
]


def month_range(now, timezone, offset=0):
    local = now.astimezone(ZoneInfo(timezone))
    index = local.year * 12 + local.month - 1 + offset
    start = datetime(index // 12, index % 12 + 1, 1, tzinfo=ZoneInfo(timezone))
    end_index = index + 1
    end = datetime(end_index // 12, end_index % 12 + 1, 1, tzinfo=ZoneInfo(timezone))
    return start, end


async def seed_categories(db, user_id):
    existing = set((await db.scalars(select(Category.name).where(Category.user_id == user_id))).all())
    for name in CATEGORIES:
        if name not in existing:
            db.add(Category(user_id=user_id, name=name, subcategory=""))


async def add_transaction(db, user_id, e, source, original, settings, confidence, receipt_id=None):
    existing = await db.scalar(
        select(Transaction).where(Transaction.user_id == user_id, Transaction.source_message_id == source)
    )
    if existing:
        return existing
    currency = (e.currency or settings.default_currency).upper()
    if len(currency) != 3 or not currency.isalpha():
        raise Clarification("Please use a three-letter currency code.")
    amount = money(e.amount or "", currency)
    merchant = (e.merchant or "").strip()
    rule = await db.scalar(
        select(MerchantRule).where(
            MerchantRule.user_id == user_id, MerchantRule.merchant == merchant.casefold()
        )
    )
    category = rule.category if rule else e.category or "Miscellaneous"
    subcategory = rule.subcategory if rule else e.subcategory or ""
    account = None
    if e.account:
        account = await db.scalar(
            select(Account).where(Account.user_id == user_id, Account.name == e.account.strip())
        )
        if not account:
            # An account name is evidence of an account, never evidence of its balance.
            account = Account(
                user_id=user_id, name=e.account.strip(), type=e.account_type or "bank", currency=currency
            )
            db.add(account)
            await db.flush()
        if account.currency != currency:
            raise Clarification(
                "That account uses a different currency. Specify the correct account or converted amount."
            )
    timestamp = parse_datetime(e.start, settings.user_timezone) if e.start else utcnow()
    transaction = Transaction(
        user_id=user_id,
        date=timestamp,
        amount=amount,
        currency=currency,
        merchant=merchant,
        description=e.description or "",
        category=category,
        subcategory=subcategory,
        transaction_type=e.transaction_type or "expense",
        account_id=account.id if account else None,
        payment_method=e.payment_method or e.account or "",
        source="receipt" if receipt_id else "telegram",
        source_message_id=source,
        receipt_id=receipt_id,
        confidence=confidence,
        original_input=original,
    )
    db.add(transaction)
    await db.flush()
    # current_balance is an explicit reconciled snapshot, never silently changed by backdated logs.
    return transaction


async def correct_category(db, user_id, e):
    if not e.category:
        raise Clarification("Which category should I use?")
    sub = e.subcategory or ""
    category = await db.scalar(
        select(Category).where(
            Category.user_id == user_id, Category.name == e.category, Category.subcategory == sub
        )
    )
    if not category:
        db.add(Category(user_id=user_id, name=e.category, subcategory=sub))
    if e.merchant:
        normalized = e.merchant.strip().casefold()
        rule = await db.scalar(
            select(MerchantRule).where(MerchantRule.user_id == user_id, MerchantRule.merchant == normalized)
        )
        if not rule:
            rule = MerchantRule(user_id=user_id, merchant=normalized)
            db.add(rule)
        rule.category, rule.subcategory = e.category, sub
    if e.target_id:
        transaction = await db.scalar(
            select(Transaction).where(Transaction.user_id == user_id, Transaction.id == e.target_id)
        )
        if not transaction:
            raise Clarification("I could not find that transaction.")
        transaction.category, transaction.subcategory = e.category, sub
    return "Saved the category preference for future transactions." if e.merchant else "Saved the category."


async def account_snapshot(db, user_id, e, settings):
    if not e.account:
        raise Clarification("What is the account name?")
    account = await db.scalar(
        select(Account).where(Account.user_id == user_id, Account.name == e.account.strip())
    )
    if not account:
        account = Account(
            user_id=user_id,
            name=e.account.strip(),
            type=e.account_type or "bank",
            currency=(e.currency or settings.default_currency).upper(),
        )
        db.add(account)
    if e.currency and account.currency != e.currency.upper():
        raise Clarification("Create a separate account for a different currency.")
    if e.amount is not None:
        account.current_balance = Decimal(0) if e.amount.strip() == "0" else money(e.amount, account.currency)
        account.balance_as_of = utcnow()
    return f"Saved {account.name}. Balances are explicit snapshots; reconcile them when needed."


async def summary(db, user_id, start, end, category=None):
    conditions = [Transaction.user_id == user_id, Transaction.date >= start, Transaction.date < end]
    if category:
        conditions.append(func.lower(Transaction.category) == category.casefold())
    totals = (
        await db.execute(
            select(Transaction.currency, Transaction.transaction_type, func.sum(Transaction.amount))
            .where(*conditions)
            .group_by(Transaction.currency, Transaction.transaction_type)
        )
    ).all()
    currencies = defaultdict(
        lambda: {
            "expense": Decimal(0),
            "income": Decimal(0),
            "transfer": Decimal(0),
            "investment": Decimal(0),
            "dividend": Decimal(0),
            "interest": Decimal(0),
        }
    )
    for currency, kind, total in totals:
        currencies[currency][kind] = total
    for values in currencies.values():
        income = values["income"] + values["dividend"] + values["interest"]
        values["cash_flow"] = income - values["expense"] - values["investment"]
        values["savings_rate_pct"] = (income - values["expense"]) / income * 100 if income else None
    categories = (
        await db.execute(
            select(Transaction.currency, Transaction.category, func.sum(Transaction.amount))
            .where(*conditions, Transaction.transaction_type == "expense")
            .group_by(Transaction.currency, Transaction.category)
        )
    ).all()
    largest = (
        await db.scalars(
            select(Transaction)
            .where(*conditions, Transaction.transaction_type == "expense")
            .order_by(Transaction.amount.desc())
            .limit(10)
        )
    ).all()
    count = await db.scalar(select(func.count()).select_from(Transaction).where(*conditions))
    return {
        "start": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "category_filter": category,
        "transaction_count": count,
        "by_currency": dict(currencies),
        "category_totals": [
            {"currency": c, "category": name, "total": amount} for c, name, amount in categories
        ],
        "largest_purchases": [
            {
                "id": t.id,
                "merchant": t.merchant,
                "amount": t.amount,
                "currency": t.currency,
                "date": str(t.date),
            }
            for t in largest
        ],
    }


async def financial_context(db, user_id, settings):
    now = utcnow()
    start, end = month_range(now, settings.user_timezone)
    current = await summary(db, user_id, start, end)
    history = []
    for offset in (-3, -2, -1):
        lo, hi = month_range(now, settings.user_timezone, offset)
        history.append(await summary(db, user_id, lo, hi))
    # Average only recorded complete months; missing months are unknown, not zero.
    totals, samples = defaultdict(Decimal), defaultdict(int)
    for month in history:
        for currency, values in month["by_currency"].items():
            totals[currency] += values["expense"]
            samples[currency] += 1
    repeated = (
        await db.execute(
            select(Transaction.merchant, Transaction.currency, Transaction.amount, func.count())
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == "expense",
                Transaction.date >= month_range(now, settings.user_timezone, -3)[0],
                Transaction.merchant != "",
            )
            .group_by(Transaction.merchant, Transaction.currency, Transaction.amount)
            .having(func.count() >= 3)
            .limit(20)
        )
    ).all()
    return {
        "this_month": current,
        "previous_months": history,
        "recorded_monthly_average": {c: totals[c] / samples[c] for c in totals},
        "average_sample_months": dict(samples),
        "possible_recurring_expenses": [
            {"merchant": m, "currency": c, "amount": a, "count": n} for m, c, a, n in repeated
        ],
        "portfolio": await portfolio_snapshot(db, user_id),
        "coverage_note": "Recorded activity only. Missing data is unknown. Current month is partial. Repeated amounts are candidates, not proven subscriptions.",
    }
