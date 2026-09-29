"""Conservative bank-statement import with preview and idempotent commit."""

import csv
import hashlib
import io
import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from openpyxl import load_workbook
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import select

from app.database import Account, StatementImport, Transaction, utcnow
from app.sheets import enqueue_sync
from app.validation import Clarification, aware

DATE_NAMES = {"date", "transaction date", "tanggal", "tgl", "posting date"}
DESCRIPTION_NAMES = {"description", "details", "merchant", "keterangan", "narrative", "transaction"}
AMOUNT_NAMES = {"amount", "jumlah", "nominal", "value"}
DEBIT_NAMES = {"debit", "withdrawal", "keluar"}
CREDIT_NAMES = {"credit", "deposit", "masuk"}
CURRENCY_NAMES = {"currency", "ccy", "mata uang"}


class StatementParser(Protocol):
    def parse(self, content: bytes) -> list[dict]: ...


def parse_amount(raw):
    if raw is None:
        return None
    value = str(raw).strip()
    value = re.sub(r"^(?:Rp\s*|IDR\s*|\$\s*)", "", value, flags=re.IGNORECASE).strip()
    if not value:
        return None
    negative = value.startswith("-") or (value.startswith("(") and value.endswith(")"))
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1].strip()
    elif value.startswith(("-", "+")):
        value = value[1:].strip()
    if not re.fullmatch(r"\d[\d.,]*", value):
        return None
    dots, commas = value.count("."), value.count(",")
    if dots and commas:
        decimal_sep = "." if value.rfind(".") > value.rfind(",") else ","
        grouping_sep = "," if decimal_sep == "." else "."
        whole, fraction = value.rsplit(decimal_sep, 1)
        groups = whole.split(grouping_sep)
        if not (
            1 <= len(fraction) <= 2
            and len(groups) >= 2
            and groups[0].isdigit()
            and 1 <= len(groups[0]) <= 3
            and all(len(g) == 3 and g.isdigit() for g in groups[1:])
        ):
            return None
        value = "".join(groups) + "." + fraction
    elif dots or commas:
        sep = "." if dots else ","
        groups = value.split(sep)
        if len(groups) > 2:
            if not (
                groups[0].isdigit()
                and 1 <= len(groups[0]) <= 3
                and all(len(g) == 3 and g.isdigit() for g in groups[1:])
            ):
                return None
            value = "".join(groups)
        elif len(groups[1]) == 3 and groups[0].isdigit() and 1 <= len(groups[0]) <= 3:
            value = "".join(groups)
        elif groups[0].isdigit() and groups[1].isdigit() and 1 <= len(groups[1]) <= 2:
            value = groups[0] + "." + groups[1]
        else:
            return None
    try:
        result = Decimal(value)
    except InvalidOperation:
        return None
    return -result if negative else result


def statement_utc_date(value, timezone):
    return datetime.combine(date.fromisoformat(value), time.min, tzinfo=ZoneInfo(timezone)).astimezone(UTC)


def parse_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value or "").strip()
    slash = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", text)
    if slash and int(slash[1]) <= 12 and int(slash[2]) <= 12:
        return None  # Day/month order is genuinely ambiguous without a bank-specific format.
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalize_row(row, index):
    if None in row:
        return {
            "index": index,
            "status": "review",
            "reason": "Extra columns: quote decimal commas or use a semicolon-delimited CSV.",
            "raw_amount": "",
            "currency": None,
            "date": None,
            "description": "",
        }
    values = {str(k).strip().casefold(): v for k, v in row.items() if k is not None}

    def first(names):
        return next((values[k] for k in names if k in values and values[k] not in (None, "")), None)

    raw_date = first(DATE_NAMES)
    date = parse_date(raw_date)
    description = str(first(DESCRIPTION_NAMES) or "").strip()[:200]
    raw_debit, raw_credit = first(DEBIT_NAMES), first(CREDIT_NAMES)
    debit, credit = parse_amount(raw_debit), parse_amount(raw_credit)
    raw_text = first(AMOUNT_NAMES)
    raw_amount = parse_amount(raw_text)
    amount = (
        -abs(debit)
        if debit is not None and debit != 0
        else abs(credit)
        if credit is not None and credit != 0
        else raw_amount
    )
    raw_currency = first(CURRENCY_NAMES)
    currency = str(raw_currency).strip().upper() if raw_currency is not None else None
    if currency is None and any(
        re.match(r"^(?:Rp|IDR)\s*", str(candidate).strip(), flags=re.IGNORECASE)
        for candidate in (raw_debit, raw_credit, raw_text)
        if candidate is not None
    ):
        currency = "IDR"
    normalized = {
        "index": index,
        "status": "review",
        "date": date,
        "raw_date": str(raw_date or ""),
        "description": description,
        "amount": str(abs(amount)) if amount is not None else None,
        "raw_amount": str(raw_text or ""),
        "currency": currency,
        "transaction_type": "expense"
        if amount is not None and amount < 0
        else "income"
        if amount is not None
        else None,
    }
    if (raw_debit is not None and debit is None) or (raw_credit is not None and credit is None):
        normalized["amount"] = None
        normalized["transaction_type"] = None
        normalized["reason"] = "Malformed debit or credit amount. Supply a corrected amount."
    elif debit is not None and credit is not None and debit != 0 and credit != 0:
        normalized["amount"] = None
        normalized["transaction_type"] = None
        normalized["reason"] = "Both debit and credit are populated."
    elif (
        debit is None
        and credit is None
        and raw_amount is not None
        and not str(raw_text).strip().startswith(("-", "+", "("))
    ):
        normalized["transaction_type"] = None
        normalized["reason"] = "Unsigned amount has no debit/credit direction."
    elif (
        not date
        or not description
        or amount is None
        or amount == 0
        or currency not in {"IDR", "USD", "EUR", "MYR", "SGD"}
    ):
        normalized["reason"] = "Missing or ambiguous date, description, amount, or currency."
    elif not amount.is_finite() or abs(amount) >= Decimal("1e18"):
        normalized["reason"] = "Invalid amount."
    else:
        normalized["status"] = "ready"
    return normalized


class CSVParser:
    def parse(self, content):
        text = content.decode("utf-8-sig", errors="replace")
        if "\ufffd" in text:
            text = content.decode("cp1252", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
            return list(csv.DictReader(io.StringIO(text), dialect=dialect))
        except csv.Error:
            header = text.splitlines()[0] if text else ""
            delimiter = max((",", ";", "\t"), key=header.count)
            if header.count(delimiter) == 0:
                raise
            return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))


class XLSXParser:
    def parse(self, content):
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        sheet = workbook.active
        values = sheet.iter_rows(values_only=True)
        header = next(values, None)
        if not header:
            return []
        return [
            dict(zip(header, row, strict=False)) for row in values if any(cell is not None for cell in row)
        ]


class PDFParser:
    def parse(self, content):
        reader = PdfReader(io.BytesIO(content), strict=False)
        if len(reader.pages) > 30:
            raise Clarification("PDF has too many pages for a safe statement preview.")
        rows = []
        extracted_text = False
        pattern = re.compile(r"^(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?[\d.,]+)\s*$")
        for page in reader.pages:
            text = page.extract_text() or ""
            extracted_text |= bool(text.strip())
            for line in text.splitlines():
                match = pattern.match(line.strip())
                if match:
                    rows.append({"date": match[1], "description": match[2], "amount": match[3]})
        if not extracted_text:
            raise Clarification(
                "I couldn't extract statement text from this PDF. Export a CSV/XLSX statement or provide a text-based PDF."
            )
        return rows


PARSERS = {".csv": CSVParser(), ".xlsx": XLSXParser(), ".pdf": PDFParser()}


def parse_statement(filename, content):
    suffix = Path(filename).suffix.lower()
    parser = PARSERS.get(suffix)
    if not parser:
        raise Clarification("Send a CSV, XLSX or text-extractable PDF statement.")
    try:
        raw = parser.parse(content)
    except (ValueError, csv.Error, KeyError, OSError, RuntimeError, PdfReadError) as exc:
        raise Clarification("I couldn't parse that statement. Check the file format and headers.") from exc
    if not raw or len(raw) > 2000:
        raise Clarification("No extractable rows found, or the statement exceeds 2,000 rows.")
    return [normalize_row(row, index) for index, row in enumerate(raw)]


async def duplicate_match(db, user_id, row, timezone="Asia/Jakarta"):
    date = statement_utc_date(row["date"], timezone)
    candidates = (
        await db.scalars(
            select(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.currency == row["currency"],
                Transaction.amount == Decimal(row["amount"]),
                Transaction.transaction_type == row["transaction_type"],
                Transaction.date >= date - timedelta(days=3),
                Transaction.date < date + timedelta(days=4),
            )
            .limit(50)
        )
    ).all()
    target = row["description"].casefold()
    return next(
        (
            item
            for item in candidates
            if SequenceMatcher(None, target, (item.merchant or item.description).casefold()).ratio() >= 0.72
        ),
        None,
    )


async def preview_statement(db, user_id, filename, content, account_name=None, timezone="Asia/Jakarta"):
    digest = hashlib.sha256(content).hexdigest()
    existing = await db.scalar(
        select(StatementImport).where(
            StatementImport.user_id == user_id,
            StatementImport.file_hash == digest,
            StatementImport.status == "committed",
        )
    )
    if existing:
        raise Clarification("This exact statement was already imported.")
    rows = parse_statement(filename, content)
    account = None
    if account_name:
        account = await db.scalar(
            select(Account).where(Account.user_id == user_id, Account.name == account_name)
        )
        if not account:
            raise Clarification("I couldn't find that account. Create it first or omit the account name.")
    for row in rows:
        if account and not row.get("currency"):
            row["currency"] = account.currency
            if (
                row.get("date")
                and row.get("description")
                and row.get("amount")
                and row.get("transaction_type")
                and row.get("reason", "").startswith("Missing or ambiguous")
            ):
                row["status"] = "ready"
                row.pop("reason", None)
        if row["status"] == "ready":
            if account and row["currency"] != account.currency:
                row["status"], row["reason"] = "review", "Currency differs from the selected account."
            elif match := await duplicate_match(db, user_id, row, timezone):
                row["status"], row["reason"], row["match_id"] = (
                    "duplicate",
                    "Matches a recorded transaction.",
                    match.id,
                )
    item = StatementImport(
        user_id=user_id,
        file_hash=digest,
        filename=filename[:250],
        account_id=account.id if account else None,
        rows={"items": rows},
        status="preview",
        imported_count=0,
    )
    db.add(item)
    await db.flush()
    counts = {
        state: sum(row["status"] == state for row in rows) for state in ("ready", "duplicate", "review")
    }
    sample = "\n".join(
        f"{r['date']} {r['description']}: {r['amount']} {r['currency']}"
        for r in rows
        if r["status"] == "ready"
    )[:800]
    review = "\n".join(
        f"row {row['index'] + 2}: {row.get('description') or 'Unknown'} · {row.get('raw_amount') or row.get('amount') or '?'} {row.get('currency') or '?'} · {row.get('reason', 'Needs review')}"
        for row in rows
        if row["status"] == "review"
    )[:400]
    message = (
        f"Statement preview: {filename}\n{len(rows)} rows · {counts['ready']} ready · {counts['duplicate']} duplicates · {counts['review']} need review.\n"
        + (f"Account: {account.name}\n" if account else "Account: unlinked\n")
        + sample
        + ("\nNeeds review:\n" + review if review else "")
        + "\nUse /statement_review to inspect rows, then /review_statement ROW expense|income|skip [CURRENCY] [YYYY-MM-DD] [AMOUNT]. Confirm to import ready rows only."
    )
    return item.id, message


async def latest_review(db, user_id):
    item = await db.scalar(
        select(StatementImport)
        .where(StatementImport.user_id == user_id, StatementImport.status == "preview")
        .order_by(StatementImport.created_at.desc())
    )
    if not item or aware(item.created_at) <= utcnow() - timedelta(hours=1):
        raise Clarification("There is no active statement preview to review. Upload the statement again.")
    return item


async def review_rows(db, user_id):
    item = await latest_review(db, user_id)
    uncertain = [row for row in item.rows["items"] if row["status"] == "review"]
    if not uncertain:
        return "No uncertain rows remain. Use the preview's Confirm button to import ready rows."
    return (
        "\n".join(
            f"Row {row['index'] + 2}: {row.get('date') or row.get('raw_date') or '?'} · "
            f"{row.get('description') or '?'} · {row.get('amount') or row.get('raw_amount') or '?'} "
            f"{row.get('currency') or '?'} — {row.get('reason') or 'Needs review'}"
            for row in uncertain[:10]
        )
        + "\nReply with /review_statement ROW expense|income|skip [CURRENCY] [YYYY-MM-DD] [AMOUNT]."
    )


async def review_row(
    db, user_id, row_number, action, currency=None, corrected_date=None, amount=None, timezone="Asia/Jakarta"
):
    item = await latest_review(db, user_id)
    index = row_number - 2
    rows = [dict(row) for row in item.rows["items"]]
    if index < 0 or index >= len(rows) or rows[index]["status"] != "review":
        raise Clarification("That row does not need review. Use /statement_review to see uncertain rows.")
    row = rows[index]
    if action == "skip":
        row["status"], row["reason"] = "skipped", "Skipped by user."
    elif action in {"expense", "income"}:
        if currency:
            row["currency"] = currency.upper()
        if corrected_date:
            row["date"] = parse_date(corrected_date)
        if amount:
            parsed_amount = parse_amount(amount)
            row["amount"] = str(abs(parsed_amount)) if parsed_amount is not None else None
        if (
            not row.get("date")
            or not row.get("description")
            or not row.get("amount")
            or row.get("currency") not in {"IDR", "USD", "EUR", "MYR", "SGD"}
        ):
            raise Clarification(
                "That row still needs a valid date, amount, description, and currency. Add corrections to the command."
            )
        value = Decimal(row["amount"])
        if not value.is_finite() or value <= 0 or value >= Decimal("1e18"):
            raise Clarification("The corrected amount must be positive and finite.")
        if item.account_id:
            account = await db.scalar(
                select(Account).where(Account.id == item.account_id, Account.user_id == user_id)
            )
            if account and row["currency"] != account.currency:
                raise Clarification("This row's currency differs from the selected account.")
        row["transaction_type"] = action
        row["status"] = "ready"
        row.pop("reason", None)
        if await duplicate_match(db, user_id, row, timezone):
            row["status"], row["reason"] = "duplicate", "Matches a recorded transaction."
    else:
        raise Clarification("Choose expense, income, or skip for that row.")
    item.rows = {"items": rows[:index] + [row] + rows[index + 1 :]}
    remaining = sum(r["status"] == "review" for r in rows)
    return f"Row {row_number} is {row['status']}. {remaining} rows still need review."


async def commit_statement(db, user_id, import_id, timezone="Asia/Jakarta"):
    item = await db.scalar(
        select(StatementImport)
        .where(StatementImport.user_id == user_id, StatementImport.id == import_id)
        .with_for_update()
    )
    if not item or item.status != "preview":
        raise Clarification("That statement preview is no longer available.")
    imported = 0
    for row in item.rows["items"]:
        if row["status"] != "ready" or await duplicate_match(db, user_id, row, timezone):
            continue
        source = f"statement:{item.id}:{row['index']}"
        exists = await db.scalar(
            select(Transaction.id).where(
                Transaction.user_id == user_id, Transaction.source_message_id == source
            )
        )
        if exists:
            continue
        transaction = Transaction(
            user_id=user_id,
            date=statement_utc_date(row["date"], timezone),
            amount=Decimal(row["amount"]),
            currency=row["currency"],
            merchant=row["description"],
            description=row["description"],
            category="Uncategorized",
            subcategory="",
            transaction_type=row["transaction_type"],
            account_id=item.account_id,
            payment_method="",
            source="statement",
            source_message_id=source,
            confidence=1.0,
            notes="Imported from statement preview",
            original_input=f"Statement {item.filename} row {row['index']}",
        )
        db.add(transaction)
        await db.flush()
        await enqueue_sync(db, user_id, "transaction", transaction.id)
        imported += 1
    item.status, item.imported_count = "committed", imported
    return f"Imported {imported} transactions. Duplicates and uncertain rows were skipped."
