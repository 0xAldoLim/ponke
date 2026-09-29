from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select

from app.database import Account, Asset, Holding, InvestmentTransaction, utcnow
from app.validation import Clarification, aware, money


class MarketDataProvider(Protocol):
    async def get_price(self, user_id: int, symbol: str): ...
    async def get_history(self, user_id: int, symbol: str): ...
    async def get_asset_info(self, user_id: int, symbol: str): ...


class ManualMarketDataProvider:
    def __init__(self, sessions):
        self.sessions = sessions

    async def get_asset_info(self, user_id, symbol):
        async with self.sessions() as db:
            return await db.scalar(
                select(Asset).where(Asset.user_id == user_id, Asset.symbol == symbol.upper())
            )

    async def get_price(self, user_id, symbol):
        asset = await self.get_asset_info(user_id, symbol)
        return (
            None
            if not asset
            else {
                "price": asset.manual_price,
                "as_of": asset.price_as_of,
                "currency": asset.currency,
                "source": "manual",
            }
        )

    async def get_history(self, user_id, symbol):
        return []  # Manual snapshot provider does not imply historical price coverage.


async def portfolio_snapshot(db, user_id):
    rows = (
        await db.execute(
            select(Holding, Asset)
            .join(Asset, Holding.asset_id == Asset.id)
            .where(Holding.user_id == user_id, Asset.user_id == user_id)
        )
    ).all()
    totals = defaultdict(Decimal)
    holdings, missing = [], []
    for holding, asset in rows:
        if asset.manual_price is None:
            missing.append(asset.symbol)
            value = None
        else:
            value = holding.quantity * asset.manual_price
            totals[asset.currency] += value
        holdings.append(
            {
                "symbol": asset.symbol,
                "exchange": asset.exchange,
                "provider_symbol": asset.provider_symbol or asset.symbol,
                "quantity": str(holding.quantity),
                "currency": asset.currency,
                "value": str(value) if value is not None else None,
                "price_as_of": str(asset.price_as_of),
                "stale": not asset.price_as_of or aware(asset.price_as_of) < utcnow() - timedelta(days=1),
            }
        )
    for row in holdings:
        total = totals[row["currency"]]
        row["allocation_pct"] = str(Decimal(row["value"]) / total * 100) if row["value"] and total else None
    accounts = list(
        (await db.scalars(select(Account).where(Account.user_id == user_id, Account.active.is_(True)))).all()
    )
    cash, net, unknown = defaultdict(Decimal), defaultdict(Decimal, totals), []
    liabilities = defaultdict(Decimal)
    for account in accounts:
        # Brokerage/crypto/deposit balances can include their holdings; exclude to avoid double counting.
        if account.type in {"bank", "cash", "ewallet"}:
            if account.current_balance is None:
                unknown.append(account.name)
            else:
                cash[account.currency] += account.current_balance
                net[account.currency] += account.current_balance
        elif account.type == "liability":
            if account.current_balance is None:
                unknown.append(account.name)
            else:
                liabilities[account.currency] += account.current_balance
    known_net_worth = {
        currency: net[currency] - liabilities[currency] for currency in set(net) | set(liabilities)
    }
    return {
        "reported_liabilities": dict(liabilities),
        "reported_net_worth": known_net_worth,
        "holdings": holdings,
        "portfolio_totals": dict(totals),
        "available_cash_snapshots": dict(cash),
        "known_assets_subtotal": dict(net),
        "missing_prices": missing,
        "unknown_cash_accounts": unknown,
        "net_worth_complete": False,
        "note": "Balances and prices are user-maintained snapshots. Reported net worth subtracts recorded liability snapshots. Missing balances, liabilities or assets are unknown, not zero. Currencies are never combined.",
    }


async def update_portfolio(db, user_id, intent, entities, source):
    e = entities
    if not e.symbol:
        raise Clarification("Which asset symbol?")
    symbol = e.symbol.upper().strip()
    if e.exchange == "IDX" and not symbol.endswith(".JK"):
        provider_symbol = symbol + ".JK"
    else:
        provider_symbol = symbol
    exact = await db.scalar(select(Asset).where(Asset.user_id == user_id, Asset.symbol == symbol))
    by_provider = await db.scalar(
        select(Asset).where(Asset.user_id == user_id, Asset.provider_symbol == provider_symbol)
    )
    if exact and by_provider and exact.id != by_provider.id:
        raise Clarification(
            "Two saved listings share this ticker. Specify the exact exchange-qualified symbol."
        )
    if not e.exchange and "." not in symbol:
        idx_asset = await db.scalar(
            select(Asset).where(Asset.user_id == user_id, Asset.provider_symbol == symbol + ".JK")
        )
        if exact and idx_asset and exact.id != idx_asset.id:
            raise Clarification("Two saved listings share this ticker. Specify the exchange.")
    asset = by_provider or exact
    if asset and e.exchange and asset.exchange not in (None, e.exchange):
        raise Clarification("That saved asset belongs to another exchange. Use its exact listing symbol.")
    if asset and e.exchange == "IDX" and asset.asset_type == "stock" and asset.currency != "IDR":
        raise Clarification(
            "The saved asset currency conflicts with an IDX listing. Check the asset identity."
        )
    if not asset:
        if not e.currency or not e.asset_type:
            raise Clarification("For a new asset, include its currency and type.")
        if e.asset_type == "stock" and not (e.exchange or symbol.endswith(".JK")):
            raise Clarification("Which exchange is this stock on? Say IDX, NASDAQ, or NYSE.")
        asset = Asset(
            user_id=user_id,
            symbol=symbol,
            name=e.title or symbol,
            asset_type=e.asset_type,
            currency=e.currency.upper(),
            exchange=e.exchange or ("IDX" if symbol.endswith(".JK") else None),
            provider_symbol=provider_symbol,
        )
        db.add(asset)
        await db.flush()
    elif e.exchange:
        asset.exchange, asset.provider_symbol = e.exchange, provider_symbol
    if intent == "portfolio.price":
        asset.manual_price = money(e.price or e.amount or "", asset.currency)
        asset.price_as_of = utcnow()
        return f"Updated the manual price for {symbol}."
    account = await db.scalar(
        select(Account).where(Account.user_id == user_id, Account.name == (e.account or "").strip())
    )
    if not account:
        raise Clarification("Create the investment account first, including its currency and type.")
    if account.currency != asset.currency:
        raise Clarification("Account and asset currencies must match. FX conversion is not implemented.")
    try:
        quantity = Decimal(e.quantity or "")
        if (
            not quantity.is_finite()
            or not 0 < quantity < Decimal("1e18")
            or quantity != quantity.quantize(Decimal("0.0000000001"))
        ):
            raise ValueError()
    except (ValueError, ArithmeticError) as exc:
        raise Clarification("Use a positive quantity with at most ten decimal places.") from exc
    price = money(e.price or "", asset.currency)
    holding = await db.scalar(
        select(Holding)
        .where(Holding.user_id == user_id, Holding.account_id == account.id, Holding.asset_id == asset.id)
        .with_for_update()
    )
    if not holding:
        holding = Holding(
            user_id=user_id,
            account_id=account.id,
            asset_id=asset.id,
            quantity=Decimal(0),
            average_cost=Decimal(0),
        )
        db.add(holding)
    if intent == "portfolio.holding":
        holding.quantity, holding.average_cost = quantity, price
        return f"Saved the holding snapshot for {symbol}."
    if e.side not in {"buy", "sell"}:
        raise Clarification("Was this a buy or a sell?")
    fees = (
        money(e.fees, asset.currency) if e.fees and e.fees.strip() not in {"0", "0.0", "0.00"} else Decimal(0)
    )
    if e.side == "sell":
        if holding.quantity < quantity:
            raise Clarification("That sale exceeds the recorded holding.")
        holding.quantity -= quantity
    else:
        holding.average_cost = (holding.quantity * holding.average_cost + quantity * price + fees) / (
            holding.quantity + quantity
        )
        holding.quantity += quantity
    db.add(
        InvestmentTransaction(
            user_id=user_id,
            account_id=account.id,
            asset_id=asset.id,
            side=e.side,
            quantity=quantity,
            price=price,
            fees=fees,
            date=utcnow(),
            source_message_id=source,
        )
    )
    return f"Recorded your {symbol} {e.side}. No trade was placed."
