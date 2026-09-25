# Ponke V2 handoff

## Implemented in the repository

- Existing Telegram, reminders, Calendar, finance, receipts, exports, portfolio bookkeeping, decision memory and per-user PostgreSQL storage are retained.
- Dedicated task/project lifecycle, priority ordering, briefing integration and decision follow-up delivery.
- Fast selective council and explicit bounded deep mode. User-facing answers use the revised Ponke voice; stable communication corrections are saved per user.
- Market providers for public Binance crypto, optional CoinGecko/Alpha Vantage/FRED and no-key Frankfurter FX, with cache, source/date and stale/manual fallback.
- Normalized investment research and deterministic growth, valuation and portfolio scenario calculations. No brokerage or order API exists.
- Conservative CSV/XLSX/text-PDF statement preview, duplicate matching, confirmation and idempotent commit.
- Optional Google Sheets OAuth and six-tab incremental sync using a durable PostgreSQL outbox.
- Additive `0002` and `0003` migrations preserve the initial schema and existing rows.

## Credentials and configuration

Keep credentials only in ignored `.env`. Existing Telegram and Gemini credentials remain necessary. Optional `COINGECKO_DEMO_API_KEY`, `ALPHA_VANTAGE_API_KEY` and `FRED_API_KEY` enable additional free-tier feeds. Binance crypto and Frankfurter FX need no key. Sheets needs `GOOGLE_SHEETS_ENABLED=true`, `GOOGLE_FINANCE_SHEET_ID`, the Sheets API enabled in Google Cloud, and a fresh `/connect_calendar` authorization. See [README.md](README.md) and [SETUP_STEP_BY_STEP.md](SETUP_STEP_BY_STEP.md).

## Deploy and verify

Back up PostgreSQL, then run `docker compose build`, `docker compose run --rm migrate`, and `docker compose up -d app`. Check `docker compose ps` and `/health/ready`. For a fresh setup, `docker compose up -d --build` runs migration first. Run automated tests and the A–K manual acceptance prompts in [README.md](README.md). [VERIFICATION.md](VERIFICATION.md) records what was actually exercised.

## Known limits

Provider quotas and symbol coverage vary. Alpha Vantage's free feed does not guarantee complete Indonesian fundamentals or historical financial statements; missing fields remain unknown. BI policy rates are not connected. PDF import covers extractable text, not scanned images. Unsigned statement amounts need review and are not auto-committed. Sheets does not backfill old rows automatically. Account balances are snapshots, not bank synchronization. Calendar availability is not yet incorporated into the task score. No automatic council reweighting or trade execution is provided.
