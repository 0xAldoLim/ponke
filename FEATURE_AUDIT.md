# Ponke V2 feature audit

This separates implemented code paths from external services that still need credentials and live validation. PostgreSQL remains authoritative and each Telegram user owns separate rows.

| Area | Implemented | Limits / live step |
| --- | --- | --- |
| Selective council | Fast health uses Health only; investment uses Macro + Risk; purchase uses Lifestyle + Risk. Explicit deep mode permits a bounded second round and up to four relevant specialists. Natural synthesis omits scores. | Live model quality requires Telegram acceptance checks. |
| Market data | Provider abstraction, TTL cache, LIVE/CACHED/MANUAL provenance and stale fallback. Public Binance USDT crypto quote; optional CoinGecko, Alpha Vantage, FRED keys; no-key Frankfurter daily FX. | Crypto USDT is not USD. `.JK` and fundamentals depend on Alpha Vantage coverage. BI rate and some Indonesian indicators are not connected. |
| Investment research | Normalized result, missing metrics, optional annual statements with deterministic CAGR/trends/valuation, and same-currency portfolio purchase scenario. No orders. | Historical statement and multiple coverage varies by provider and ticker; missing data stays unknown. No implicit FX conversion. |
| Statements | Conservative CSV/XLSX/text-PDF parsers, preview, duplicate check against manual records, confirmation and idempotent commit. | Unsigned rows without a debit/credit column need review and are excluded from commit. Scanned PDFs need OCR outside Ponke. |
| Sheets | Optional OAuth Sheets scope, six tabs, incremental row upserts and durable retry outbox. Finance success is independent of Sheets success. | Requires a spreadsheet ID, Sheets API and reconnecting Google OAuth. No automatic backfill of pre-existing rows. |
| Tasks/projects | Dedicated persistent models, natural-language intents, CRUD, deterministic priority and briefing integration. Reminders remain separate. | Calendar availability is not yet fed into task scoring; the score accepts known free minutes when supplied. |
| Analyst | Spending evidence, recorded task completion counts, decision outcomes, 20-outcome informational calibration threshold, scheduled decision follow-ups. | These are descriptive samples, not causal conclusions or automatic council reweighting. |
| Personality | Direct concise answer prompt, context-sensitive humor, English default, stable per-user communication corrections, fixed brief tool confirmations. | Live language/style quality must be checked with the configured model. |
| Existing MVP | Telegram allowlist, reminders, Calendar, expenses, receipts, exports, portfolio bookkeeping, decision history and PostgreSQL persistence retained. | Live Telegram/Calendar/provider checks still require user credentials. |

See [VERIFICATION.md](VERIFICATION.md) for executed checks and [README.md](README.md) for setup and limits.
