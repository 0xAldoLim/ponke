# Verification record — Ponke V2, 25 September 2026

- Full Python 3.12 suite against the isolated migrated PostgreSQL `ponke_test` database: **102 passed**. Fixtures use outer transactions/savepoints; no production records were used.
- Ruff lint and format checks passed: `ruff check .` and `ruff format --check .` (run without cache on a read-only source mount).
- Additive Alembic upgrades through `0003` succeeded on disposable PostgreSQL and SQLite. `alembic check` found no PostgreSQL schema drift.
- Live public market endpoint smoke checks from the local service environment returned a BTCUSDT Binance Spot quote and a dated USD/IDR Frankfurter reference rate. No trade endpoint was used.
- A binary PostgreSQL backup was saved outside Git before local rollout. The existing database volume was not replaced.

Automated coverage includes selective/deep council bounds, task lifecycle and user ownership, CSV/XLSX statement validation, preview and idempotent confirmation, market cache freshness/stale behavior, deterministic research calculations, outcome recording, Sheets upsert/retry behavior, unapproved-user Telegram onboarding, and regression tests for the original MVP.

These tests use controlled model and Google responses. They do not prove live Gemini interpretation, Google OAuth/Sheets authorization, real bank PDF extraction accuracy, provider coverage for a particular Indonesian ticker, or Telegram delivery from the user's account. Those require the live A–K acceptance prompts in [README.md](README.md). Credentials remain in ignored `.env`; none are committed.
