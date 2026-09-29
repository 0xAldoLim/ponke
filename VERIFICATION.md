# Verification record — Ponke audit, 29 September 2026

- The last complete Python 3.12 suite before this audit passed **102 tests** against isolated PostgreSQL `ponke_test`.
- The final Python 3.12 suite against isolated PostgreSQL `ponke_test` passed **158 tests** after the audit fixes. Fixtures use outer transactions/savepoints; production rows were not used.
- Additive Alembic upgrade through `0004` succeeded on isolated PostgreSQL `ponke_test`; `alembic current` returned `0004 (head)` and `alembic check` found no schema drift.
- Ruff lint and format checks passed (`ruff check .`, `ruff format --check .`); all 42 Python files also parsed with the bundled Python runtime.
- The final suite includes statement checks confirming `48.000` becomes 48000, mixed separators become 1250000.50, malformed values are held for review, and `Rp48.000` can supply IDR explicitly.
- `docker compose build app migrate` completed successfully. A fresh binary PostgreSQL backup was saved at ignored `backups/ponke-pre-audit-20260929.dump` before the live migration; its `PGDMP` header was verified.
- The app was stopped for the migration, `docker compose run --rm migrate` completed successfully, and the live database reported Alembic version `0004`. The app was restarted; `/health/ready` returned `{"status":"ready"}` and startup logs reported no errors.
- GitHub Actions [CI run 36531883998](https://github.com/0xAldoLim/ponke/actions/runs/36531883998) for audit commit `ed18461` completed successfully, including lint, format, migration, tests, and Docker build.
- Live public market endpoint smoke checks from the local service environment returned a BTCUSDT Binance Spot quote and a dated USD/IDR Frankfurter reference rate. No trade endpoint was used.
- The earlier V2 backup remains outside Git. The new audit backup is also ignored by Git.

The new regression file covers money formats, malformed rows, IDX resolution, incomplete portfolio and cash scenarios, statement review and three timezones, partial fundamentals, default briefing tasks, priority scoring, deep-request detection, Sheets mutation/retry behavior and sparse analyst samples. Existing tests cover the original MVP and V2 flows.

These tests use controlled model and Google responses. They do not prove live Gemini interpretation, Google OAuth/Sheets authorization, real bank PDF extraction accuracy, provider coverage for a particular Indonesian ticker, or Telegram delivery from the user's account. Credentials remain in ignored `.env`; none are committed.
