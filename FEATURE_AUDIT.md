# Ponke V2 feature audit

This separates implemented code paths from external services that still need credentials and live validation. PostgreSQL remains authoritative and each Telegram user owns separate rows.

| Area | Implemented | Limits / live step |
| --- | --- | --- |
| Selective council | Fast health uses Health only; investment uses Macro + Risk; purchase uses Lifestyle + Risk. Explicit deep mode permits a bounded second round and up to four relevant specialists. Natural synthesis omits scores. | Live model quality requires Telegram acceptance checks. |
| Market data | Exchange-aware asset identity, contextual IDX resolution, provider-symbol provenance, TTL cache and stale fallback. Public Binance USDT crypto; optional CoinGecko, Alpha Vantage, FRED; Frankfurter FX. | Bare unknown equity tickers ask for exchange. `.JK` quote/fundamental coverage depends on Alpha Vantage. BI rate and Indonesian CPI explicitly remain unavailable. |
| Investment research | Provider-neutral normalized fundamentals, missing-field checks, optional annual statements, deterministic valuation and same-currency purchase scenarios with known subtotal and cash-shortfall signals. No orders. | Missing holding prices make true concentration unknown; historical data varies by provider. No implicit FX conversion. |
| Statements | Strict Indonesian/international Decimal parsing, local-date UTC storage, conservative CSV/XLSX/text-PDF preview, duplicate checks, per-row correction/skip command, confirmation and idempotent commit. | Missing currency/direction/date/amount stays in review. Malformed columns require a corrected source file. Scanned PDFs need CSV/XLSX export. |
| Sheets | Optional OAuth Sheets scope, six tabs, incremental row upserts and durable retry outbox after relevant mutations. Attempts, last error/attempt and six-hour degraded retries are visible in PostgreSQL. | Requires a spreadsheet ID, Sheets API and reconnecting Google OAuth. No automatic backfill of pre-existing rows. |
| Tasks/projects | Dedicated persistent models, natural-language intents, CRUD, deterministic priority and briefing integration. Reminders remain separate. | Daily briefing passes known calendar free minutes to the task score; an unknown calendar leaves convenience neutral. |
| Analyst | Spending evidence, minimum samples for descriptive task/decision patterns, cross-domain aggregate foundation, 20-outcome informational calibration and decision follow-ups. | No causal correlation is generated from sparse samples or automatic council reweighting. |
| Personality | Direct concise answer prompt, context-sensitive humor, English default, stable per-user communication corrections, fixed brief tool confirmations. | Live language/style quality must be checked with the configured model. |
| Existing MVP | Telegram allowlist, reminders, Calendar, expenses, receipts, exports, portfolio bookkeeping, decision history and PostgreSQL persistence retained. | Live Telegram/Calendar/provider checks still require user credentials. |

See [VERIFICATION.md](VERIFICATION.md) for executed checks and [README.md](README.md) for setup and limits.
