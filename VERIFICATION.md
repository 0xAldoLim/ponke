# Verification record

## Gemini Free Tier update — 24 September 2026

- Ruff lint and formatting checks passed for the updated tree.
- Docker-based Python 3.12 run against a separate migrated PostgreSQL test database: **75 passed**. Test settings now ignore live application environment variables, so local credentials and timezone cannot change acceptance assertions.
- Mock HTTP transport verified Gemini Interactions request shape, image input, JSON response validation, temporary-limit retry, and provider-specific key requirements. Real receipt extraction accuracy remains unmeasured.
- A current production Docker image built successfully, and the local app and database both passed health checks. A prior build attempt hit a temporary PyPI read timeout; a retry completed.
- With user-provided credentials kept outside Git, Telegram `getMe` identified the configured bot and Google confirmed model access. Live Gemini structured output and a harmless reminder intent succeeded. A synthetic Decision Council run completed four independent first-round opinions, four second-round opinions, and a Chief Analyst verdict. No personal financial payload was used for these live model checks.
- Google Calendar OAuth has not been configured. Real receipt extraction, natural-language financial interpretation, Telegram delivery timing and Calendar A/I workflows still need user-driven live acceptance checks.

Verification date: 14 September 2026.

## Executed locally

- Python 3.12.14 with PostgreSQL 17: **69 tests passed** in the final complete run (91.47 seconds; no skips).
- The production-engine run includes acceptance workflows A–I, using real PostgreSQL persistence and controlled external API responses.
- Earlier SQLite run: 67 passed and the PostgreSQL-only check skipped; subsequent regression additions were verified against PostgreSQL.
- Ruff lint and formatting checks passed. `pip check` reported no broken requirements.
- Alembic upgrade, downgrade to base, re-upgrade and migration drift checks passed on the disposable PostgreSQL database. Initial upgrade/drift were also verified on SQLite.
- Docker image built successfully with Python 3.12-slim and the pinned runtime dependencies.
- Network-disabled Docker smoke test imported FastAPI and all 20 database tables as UID 1000 (non-root).
- Compose configuration validated using the placeholder environment template; no real `.env` was created.
- OpenAI Responses structured-output requests were exercised through the installed SDK using mock HTTP transport.
- Google OAuth state/PKCE, encryption, refresh, pagination and create retry behavior were exercised with mock HTTP responses.
- Regression tests cover fractional holdings, recorded liabilities, corrected-receipt duplicate checks, recurring reminder completion, OAuth-link exclusion from model context and reviewed bulk deletion.

The first Docker build encountered a Windows test-cache access error. Excluding generated caches in `.dockerignore` resolved it. An earlier PostgreSQL test run emitted a pytest cache-permission warning; the final run disabled that nonessential cache and passed cleanly.

## What these tests do not prove

No live OpenAI API calls were purchased and no personal Google account or Telegram bot was connected. Real natural-language accuracy, receipt extraction accuracy, live Telegram delivery and Google authorization require the credentials and live checks in README. The tests deliberately control model responses; they prove application routing, validation, persistence and handling of those responses, not that a model always chooses the correct intent.

No paid deployment was created. No real credentials or financial records are included. The Docker image and disposable PostgreSQL database are local test resources. GitHub Actions provides an additional Linux/PostgreSQL/build check after publication; its result is separate from the local results above.
