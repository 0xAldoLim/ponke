"""Optional market feeds with explicit provenance and a durable stale fallback."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol

import httpx
from pydantic import BaseModel
from sqlalchemy import or_, select

from app.database import Activity, Asset, MarketCache, utcnow
from app.validation import Clarification, aware


def number(value):
    if value in (None, "", "None", "N/A", "-"):
        return None
    try:
        return str(Decimal(str(value).replace(",", "")))
    except InvalidOperation:
        return None


def normalized_symbol(symbol):
    value = symbol.strip().upper()
    if not value or len(value) > 30 or not all(c.isalnum() or c in ".-_" for c in value):
        raise Clarification("Give me a valid ticker or currency pair.")
    return value


class ResolvedSymbol(BaseModel):
    raw_symbol: str
    canonical_symbol: str
    provider_symbol: str
    exchange: str | None = None
    asset_type: str | None = None
    resolution_source: str


def indonesian_market_context(text):
    words = (text or "").casefold()
    return any(
        marker in words
        for marker in (
            "idx",
            "ihsg",
            "indonesian stock",
            "indonesia stock",
            "indonesian exchange",
            "indonesia exchange",
            "indonesian equities",
            "jakarta stock",
            "bursa efek indonesia",
            "saham indonesia",
            "saham idx",
        )
    )


def canonical_macro_series(raw_key, context=None):
    value = raw_key.strip().upper()
    words = (context or "").casefold()
    if "bi rate" in words or ("bank indonesia" in words and "rate" in words) or value == "BI_RATE":
        return "ID_BI_RATE"
    if ("indonesia" in words or "indonesian" in words) and ("cpi" in words or "inflation" in words):
        return "ID_CPI"
    return value


async def resolve_equity_symbol(db, user_id, raw_symbol, context=None):
    raw = raw_symbol.strip().upper()
    prefix, marker, code = raw.partition(":")
    if marker:
        if prefix not in {"IDX", "NASDAQ", "NYSE", "US"}:
            raise Clarification("Specify a supported exchange such as IDX:BYAN or NASDAQ:AAPL.")
        symbol = normalized_symbol(code)
        exchange = "IDX" if prefix == "IDX" else prefix
        if (exchange == "IDX" and "." in symbol and not symbol.endswith(".JK")) or (
            exchange != "IDX" and symbol.endswith(".JK")
        ):
            raise Clarification("The ticker suffix conflicts with the stated exchange.")
        provider_symbol = symbol + ".JK" if exchange == "IDX" and not symbol.endswith(".JK") else symbol
        return ResolvedSymbol(
            raw_symbol=raw,
            canonical_symbol=symbol,
            provider_symbol=provider_symbol,
            exchange=exchange,
            asset_type="stock",
            resolution_source="explicit_exchange",
        )
    symbol = normalized_symbol(raw)
    exact = await db.scalar(select(Asset).where(Asset.user_id == user_id, Asset.symbol == symbol))
    by_provider = await db.scalar(
        select(Asset).where(Asset.user_id == user_id, Asset.provider_symbol == symbol)
    )
    if exact and by_provider and exact.id != by_provider.id:
        raise Clarification("You have more than one listing for that ticker. Specify the exchange.")
    asset = exact or by_provider
    if "." not in symbol:
        idx_asset = await db.scalar(
            select(Asset).where(
                Asset.user_id == user_id,
                or_(Asset.symbol == symbol + ".JK", Asset.provider_symbol == symbol + ".JK"),
            )
        )
        if asset and idx_asset and asset.id != idx_asset.id:
            raise Clarification("You have more than one listing for that ticker. Specify the exchange.")
        asset = asset or idx_asset
    if not asset and symbol.endswith(".JK"):
        asset = await db.scalar(
            select(Asset).where(
                Asset.user_id == user_id,
                Asset.symbol == symbol.removesuffix(".JK"),
                Asset.asset_type == "stock",
                or_(Asset.exchange == "IDX", Asset.currency == "IDR"),
            )
        )
    if asset:
        exchange = asset.exchange or ("IDX" if asset.symbol.endswith(".JK") else None)
        provider_symbol = asset.provider_symbol or asset.symbol
        if exchange == "IDX" and not provider_symbol.endswith(".JK"):
            provider_symbol = asset.symbol.removesuffix(".JK") + ".JK"
        elif (
            not exchange
            and asset.asset_type == "stock"
            and asset.currency == "IDR"
            and "." not in provider_symbol
        ):
            exchange, provider_symbol = "IDX", asset.symbol + ".JK"
        return ResolvedSymbol(
            raw_symbol=raw,
            canonical_symbol=asset.symbol,
            provider_symbol=provider_symbol,
            exchange=exchange,
            asset_type=asset.asset_type,
            resolution_source="user_asset",
        )
    if symbol.endswith(".JK"):
        return ResolvedSymbol(
            raw_symbol=raw,
            canonical_symbol=symbol,
            provider_symbol=symbol,
            exchange="IDX",
            asset_type="stock",
            resolution_source="explicit_suffix",
        )
    if "." in symbol:
        return ResolvedSymbol(
            raw_symbol=raw,
            canonical_symbol=symbol,
            provider_symbol=symbol,
            asset_type="stock",
            resolution_source="explicit_suffix",
        )
    if indonesian_market_context(context):
        return ResolvedSymbol(
            raw_symbol=raw,
            canonical_symbol=symbol,
            provider_symbol=symbol + ".JK",
            exchange="IDX",
            asset_type="stock",
            resolution_source="market_context",
        )
    raise Clarification(
        "Which exchange is this stock on? Use IDX:BYAN or NASDAQ:AAPL, or give the .JK ticker."
    )


class MarketProvider(Protocol):
    name: str

    async def fetch(self, kind: str, key: str) -> dict: ...


class EquityMarketProvider(Protocol):
    name: str
    supported_exchanges: set[str]

    async def fetch(self, kind: str, key: str) -> dict: ...


class NormalizedFundamentals(BaseModel):
    revenue_ttm: Decimal | None = None
    revenue_growth_yoy: Decimal | None = None
    net_income_ttm: Decimal | None = None
    earnings_growth_yoy: Decimal | None = None
    eps_ttm: Decimal | None = None
    gross_profit_ttm: Decimal | None = None
    ebitda_ttm: Decimal | None = None
    operating_margin: Decimal | None = None
    profit_margin: Decimal | None = None
    free_cash_flow_ttm: Decimal | None = None
    debt: Decimal | None = None
    cash: Decimal | None = None
    return_on_equity: Decimal | None = None
    return_on_assets: Decimal | None = None
    roic: Decimal | None = None
    pe: Decimal | None = None
    pb: Decimal | None = None
    ev_ebitda: Decimal | None = None
    dividend_yield: Decimal | None = None
    shares_outstanding: Decimal | None = None
    market_cap: Decimal | None = None


class AlphaVantageAdapter:
    overview_fields = {
        "revenue_ttm": "RevenueTTM",
        "revenue_growth_yoy": "QuarterlyRevenueGrowthYOY",
        "net_income_ttm": "NetIncomeTTM",
        "earnings_growth_yoy": "QuarterlyEarningsGrowthYOY",
        "eps_ttm": "EPS",
        "gross_profit_ttm": "GrossProfitTTM",
        "ebitda_ttm": "EBITDA",
        "operating_margin": "OperatingMarginTTM",
        "profit_margin": "ProfitMargin",
        "free_cash_flow_ttm": "FreeCashFlowTTM",
        "debt": "TotalDebt",
        "cash": "CashAndCashEquivalents",
        "return_on_equity": "ReturnOnEquityTTM",
        "return_on_assets": "ReturnOnAssetsTTM",
        "roic": "ReturnOnInvestedCapitalTTM",
        "pe": "PERatio",
        "pb": "PriceToBookRatio",
        "ev_ebitda": "EVToEBITDA",
        "dividend_yield": "DividendYield",
        "shares_outstanding": "SharesOutstanding",
        "market_cap": "MarketCapitalization",
    }

    @classmethod
    def fundamentals(cls, data):
        normalized = NormalizedFundamentals(
            **{
                field: number(data.get(provider_field))
                for field, provider_field in cls.overview_fields.items()
            }
        )
        return normalized.model_dump(mode="json")


def normalize_fundamentals_payload(data):
    """Adapt legacy cached names as well as new provider-neutral fields."""
    aliases = {
        "revenue": "revenue_ttm",
        "net_income": "net_income_ttm",
        "eps": "eps_ttm",
        "ebitda": "ebitda_ttm",
        "free_cash_flow": "free_cash_flow_ttm",
    }
    prepared = dict(data)
    for old, new in aliases.items():
        if prepared.get(new) is None and prepared.get(old) is not None:
            prepared[new] = prepared[old]
    normalized = NormalizedFundamentals(
        **{field: prepared.get(field) for field in NormalizedFundamentals.model_fields}
    ).model_dump(mode="json")
    return {**prepared, **normalized}


class CryptoProvider:
    name = "crypto"
    ids = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "SOL": "solana",
        "BNB": "binancecoin",
        "ADA": "cardano",
        "XRP": "ripple",
        "DOGE": "dogecoin",
    }

    def __init__(self, client, key):
        self.client, self.key = client, key

    async def fetch(self, kind, key):
        coin = self.ids.get(key.upper())
        if not coin:
            raise Clarification("That crypto symbol is not mapped to a verified CoinGecko ID.")
        if kind == "crypto_history":
            if self.key:
                response = await self.client.get(
                    f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart",
                    params={"vs_currency": "usd", "days": 30},
                    headers={"x-cg-demo-api-key": self.key},
                )
                response.raise_for_status()
                prices = response.json().get("prices", [])
                currency, source = "USD", "CoinGecko"
                history = [{"timestamp_ms": int(row[0]), "price": number(row[1])} for row in prices]
            else:
                response = await self.client.get(
                    "https://data-api.binance.vision/api/v3/klines",
                    params={"symbol": key.upper() + "USDT", "interval": "1d", "limit": 31},
                )
                response.raise_for_status()
                currency, source = "USDT", "Binance Spot"
                history = [{"timestamp_ms": int(row[0]), "price": number(row[4])} for row in response.json()]
            if not history:
                raise ValueError("No crypto price history")
            from datetime import UTC, datetime

            return {
                "symbol": key,
                "currency": currency,
                "history": history,
                "as_of": datetime.fromtimestamp(history[-1]["timestamp_ms"] / 1000, UTC).isoformat(),
                "source": source,
            }
        if not self.key:
            response = await self.client.get(
                "https://data-api.binance.vision/api/v3/ticker/24hr", params={"symbol": key.upper() + "USDT"}
            )
            response.raise_for_status()
            row = response.json()
            if not number(row.get("lastPrice")):
                raise ValueError("No public spot quote for symbol")
            from datetime import UTC, datetime

            as_of = (
                datetime.fromtimestamp(int(row["closeTime"]) / 1000, UTC).isoformat()
                if row.get("closeTime")
                else None
            )
            return {
                "symbol": key,
                "currency": "USDT",
                "price": number(row.get("lastPrice")),
                "change_24h_percent": number(row.get("priceChangePercent")),
                "volume_24h": number(row.get("quoteVolume")),
                "market_cap": None,
                "as_of": as_of,
                "source": "Binance Spot",
                "note": "USDT trading pair, not a USD reference price; market cap unavailable.",
            }
        params = {"vs_currency": "usd", "ids": coin, "price_change_percentage": "24h"}
        response = await self.client.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params=params,
            headers={"x-cg-demo-api-key": self.key},
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or not rows:
            raise ValueError("No crypto quote")
        row = rows[0]
        return {
            "symbol": key,
            "name": row.get("name"),
            "currency": "USD",
            "price": number(row.get("current_price")),
            "change_24h_percent": number(row.get("price_change_percentage_24h")),
            "market_cap": number(row.get("market_cap")),
            "volume_24h": number(row.get("total_volume")),
            "as_of": row.get("last_updated"),
            "source": "CoinGecko",
        }


class EquityProvider:
    name = "Alpha Vantage"
    supported_exchanges = {"IDX", "NASDAQ", "NYSE", "US"}

    def __init__(self, client, key):
        self.client, self.key = client, key

    async def fetch(self, kind, key):
        if not self.key:
            raise Clarification(
                "Live equity data needs ALPHA_VANTAGE_API_KEY; manual prices remain available."
            )
        if kind == "statements":
            reports = {}
            for function, fields in (
                ("INCOME_STATEMENT", ("totalRevenue", "netIncome", "operatingIncome", "grossProfit")),
                (
                    "BALANCE_SHEET",
                    (
                        "totalCurrentAssets",
                        "cashAndShortTermInvestments",
                        "shortLongTermDebtTotal",
                        "totalShareholderEquity",
                    ),
                ),
                ("CASH_FLOW", ("operatingCashflow", "capitalExpenditures", "dividendPayout")),
            ):
                response = await self.client.get(
                    "https://www.alphavantage.co/query",
                    params={"function": function, "symbol": key, "apikey": self.key},
                )
                response.raise_for_status()
                data = response.json()
                if "Information" in data or "Note" in data:
                    raise ValueError("Equity provider rate limit")
                reports[function] = [
                    {
                        "date": row.get("fiscalDateEnding"),
                        **{field: number(row.get(field)) for field in fields},
                    }
                    for row in data.get("annualReports", [])[:4]
                ]
            if not any(reports.values()):
                raise ValueError("No annual statements for ticker")
            as_of = max(
                (row["date"] for values in reports.values() for row in values if row["date"]), default=None
            )
            return {"symbol": key, "annual_reports": reports, "as_of": as_of, "source": self.name}
        function = (
            "OVERVIEW"
            if kind == "fundamentals"
            else "TIME_SERIES_DAILY"
            if kind == "history"
            else "GLOBAL_QUOTE"
        )
        response = await self.client.get(
            "https://www.alphavantage.co/query",
            params={"function": function, "symbol": key, "apikey": self.key},
        )
        response.raise_for_status()
        data = response.json()
        if "Information" in data or "Note" in data:
            raise ValueError("Equity provider rate limit")
        if kind == "fundamentals":
            if not data.get("Symbol"):
                raise ValueError("No verified fundamentals for ticker")
            return {
                "symbol": key,
                "name": data.get("Name"),
                "sector": data.get("Sector"),
                "currency": data.get("Currency"),
                **AlphaVantageAdapter.fundamentals(data),
                "as_of": data.get("LatestQuarter"),
                "source": self.name,
            }
        if kind == "history":
            daily = data.get("Time Series (Daily)", {})
            if not daily:
                raise ValueError("No daily history for ticker")
            return {
                "symbol": key,
                "currency": "IDR" if key.endswith(".JK") else "USD",
                "history": [
                    {"date": d, "close": number(v.get("4. close")), "volume": number(v.get("5. volume"))}
                    for d, v in sorted(daily.items(), reverse=True)[:100]
                ],
                "as_of": max(daily),
                "source": self.name,
            }
        quote = data.get("Global Quote", {})
        if not quote or not number(quote.get("05. price")):
            raise ValueError("No equity quote for ticker")
        return {
            "symbol": key,
            "currency": "IDR" if key.endswith(".JK") else "USD",
            "price": number(quote.get("05. price")),
            "change_percent": number(str(quote.get("10. change percent", "")).rstrip("%")),
            "volume": number(quote.get("06. volume")),
            "as_of": quote.get("07. latest trading day"),
            "source": self.name,
        }


class FXProvider:
    name = "Frankfurter"

    def __init__(self, client):
        self.client = client

    async def fetch(self, kind, key):
        base, quote = key.split("/")
        response = await self.client.get(f"https://api.frankfurter.dev/v2/rate/{base}/{quote}")
        response.raise_for_status()
        data = response.json()
        if not number(data.get("rate")):
            raise ValueError("No FX rate")
        return {
            "symbol": key,
            "base": base,
            "quote": quote,
            "rate": number(data["rate"]),
            "as_of": data.get("date"),
            "source": self.name,
            "note": "Daily reference rate, not an intraday executable rate.",
        }


class MacroProvider:
    name = "FRED"
    series = {
        "US_FED_FUNDS": "FEDFUNDS",
        "FED_FUNDS": "FEDFUNDS",
        "US_CPI": "CPIAUCSL",
        "US_10Y": "DGS10",
        "DXY_PROXY": "DTWEXBGS",
        "US_INFLATION": "CPIAUCSL",
    }

    def __init__(self, client, key):
        self.client, self.key = client, key

    async def fetch(self, kind, key):
        if not self.key:
            raise Clarification("Macro observations need FRED_API_KEY.")
        series = self.series.get(key)
        if not series:
            raise Clarification("That macro series is not configured.")
        response = await self.client.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": series,
                "api_key": self.key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 8,
            },
        )
        response.raise_for_status()
        observations = response.json().get("observations", [])
        valid = [o for o in observations if number(o.get("value")) is not None]
        if not valid:
            raise ValueError("No macro observation")
        return {
            "series": key,
            "value": number(valid[0]["value"]),
            "as_of": valid[0]["date"],
            "source": self.name,
            "units": "index" if key in {"US_CPI", "DXY_PROXY", "US_INFLATION"} else "percent",
            "note": "Observation date; publication may lag.",
        }


class MarketService:
    TTL = {
        "crypto": 120,
        "crypto_history": 21600,
        "equity": 900,
        "fx": 3600,
        "macro": 86400,
        "fundamentals": 86400,
        "statements": 86400,
        "history": 21600,
    }

    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client or httpx.AsyncClient(timeout=settings.market_timeout_seconds)
        self.crypto = CryptoProvider(self.client, settings.coingecko_demo_api_key.get_secret_value())
        self.equity = EquityProvider(self.client, settings.alpha_vantage_api_key.get_secret_value())
        self.fx = FXProvider(self.client)
        self.macro = MacroProvider(self.client, settings.fred_api_key.get_secret_value())

    async def close(self):
        await self.client.aclose()

    @staticmethod
    def record_lookup(db, user_id, data):
        fields = (
            "source",
            "as_of",
            "fetched_at",
            "freshness",
            "stale",
            "canonical_symbol",
            "provider_symbol",
            "exchange",
            "symbol",
            "series",
        )
        db.add(Activity(user_id=user_id, kind="market.lookup", detail={key: data.get(key) for key in fields}))
        return data

    async def get(self, db, user_id, kind, raw_key, context=None):
        if kind == "macro":
            raw_key = canonical_macro_series(raw_key, context)
        if kind == "macro" and raw_key.upper() in {"ID_BI_RATE", "ID_CPI"}:
            raise Clarification(
                f"{raw_key.upper()} is unavailable: no verified Indonesian macro provider is configured."
            )
        if kind == "macro" and raw_key.upper() == "USD_IDR":
            return {**await self.get(db, user_id, "fx", "USD/IDR"), "series": "USD_IDR"}
        identity = (
            await resolve_equity_symbol(db, user_id, raw_key, context)
            if kind in {"equity", "fundamentals", "history", "statements"}
            else None
        )
        key = (
            identity.provider_symbol
            if identity
            else normalized_symbol(raw_key)
            if kind != "fx"
            else raw_key.upper().replace("-", "/")
        )
        if kind == "fx" and (
            len(key.split("/")) != 2 or not all(len(p) == 3 and p.isalpha() for p in key.split("/"))
        ):
            raise Clarification("Use a currency pair such as USD/IDR.")
        provider = (
            self.crypto
            if kind in {"crypto", "crypto_history"}
            else self.fx
            if kind == "fx"
            else self.macro
            if kind == "macro"
            else self.equity
        )
        cached = await db.scalar(
            select(MarketCache).where(
                MarketCache.provider == provider.name, MarketCache.cache_key == f"{kind}:{key}"
            )
        )
        if cached and aware(cached.expires_at) > utcnow():
            return self.record_lookup(
                db,
                user_id,
                {
                    **(
                        normalize_fundamentals_payload(cached.payload)
                        if kind == "fundamentals"
                        else cached.payload
                    ),
                    **(identity.model_dump() if identity else {}),
                    "freshness": "CACHED",
                    "fetched_at": aware(cached.fetched_at).isoformat(),
                    "stale": False,
                },
            )
        try:
            data = await provider.fetch(kind, key)
            if kind == "fundamentals":
                data = normalize_fundamentals_payload(data)
            if identity:
                data = {**data, **identity.model_dump()}
            fetched_at = utcnow()
            if cached:
                cached.payload, cached.fetched_at, cached.expires_at = (
                    data,
                    fetched_at,
                    fetched_at + timedelta(seconds=self.TTL[kind]),
                )
            else:
                db.add(
                    MarketCache(
                        provider=provider.name,
                        cache_key=f"{kind}:{key}",
                        payload=data,
                        fetched_at=fetched_at,
                        expires_at=fetched_at + timedelta(seconds=self.TTL[kind]),
                    )
                )
            return self.record_lookup(
                db,
                user_id,
                {**data, "freshness": "LIVE", "fetched_at": fetched_at.isoformat(), "stale": False},
            )
        except (httpx.HTTPError, ValueError, Clarification) as exc:
            if cached:
                return self.record_lookup(
                    db,
                    user_id,
                    {
                        **(
                            normalize_fundamentals_payload(cached.payload)
                            if kind == "fundamentals"
                            else cached.payload
                        ),
                        **(identity.model_dump() if identity else {}),
                        "freshness": "CACHED",
                        "fetched_at": aware(cached.fetched_at).isoformat(),
                        "stale": True,
                        "warning": "Feed unavailable; this cached result may be stale.",
                    },
                )
            if kind in {"crypto", "equity"}:
                asset = await db.scalar(
                    select(Asset).where(
                        Asset.user_id == user_id,
                        Asset.symbol == (identity.canonical_symbol if identity else key),
                    )
                )
                if asset and identity and identity.resolution_source != "user_asset":
                    asset_exchange = asset.exchange or (
                        "IDX" if asset.asset_type == "stock" and asset.currency == "IDR" else None
                    )
                    if (
                        asset.provider_symbol or asset.symbol
                    ) != identity.provider_symbol and asset_exchange != identity.exchange:
                        asset = None
                if asset and asset.manual_price is not None:
                    return self.record_lookup(
                        db,
                        user_id,
                        {
                            "symbol": identity.canonical_symbol if identity else key,
                            **(identity.model_dump() if identity else {}),
                            "price": str(asset.manual_price),
                            "currency": asset.currency,
                            "source": "USER",
                            "freshness": "MANUAL",
                            "as_of": aware(asset.price_as_of).isoformat() if asset.price_as_of else None,
                            "stale": True,
                            "warning": "Manual price; no verified live quote.",
                        },
                    )
            raise Clarification(
                str(exc)
                if isinstance(exc, Clarification)
                else "Market feed unavailable and no cached or manual value exists."
            ) from exc


def render_market(data):
    value = data.get("price") or data.get("rate") or data.get("value")
    unit = data.get("currency") or data.get("units") or ""
    lines = [
        f"{data.get('canonical_symbol') or data.get('symbol') or data.get('series')}: {value} {unit}".strip(),
        f"Source: {data.get('source')} ({data.get('freshness')}) · as of {data.get('as_of') or 'unknown'}",
    ]
    if data.get("provider_symbol"):
        lines.append(
            f"Exchange: {data.get('exchange') or 'unverified'} · provider symbol: {data['provider_symbol']}"
        )
    if data.get("fetched_at"):
        lines.append(f"Fetched: {data['fetched_at']} · stale: {'yes' if data.get('stale') else 'no'}")
    if data.get("change_24h_percent") is not None:
        lines.insert(1, f"24h: {data['change_24h_percent']}%")
    if data.get("warning"):
        lines.append(data["warning"])
    return "\n".join(lines)
