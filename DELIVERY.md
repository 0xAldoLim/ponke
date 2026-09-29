# Ponke V2 handoff

## Implemented in the repository

- Existing Telegram, reminders, Calendar, finance, receipts, exports, portfolio bookkeeping, decision memory and per-user PostgreSQL storage are retained.
- Dedicated task/project lifecycle, priority ordering, briefing integration and decision follow-up delivery.
- Fast selective council and explicit bounded deep mode. User-facing answers use the revised Ponke voice; stable communication corrections are saved per user.
- Market providers for public Binance crypto, optional CoinGecko/Alpha Vantage/FRED and no-key Frankfurter FX, with cache, source/date and stale/manual fallback.
- Provider-normalized fundamentals, exchange-aware IDX resolution, deterministic growth/valuation, known-subtotal portfolio scenarios and cash affordability. No brokerage or order API exists.
- Strict Indonesian/international statement amount parsing, local-date storage, CSV/XLSX/text-PDF preview, per-row review, confirmation and idempotent commit.
- Optional Google Sheets OAuth and six-tab incremental sync with a retry-observable PostgreSQL outbox.
- Additive migrations through `0004` preserve existing symbols and rows; new Asset exchange/provider-symbol fields are nullable.

## Credentials and configuration

Keep credentials only in ignored `.env`. Existing Telegram and Gemini credentials remain necessary. Optional `COINGECKO_DEMO_API_KEY`, `ALPHA_VANTAGE_API_KEY` and `FRED_API_KEY` enable additional free-tier feeds. Binance crypto and Frankfurter FX need no key. Sheets needs `GOOGLE_SHEETS_ENABLED=true`, `GOOGLE_FINANCE_SHEET_ID`, the Sheets API enabled in Google Cloud, and a fresh `/connect_calendar` authorization. See [README.md](README.md) and [SETUP_STEP_BY_STEP.md](SETUP_STEP_BY_STEP.md).

## Deploy and verify

Back up PostgreSQL, then run `docker compose build`, `docker compose run --rm migrate`, and `docker compose up -d app`. Check `docker compose ps` and `/health/ready`. For a fresh setup, `docker compose up -d --build` runs migration first. Run automated tests and the A–K manual acceptance prompts in [README.md](README.md). [VERIFICATION.md](VERIFICATION.md) records what was actually exercised.

## Known limits

Provider quotas and symbol coverage vary. Alpha Vantage's free feed does not guarantee Indonesian quotes, fundamentals or historical financial statements; missing fields remain unknown. Bare ambiguous tickers require an exchange. BI policy rates and Indonesian CPI are not connected. PDF import covers extractable text, not scanned images. Uncertain statement rows need explicit correction or skip before import; malformed columns require a new file. Sheets does not backfill old rows automatically. Account balances are snapshots, not bank synchronization. Daily briefing uses calendar free minutes only when available. No automatic council reweighting or trade execution is provided.
