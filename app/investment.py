"""Deterministic research calculations; never place orders or fabricate missing metrics."""

from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field

from app.market import CryptoProvider, normalized_symbol
from app.portfolio import portfolio_snapshot


class InvestmentResearchResult(BaseModel):
    symbol: str
    asset_type: str
    market_data: dict = Field(default_factory=dict)
    fundamentals: dict = Field(default_factory=dict)
    valuation: dict = Field(default_factory=dict)
    macro_context: dict = Field(default_factory=dict)
    portfolio_context: dict = Field(default_factory=dict)
    risks: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)


def cagr(first, last, years):
    if first is None or last is None or years <= 0:
        return None
    try:
        begin, finish = Decimal(str(first)), Decimal(str(last))
    except (InvalidOperation, ValueError):
        return None
    if not begin.is_finite() or not finish.is_finite() or begin <= 0 or finish < 0:
        return None
    return (finish / begin) ** (Decimal(1) / Decimal(years)) - 1


def valuation(fundamentals, historical=None):
    historical = historical or {}
    result = {}
    eps = fundamentals.get("eps")
    for key in ("pe", "pb", "ev_ebitda", "fcf_yield", "dividend_yield"):
        value = fundamentals.get(key)
        if key == "pe" and eps is not None and Decimal(str(eps)) <= 0:
            result[key] = {"current": None, "note": "P/E is not meaningful with non-positive earnings."}
            continue
        series = [Decimal(str(v)) for v in historical.get(key, []) if v is not None]
        series.sort()
        result[key] = {
            "current": value,
            "historical_median": str(series[len(series) // 2]) if series else None,
            "historical_range": [str(series[0]), str(series[-1])] if series else None,
        }
    return result


def trends(history):
    result = {}
    for field in ("revenue", "earnings", "free_cash_flow", "dividend"):
        values = history.get(field, [])
        if len(values) >= 2:
            rate = cagr(values[0], values[-1], len(values) - 1)
            result[field + "_cagr"] = str(rate) if rate is not None else None
    for field in ("operating_margin", "debt"):
        values = history.get(field, [])
        if len(values) >= 2 and values[0] is not None and values[-1] is not None:
            result[field + "_direction"] = (
                "up"
                if Decimal(str(values[-1])) > Decimal(str(values[0]))
                else "down"
                if Decimal(str(values[-1])) < Decimal(str(values[0]))
                else "flat"
            )
    return result


def statement_metrics(statement):
    reports = statement.get("annual_reports", {})
    income = reports.get("INCOME_STATEMENT", [])
    balance = reports.get("BALANCE_SHEET", [])
    cashflow = reports.get("CASH_FLOW", [])

    def latest(rows, key):
        return next((row.get(key) for row in rows if row.get(key) is not None), None)

    fcf = None
    if (
        cashflow
        and cashflow[0].get("operatingCashflow") is not None
        and cashflow[0].get("capitalExpenditures") is not None
    ):
        fcf = str(
            Decimal(cashflow[0]["operatingCashflow"]) - abs(Decimal(cashflow[0]["capitalExpenditures"]))
        )
    normalized = {
        "net_income": latest(income, "netIncome"),
        "revenue": latest(income, "totalRevenue"),
        "debt": latest(balance, "shortLongTermDebtTotal"),
        "cash": latest(balance, "cashAndShortTermInvestments"),
        "free_cash_flow": fcf,
    }
    history = {
        "revenue": [row.get("totalRevenue") for row in reversed(income)],
        "earnings": [row.get("netIncome") for row in reversed(income)],
        "debt": [row.get("shortLongTermDebtTotal") for row in reversed(balance)],
        "free_cash_flow": [
            str(Decimal(row["operatingCashflow"]) - abs(Decimal(row["capitalExpenditures"])))
            if row.get("operatingCashflow") is not None and row.get("capitalExpenditures") is not None
            else None
            for row in reversed(cashflow)
        ],
        "dividend": [row.get("dividendPayout") for row in reversed(cashflow)],
    }
    return normalized, trends(history)


def purchase_scenario(portfolio, symbol, currency, amount):
    amount = Decimal(str(amount))
    rows = [h for h in portfolio["holdings"] if h["currency"] == currency]
    total = sum((Decimal(h["value"]) for h in rows if h["value"] is not None), Decimal(0))
    position = sum(
        (Decimal(h["value"]) for h in rows if h["symbol"] == symbol and h["value"] is not None), Decimal(0)
    )
    missing = [h["symbol"] for h in rows if h["value"] is None]
    cash = portfolio["available_cash_snapshots"].get(currency)
    return {
        "currency": currency,
        "amount": str(amount),
        "position_before": str(position) if not missing else None,
        "position_after": str(position + amount) if not missing else None,
        "concentration_before_percent": str(position / total * 100) if total and not missing else None,
        "concentration_after_percent": str((position + amount) / (total + amount) * 100)
        if total + amount and not missing
        else None,
        "cash_remaining": str(Decimal(str(cash)) - amount) if cash is not None else None,
        "cash_snapshot_complete": cash is not None and not portfolio["unknown_cash_accounts"],
        "missing_prices": missing,
        "note": "Scenario only; no trade was placed. Portfolio concentration uses same-currency recorded holdings. Cash snapshots may be incomplete.",
    }


async def research(
    db,
    user_id,
    market,
    symbol,
    asset_type="stock",
    purchase_amount=None,
    purchase_currency=None,
    include_history=False,
):
    symbol = normalized_symbol(symbol)
    if asset_type == "stock" and symbol in CryptoProvider.ids:
        asset_type = "crypto"
    result = InvestmentResearchResult(symbol=symbol, asset_type=asset_type)
    kind = "crypto" if asset_type == "crypto" else "equity"
    try:
        result.market_data = await market.get(db, user_id, kind, symbol)
        result.sources.append({k: result.market_data.get(k) for k in ("source", "as_of", "freshness")})
    except Exception:
        result.missing_data.append("verified quote")
    if asset_type == "stock":
        try:
            result.fundamentals = await market.get(db, user_id, "fundamentals", symbol)
            result.sources.append({k: result.fundamentals.get(k) for k in ("source", "as_of", "freshness")})
        except Exception:
            result.missing_data.append("verified fundamentals")
        required = (
            "revenue",
            "revenue_growth_yoy",
            "net_income",
            "earnings_growth_yoy",
            "eps",
            "operating_margin",
            "profit_margin",
            "free_cash_flow",
            "debt",
            "cash",
            "return_on_equity",
            "return_on_assets",
            "roic",
            "pe",
            "pb",
            "ev_ebitda",
            "dividend_yield",
            "shares_outstanding",
            "market_cap",
        )
        if include_history:
            try:
                statements = await market.get(db, user_id, "statements", symbol)
                latest, direction = statement_metrics(statements)
                result.fundamentals.update({key: value for key, value in latest.items() if value is not None})
                result.fundamentals["trends"] = direction
                result.sources.append({k: statements.get(k) for k in ("source", "as_of", "freshness")})
            except Exception:
                result.missing_data.append("annual financial statements")
        fcf, cap = result.fundamentals.get("free_cash_flow"), result.fundamentals.get("market_cap")
        if fcf is not None and cap is not None and Decimal(str(cap)) > 0:
            result.fundamentals["fcf_yield"] = str(Decimal(str(fcf)) / Decimal(str(cap)))
        result.valuation = valuation(result.fundamentals)
        for field in required:
            if result.fundamentals.get(field) is None:
                result.missing_data.append(field)
            result.fundamentals.setdefault(field, None)
        if not include_history:
            result.missing_data.append("historical financial statements not retrieved in fast mode")
        result.missing_data.append("historical valuation multiples")
    if asset_type == "crypto":
        result.risks.extend(["High volatility", "No conventional earnings or P/E valuation"])
        if result.market_data.get("market_cap") is None:
            result.missing_data.append("market capitalization from the selected quote source")
        if include_history:
            try:
                history = await market.get(db, user_id, "crypto_history", symbol)
                prices = history.get("history", [])
                if len(prices) >= 2 and Decimal(prices[0]["price"]) > 0:
                    result.market_data["recorded_30d_change_percent"] = str(
                        (Decimal(prices[-1]["price"]) / Decimal(prices[0]["price"]) - 1) * 100
                    )
                    result.market_data["history_as_of"] = history.get("as_of")
                result.sources.append({k: history.get(k) for k in ("source", "as_of", "freshness")})
            except Exception:
                result.missing_data.append("recent crypto price history")
    if market.settings.fred_api_key.get_secret_value():
        try:
            result.macro_context["fed_funds"] = await market.get(db, user_id, "macro", "FED_FUNDS")
            result.sources.append(
                {k: result.macro_context["fed_funds"].get(k) for k in ("source", "as_of", "freshness")}
            )
        except Exception:
            result.missing_data.append("current Fed funds observation")
    else:
        result.missing_data.append("live macro context (FRED key not configured)")
    portfolio = await portfolio_snapshot(db, user_id)
    result.portfolio_context = portfolio
    if purchase_amount is not None:
        currency = (
            purchase_currency
            or result.market_data.get("currency")
            or ("IDR" if symbol.endswith(".JK") else "USD")
        )
        result.portfolio_context["purchase_scenario"] = purchase_scenario(
            portfolio, symbol, currency, purchase_amount
        )
        if result.market_data.get("currency") and currency != result.market_data["currency"]:
            result.missing_data.append(
                f"FX conversion from quoted {result.market_data['currency']} to {currency}; no conversion was assumed"
            )
    if portfolio["missing_prices"]:
        result.missing_data.append("prices for some recorded holdings")
    return result
