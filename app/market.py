"""Optional market feeds with explicit provenance and a durable stale fallback."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol

import httpx
from sqlalchemy import select

from app.database import Asset, MarketCache, utcnow
from app.validation import Clarification, aware


def number(value):
    if value in (None, "", "None", "N/A", "-"):
        return None
    try:
        return str(Decimal(str(value).replace(",", "")))
    except InvalidOperation:
        return None


def normalized_symbol(symbol):
    value = symbol.strip().upper().replace("IDX:", "").replace("NASDAQ:", "")
    if not value or len(value) > 30 or not all(c.isalnum() or c in ".-_" for c in value):
        raise Clarification("Give me a valid ticker or currency pair.")
    if value in {
        "BBCA",
        "BBRI",
        "BMRI",
        "BBNI",
        "TLKM",
        "ASII",
        "UNVR",
        "GOTO",
        "ICBP",
        "INDF",
        "ANTM",
        "ADRO",
        "PTBA",
        "MDKA",
        "AMRT",
    }:
        value += ".JK"
    return value


class MarketProvider(Protocol):
    name: str

    async def fetch(self, kind: str, key: str) -> dict: ...


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
                "market_cap": number(data.get("MarketCapitalization")),
                "pe": number(data.get("PERatio")),
                "pb": number(data.get("PriceToBookRatio")),
                "ev_ebitda": number(data.get("EVToEBITDA")),
                "eps": number(data.get("EPS")),
                "shares_outstanding": number(data.get("SharesOutstanding")),
                "revenue_ttm": number(data.get("RevenueTTM")),
                "revenue_growth_yoy": number(data.get("QuarterlyRevenueGrowthYOY")),
                "earnings_growth_yoy": number(data.get("QuarterlyEarningsGrowthYOY")),
                "gross_profit_ttm": number(data.get("GrossProfitTTM")),
                "ebitda": number(data.get("EBITDA")),
                "profit_margin": number(data.get("ProfitMargin")),
                "operating_margin": number(data.get("OperatingMarginTTM")),
                "return_on_equity": number(data.get("ReturnOnEquityTTM")),
                "return_on_assets": number(data.get("ReturnOnAssetsTTM")),
                "dividend_yield": number(data.get("DividendYield")),
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

    async def get(self, db, user_id, kind, raw_key):
        key = normalized_symbol(raw_key) if kind != "fx" else raw_key.upper().replace("-", "/")
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
            return {
                **cached.payload,
                "freshness": "CACHED",
                "fetched_at": aware(cached.fetched_at).isoformat(),
                "stale": False,
            }
        try:
            data = await provider.fetch(kind, key)
            if cached:
                cached.payload, cached.fetched_at, cached.expires_at = (
                    data,
                    utcnow(),
                    utcnow() + timedelta(seconds=self.TTL[kind]),
                )
            else:
                db.add(
                    MarketCache(
                        provider=provider.name,
                        cache_key=f"{kind}:{key}",
                        payload=data,
                        fetched_at=utcnow(),
                        expires_at=utcnow() + timedelta(seconds=self.TTL[kind]),
                    )
                )
            return {**data, "freshness": "LIVE", "fetched_at": utcnow().isoformat(), "stale": False}
        except (httpx.HTTPError, ValueError, Clarification) as exc:
            if cached:
                return {
                    **cached.payload,
                    "freshness": "CACHED",
                    "fetched_at": aware(cached.fetched_at).isoformat(),
                    "stale": True,
                    "warning": "Feed unavailable; this cached result may be stale.",
                }
            if kind in {"crypto", "equity"}:
                asset = await db.scalar(select(Asset).where(Asset.user_id == user_id, Asset.symbol == key))
                if asset and asset.manual_price is not None:
                    return {
                        "symbol": key,
                        "price": str(asset.manual_price),
                        "currency": asset.currency,
                        "source": "USER",
                        "freshness": "MANUAL",
                        "as_of": aware(asset.price_as_of).isoformat() if asset.price_as_of else None,
                        "stale": True,
                        "warning": "Manual price; no verified live quote.",
                    }
            raise Clarification(
                str(exc)
                if isinstance(exc, Clarification)
                else "Market feed unavailable and no cached or manual value exists."
            ) from exc


def render_market(data):
    value = data.get("price") or data.get("rate") or data.get("value")
    unit = data.get("currency") or data.get("units") or ""
    lines = [
        f"{data.get('symbol') or data.get('series')}: {value} {unit}".strip(),
        f"Source: {data.get('source')} ({data.get('freshness')}) · as of {data.get('as_of') or 'unknown'}",
    ]
    if data.get("change_24h_percent") is not None:
        lines.insert(1, f"24h: {data['change_24h_percent']}%")
    if data.get("warning"):
        lines.append(data["warning"])
    return "\n".join(lines)
