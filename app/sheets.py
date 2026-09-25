"""Google Sheets is an optional read model, updated by a retryable PostgreSQL outbox."""

from datetime import timedelta
from urllib.parse import quote

import structlog
from sqlalchemy import select

from app.database import Account, Asset, Decision, Holding, SpreadsheetSyncOutbox, Transaction, utcnow
from app.finance import month_range, summary
from app.portfolio import portfolio_snapshot

log = structlog.get_logger()
TABS = ("Transactions", "Accounts", "Monthly Summary", "Investments", "Net Worth", "Decision History")


async def enqueue_sync(db, user_id, entity_type, entity_id, operation="upsert"):
    existing = await db.scalar(
        select(SpreadsheetSyncOutbox).where(
            SpreadsheetSyncOutbox.user_id == user_id,
            SpreadsheetSyncOutbox.entity_type == entity_type,
            SpreadsheetSyncOutbox.entity_id == entity_id,
            SpreadsheetSyncOutbox.operation == operation,
        )
    )
    if existing:
        existing.status, existing.next_attempt_at = "pending", utcnow()
    else:
        db.add(
            SpreadsheetSyncOutbox(
                user_id=user_id, entity_type=entity_type, entity_id=entity_id, operation=operation
            )
        )


async def enqueue_derived(db, user_id):
    await enqueue_sync(db, user_id, "monthly", "current")
    await enqueue_sync(db, user_id, "net_worth", "current")


class SheetsWorker:
    def __init__(self, sessions, settings, calendar):
        self.sessions, self.settings, self.calendar = sessions, settings, calendar

    async def request(self, user_id, method, path, **kwargs):
        token = await self.calendar.access_token(user_id)
        url = (
            "https://sheets.googleapis.com/v4/spreadsheets/"
            + quote(self.settings.google_finance_sheet_id, safe="")
            + path
        )
        response = await self.calendar.http.request(
            method, url, headers={"Authorization": "Bearer " + token}, **kwargs
        )
        response.raise_for_status()
        return response.json()

    async def ensure_tabs(self, user_id):
        meta = await self.request(user_id, "GET", "")
        existing = {row["properties"]["title"] for row in meta.get("sheets", [])}
        missing = [name for name in TABS if name not in existing]
        if missing:
            await self.request(
                user_id,
                "POST",
                ":batchUpdate",
                json={"requests": [{"addSheet": {"properties": {"title": name}}} for name in missing]},
            )

    async def upsert(self, user_id, tab, key, cells):
        path = "/values/" + quote("'" + tab.replace("'", "''") + "'!A:A", safe="")
        data = await self.request(user_id, "GET", path)
        keys = [row[0] if row else "" for row in data.get("values", [])]
        full_row = [str(user_id) + ":" + key] + ["" if value is None else str(value) for value in cells]
        if full_row[0] in keys:
            index = keys.index(full_row[0]) + 1
            range_path = "/values/" + quote("'" + tab.replace("'", "''") + f"'!A{index}", safe="")
            await self.request(
                user_id, "PUT", range_path, params={"valueInputOption": "RAW"}, json={"values": [full_row]}
            )
        else:
            append = "/values/" + quote("'" + tab.replace("'", "''") + "'!A:A", safe="") + ":append"
            await self.request(
                user_id,
                "POST",
                append,
                params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
                json={"values": [full_row]},
            )

    async def render_event(self, db, event):
        user_id = event.user_id
        if event.entity_type == "transaction":
            item = await db.scalar(
                select(Transaction).where(Transaction.id == event.entity_id, Transaction.user_id == user_id)
            )
            if not item:
                return "Transactions", event.entity_id, ["deleted"]
            return (
                "Transactions",
                item.id,
                [
                    item.date.date().isoformat(),
                    item.transaction_type,
                    item.amount,
                    item.currency,
                    item.merchant,
                    item.category,
                    item.account_id,
                    item.source,
                ],
            )
        if event.entity_type == "account":
            item = await db.scalar(
                select(Account).where(Account.id == event.entity_id, Account.user_id == user_id)
            )
            return (
                "Accounts",
                event.entity_id,
                [item.name, item.type, item.currency, item.current_balance, item.balance_as_of]
                if item
                else ["deleted"],
            )
        if event.entity_type == "investment":
            item = await db.scalar(
                select(Holding).where(Holding.id == event.entity_id, Holding.user_id == user_id)
            )
            asset = (
                await db.scalar(select(Asset).where(Asset.id == item.asset_id, Asset.user_id == user_id))
                if item
                else None
            )
            return (
                "Investments",
                event.entity_id,
                [asset.symbol, item.quantity, item.average_cost, asset.currency, item.account_id]
                if item and asset
                else ["deleted"],
            )
        if event.entity_type == "decision":
            item = await db.scalar(
                select(Decision).where(Decision.id == event.entity_id, Decision.user_id == user_id)
            )
            return (
                "Decision History",
                event.entity_id,
                [
                    item.created_at,
                    item.decision_type,
                    item.user_question,
                    item.final_recommendation.get("recommended_action"),
                    item.status,
                ]
                if item
                else ["deleted"],
            )
        if event.entity_type == "monthly":
            start, end = month_range(utcnow(), self.settings.user_timezone)
            totals = await summary(db, user_id, start, end)
            return (
                "Monthly Summary",
                start.strftime("%Y-%m"),
                [start.strftime("%Y-%m"), str(totals["by_currency"]), totals["transaction_count"]],
            )
        if event.entity_type == "net_worth":
            data = await portfolio_snapshot(db, user_id)
            return (
                "Net Worth",
                "current",
                [
                    utcnow().isoformat(),
                    str(data["reported_net_worth"]),
                    str(data["available_cash_snapshots"]),
                    str(data["reported_liabilities"]),
                    "incomplete" if not data["net_worth_complete"] else "complete",
                ],
            )
        raise ValueError("Unsupported Sheets outbox entity")

    async def tick(self):
        if not self.settings.google_sheets_enabled or not self.settings.google_finance_sheet_id:
            return
        async with self.sessions() as db:
            pending = (
                await db.scalars(
                    select(SpreadsheetSyncOutbox)
                    .where(
                        SpreadsheetSyncOutbox.status == "pending",
                        SpreadsheetSyncOutbox.next_attempt_at <= utcnow(),
                        SpreadsheetSyncOutbox.user_id.in_(self.settings.allowed_ids),
                    )
                    .order_by(SpreadsheetSyncOutbox.created_at)
                    .limit(20)
                )
            ).all()
        for event in pending:
            try:
                async with self.sessions() as db:
                    tab, key, cells = await self.render_event(db, event)
                await self.ensure_tabs(event.user_id)
                await self.upsert(event.user_id, tab, key, cells)
            except Exception as exc:
                log.warning(
                    "sheets_sync_failed", error_type=type(exc).__name__, entity_type=event.entity_type
                )
                async with self.sessions.begin() as db:
                    row = await db.get(SpreadsheetSyncOutbox, event.id)
                    row.attempts += 1
                    row.last_error = type(exc).__name__
                    row.next_attempt_at = utcnow() + timedelta(
                        seconds=min(3600, 30 * 2 ** min(row.attempts, 7))
                    )
            else:
                async with self.sessions.begin() as db:
                    row = await db.get(SpreadsheetSyncOutbox, event.id)
                    row.status, row.last_error = "done", ""
