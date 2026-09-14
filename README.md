# Ponke

A private Telegram chief of staff for reminders, Google Calendar, personal finance, receipts and considered decisions. Python 3.12, FastAPI, PostgreSQL, SQLAlchemy 2 and a configurable OpenAI Responses API model, packaged as one service.

**Start here:** create your credentials, follow the setup below, then run the acceptance checklist. No credentials are bundled, and live Telegram/Google/OpenAI behavior requires your own authorization. The automated tests use controlled API responses rather than claiming that a mock proves live model accuracy.

## What you can say

- “Remind me tomorrow at 8 PM to water the plants.”
- “Remind me every Friday at 6 PM to review spending.”
- “Gym Friday at 5 PM.” / “What's my schedule tomorrow?”
- “Spent 48k on coffee using BCA.” / “Mom gave me 2 million.”
- Send a JPEG/PNG receipt, as a photo or image document.
- “How much did I spend on food this month?” / “Analyze my spending.”
- “Export my finances.” / “Export transactions as CSV.”
- “ACE Hardware should be Gardening.”
- “Set my monthly IDR budget to 8 million.”
- “My BCA bank account balance is 20 million IDR.”
- “Record my credit card debt account with a balance of 2 million IDR and type liability.”
- “Create account Binance, type crypto, currency IDR.”
- “Record a holding of 0.01 BTC in Binance, asset type crypto, currency IDR, average cost 900 million IDR per BTC.”
- “Set the manual BTC price to 1 billion IDR.” Write `1000000000` if shorthand is unclear.
- “Record that I bought 0.001 BTC in Binance at 1000000000 IDR per BTC.” This records an already-executed trade; it cannot place orders.
- “Should I spend Rp12m on a PC?” / “Should I add 5m IDR to BTC?”
- “What did the council previously say about my PC?” / “details”
- “Record the outcome for decision [ID]: I waited and saved money; satisfaction 80.”
- “Give me my morning briefing.”

Ordinary small expense logs and clear reminders run immediately. Large financial entries, account/portfolio changes, calendar edits/deletions, and duplicate overrides are reviewed through expiring, user-bound confirmation buttons. Ambiguous inputs ask for clarification. Explicit deletion of all transactions requires confirmation of the exact reviewed count and preserves subsequently added entries.

## Quick start with Docker

Install Docker Engine with Compose (Linux) or Docker Desktop (Windows/macOS). Use Python 3.12+ for the setup helpers and local tests.

```powershell
git clone https://github.com/0xAldoLim/ponke.git
cd ponke
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.lock
.\.venv\Scripts\python -m pip install --no-deps -e .
.\.venv\Scripts\python scripts/generate_key.py
```

On Linux/macOS, use `cp .env.example .env` and `.venv/bin/python` instead of the Windows Python path.

Paste the generated key into `APP_SECRET_KEY` in `.env`. This key encrypts Google tokens; retain it securely with your backups. Do not replace it on every restart.

Fill in the Telegram and OpenAI credentials below. Choose a strong alphanumeric `POSTGRES_PASSWORD` and put the same password in `DATABASE_URL`. The Compose database hostname is `db`. If the password contains URL-reserved characters, percent-encode it in `DATABASE_URL` only.

```powershell
docker compose up -d --build
docker compose ps
docker compose logs --tail 50 app
```

Compose waits for PostgreSQL, runs `alembic upgrade head`, then starts one application worker. Readiness is at [localhost:8000/health/ready](http://localhost:8000/health/ready). Telegram uses outbound long polling. There is no Telegram webhook to configure.

## Telegram setup

1. Open the verified [BotFather](https://t.me/BotFather) in Telegram. Send `/newbot`, choose a display name and an available bot username ending in `bot`.
2. Copy the token into `TELEGRAM_BOT_TOKEN` in `.env`. Do not paste it into a browser address bar or commit it.
3. Open your new bot and send `/start` **before starting Ponke**.
4. Run `.\.venv\Scripts\python scripts/telegram_user_id.py`. It calls Telegram using the token from `.env` and prints numeric IDs and usernames, not message contents.
5. Put your numeric ID in `ALLOWED_TELEGRAM_USER_IDS`. Multiple approved IDs are comma-separated. Each gets separate database records and OAuth tokens; timezone, briefing configuration and calendar ID are deployment-wide.
6. Start Ponke and send `/start` again. Only allowlisted users in private one-to-one chats are accepted. Group chats, unauthorized users and edited messages do not trigger actions.

If the ID helper finds no updates, stop the running app, send another message to the bot and retry. [Telegram's official bot tutorial](https://core.telegram.org/bots/tutorial) explains BotFather and tokens.

Optional shortcuts: `/connect_calendar`, `/export_finance`, `/briefing`, `/reminders`. Normal use is natural language.

## OpenAI setup

Create an API key in your [OpenAI API project](https://platform.openai.com/api-keys), enable billing and set a project budget. ChatGPT subscription access is separate from API access.

```dotenv
OPENAI_API_KEY=your-project-api-key
OPENAI_PRIMARY_MODEL=gpt-6-astra
OPENAI_FAST_MODEL=
```

The primary model remains configurable. Choose a fast model available to your project that supports **structured outputs and image inputs**. Leaving it blank uses the primary model for all calls; it does not silently substitute another model. Verify your account's model access before live use. Ponke uses the [Responses structured output interface](https://developers.openai.com/api/docs/guides/structured-outputs) and the requested [GPT-6 Astra model](https://developers.openai.com/api/docs/models/gpt-6-astra).

Classification, receipts and simple replies use the fast configuration; complex analysis and council calls use the primary configuration. A council request makes eight specialist calls plus one judge call, in addition to routing. Requests have timeouts and the SDK retries transient failures at most twice. `store=False` disables application-requested response persistence; it does not constitute a zero-retention guarantee from the provider.

Optional per-million-token prices in `.env` enable approximate usage cost logs. Unconfigured prices produce token counts without invented cost estimates. Estimates do not account for every provider discount, cache policy or pricing tier.

## Google Calendar setup

1. In [Google Cloud Console](https://console.cloud.google.com/), create or select your own project.
2. Open **APIs & Services → Library** and enable **Google Calendar API**.
3. Open **Google Auth Platform** (or **OAuth consent screen** in APIs & Services). Set an app name, your support email and developer contact email.
4. Choose the appropriate audience. For a personal external app in Testing, add your Google account as a **test user**.
5. In Data Access/scopes, add `https://www.googleapis.com/auth/calendar.events`.
6. Open Clients / Credentials → **Create OAuth client ID** → **Web application**. Do not select Desktop app: Ponke implements a web-server callback.
7. Add this exact authorized redirect URI for local use: `http://localhost:8000/oauth/google/callback`. For a deployed instance use your HTTPS domain, for example `https://ponke.example.com/oauth/google/callback`.
8. Copy the client ID and client secret into `.env`, alongside the identical redirect URI:

```dotenv
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/oauth/google/callback
GOOGLE_CALENDAR_ID=primary
```

9. Restart with `docker compose up -d`. In Telegram, send `/connect_calendar`. Open the generated link, select your Google account, grant the requested calendar access, and wait for “Google Calendar connected”. Links expire after ten minutes and can be used once.
10. For a localhost callback, open the link in a browser on the same computer running Ponke. Opening it on your phone will point at your phone's localhost. Use your deployed HTTPS URL for phone-based setup.

OAuth uses state binding, PKCE, encrypted access/refresh tokens, expiration and refresh. No Google password is requested or stored. If Google revokes access or a testing-mode refresh token expires, reconnect in Telegram. External apps in Testing can have short-lived refresh tokens; review Google's production/verification requirements for long-lived deployment. See [Google's web-server OAuth guide](https://developers.google.com/identity/protocols/oauth2/web-server) and [Calendar setup guide](https://developers.google.com/workspace/calendar/api/quickstart/python).

The API supports listing/searching, creating, updating and deleting events, all-day display, pagination and overlap checks. Creation uses a deterministic event ID for retry safety. Updates use ETags; changes to an event invalidate its pending review. Relative dates resolve in `USER_TIMEZONE` (default `Asia/Jakarta`); output uses that timezone. Shared or other calendars can be selected through `GOOGLE_CALENDAR_ID` if the authorized account has access.

## Running locally without containerizing the app

Keep PostgreSQL in Docker and expose it to localhost using this optional override:

```yaml
# compose.local.yml
services:
  db:
    ports:
      - "127.0.0.1:5432:5432"
```

```powershell
docker compose -f docker-compose.yml -f compose.local.yml up -d db
```

Change `DATABASE_URL` in your local `.env` to `postgresql+asyncpg://ponke:YOUR_PASSWORD@localhost:5432/ponke`, then run:

```powershell
.\.venv\Scripts\python -m alembic upgrade head
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

Do not run the local app and Compose app simultaneously. The PostgreSQL advisory lock prevents a second Ponke instance on the same database; Telegram also allows only one polling consumer for a token. Do not use multiple Uvicorn workers.

## Tests and acceptance checklist

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m ruff format --check .
```

The default suite uses SQLite with foreign keys and mocked APIs, including the actual OpenAI SDK against a mock HTTP transport. It verifies validation, routing, user boundaries, money, timezones/DST, recurrence, transaction persistence, receipts, category corrections, exports, council rounds, decision memory, OAuth encryption/refresh, confirmations and failure handling. It does not estimate live model extraction accuracy.

For the same service suite against PostgreSQL, use a **disposable database whose name ends in `_test`**. Apply migrations first, then set `TEST_DATABASE_URL` to that database and run pytest. Fixtures use outer transactions and savepoints to isolate test data. GitHub Actions provisions PostgreSQL 17, runs migrations, migration drift checks, the test suite and a Docker build.

After you supply credentials, run these live checks with small test entries:

| Test | Send in Telegram | Verify |
|---|---|---|
| A | Remind me in 2 minutes to water the plants. | Saved reminder; notification arrives; Done records completion. |
| B | Gym Friday at 5 PM. | Ponke confirms a real event; verify it in Google Calendar. |
| C | Spent 48k on coffee using BCA. | IDR 48,000, Food & Drinks > Coffee; raw message is in export. |
| D | Send a receipt, then send it again. | First logs; duplicate asks before adding; Cancel keeps one entry. |
| E | How much did I spend on food this month? | Database total includes C and eligible D, excludes other categories. |
| F | Export my finances. | Telegram receives a valid workbook with eight sheets; CSV also works. |
| G | Should I spend Rp12m on a new PC? | Two-round council output, missing evidence called out, persisted decision. |
| H | What did the council previously say about buying a PC? | Matching stored advice; “details” retrieves specialist summaries. |
| I | What's my schedule tomorrow? | Correct local dates and Asia/Jakarta times. |

Also test Cancel on a large expense; a second unauthorized Telegram account; moving/deleting an event; a weekly reminder; a blurry receipt; and a temporary network outage. No operation should claim success without a corresponding confirmed result. A remote timeout can leave an uncertain outcome: check the provider before resubmitting.

## Architecture and guarantees

```text
Telegram private chat → allowlist/rate limit → structured intent → typed service dispatch
  ├─ Google Calendar / encrypted per-user OAuth
  ├─ PostgreSQL reminders → durable delivery outbox → Telegram
  ├─ expenses / receipts / merchant rules → decimal analytics → XLSX/CSV
  ├─ holdings / reported trades / manual prices / reported liabilities
  ├─ council: 4 independent → 4 rebuttals → Chief Analyst → decision memory
  └─ bounded conversation context / explicit preferences / analyst / briefings
```

Modules are in `app/`; the orchestrator calls explicit validated Python functions, never model-generated SQL or shell. SQLAlchemy scopes reads and writes by the authenticated Telegram ID. Council specialists receive identical factual context independently in round one. Their second-round summaries and the judge's contextual weights are persisted; scores are not mechanically averaged. Outcome data supports later calibration, but no automatic weighting is active.

Financial amounts use `Decimal` and database `NUMERIC`. Totals, category spending, cash flow, savings rate, recorded-month averages, repeated-charge candidates, holding values, allocation and reported net worth are computed in code. FX is not inferred. Bank/cash/e-wallet balances are user-reconciled snapshots; expense logging does not silently rewrite a snapshot with unknown coverage. Investment-account balance snapshots are excluded from cash totals to avoid double-counting holdings. Reported net worth subtracts recorded liability-account balances; incomplete coverage is always explicit.

Receipt files are validated, decoded/re-encoded without metadata and sent to the vision model. Originals are not retained on disk. Extracted fields, hashes, the Telegram file identifier and transaction audit input are stored. Duplicate checks combine exact file/hash identity and merchant/date/amount with payment or perceptual similarity. Photos and model content cannot redefine application instructions. Structured output is a defense layer, not a claim of perfect prompt-injection immunity.

Conversation retrieval is at most eight entries from seven days. Older entries are pruned when that user next talks to Ponke. Structured preferences, transactions and decisions remain until deliberately managed. Relevant aggregates are retrieved for analysis; the whole database is never sent to the model. Plain Telegram responses avoid Markdown injection; spreadsheet exports escape formula-looking text.

Reminders use one row plus RFC5545 daily/weekly/monthly/yearly recurrence. The scheduler produces at most one overdue occurrence per reminder after downtime and advances from the original recurrence, preserving local wall-clock time. Outbox entries persist through restart and retry delivery with backoff. Telegram has no client idempotency key: a crash after Telegram accepted a message but before the database marked it sent can produce a duplicate notification. This is **at-least-once**, not exactly-once delivery.

Daily briefings run once per local date after `DAILY_BRIEFING_TIME`; a restart later that day catches up once. Set `DAILY_BRIEFING_ENABLED=false` to disable. `DAILY_BRIEFING_SECTIONS` accepts `today,reminders,finance,notable,priorities`. Missing calendar data degrades to a clear unavailable message. Insights distinguish recorded FACT from POSSIBLE PATTERN and avoid psychological claims.

## Deployment: one small Linux VPS

Use one Linux server with Docker/Compose and persistent storage. Clone the repository, create a private `.env`, set `APP_ENV=production`, fill credentials and run `docker compose up -d --build`. Docker Compose is suitable for a [single-server deployment](https://docs.docker.com/compose/how-tos/production/).

The Compose file binds port 8000 to loopback and leaves PostgreSQL unexposed. For Google authorization on a phone, put a reverse proxy with a valid HTTPS certificate in front of localhost:8000. For example, with Caddy installed on the host and your domain pointing to the server:

```caddyfile
ponke.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Allow ports 80/443 for the proxy and your SSH administration port; do not expose PostgreSQL. Set the identical HTTPS callback in Google Cloud and `.env`. Do not enable proxy access logs that retain OAuth query strings. Telegram itself still polls outbound; no webhook endpoint is implemented or required.

Before an update, take a backup, then:

```sh
docker compose stop app
git pull --ff-only
docker compose build
docker compose run --rm migrate
docker compose up -d
```

Inspect `/health/ready` and run one reminder/calendar test. Keep one replica. Arrange host monitoring, disk alerts, encrypted volumes and security updates. No infrastructure, DNS or paid server is created by the code.

## Backups and recovery

From the project directory, with Docker available:

```sh
python scripts/backup.py backups/ponke-2026-09-14.dump
```

Use a unique filename each time. The helper writes `pg_dump -Fc` directly to a binary file and refuses to overwrite an existing backup. Encrypt the dump, copy it off-host, and keep the original `APP_SECRET_KEY` separately in a password manager. Database dumps contain sensitive financial history even though OAuth tokens are encrypted.

Test restoration on a disposable deployment before relying on a backup. To deliberately replace the configured database:

```sh
docker compose stop app
python scripts/restore.py backups/ponke-2026-09-14.dump --replace-database-contents
docker compose run --rm migrate
docker compose up -d app
```

A database dump without the encryption key cannot recover Google tokens; reconnect each Google account instead. Do not run `docker compose down -v` unless you intend to remove database storage.

## Limitations and next steps

- Live model interpretation, Telegram delivery and Google authorization need your credentials and live acceptance checks. No real financial records are seeded.
- Manual market-price snapshots only; historical price retrieval is empty by design. No live financial news, medical evidence search, brokerage execution, banking sync or FX conversion. Time-sensitive evidence is identified as missing.
- Reported net worth depends on your recorded assets, liability snapshots and prices. Unknown balances are never fabricated; stale snapshots are flagged.
- No calendar recurrence creation/editing, recurring exception editor, arbitrary document/PDF extraction, voice, arbitrary administrative operations, or web dashboard. These are outside this MVP's implemented interface.
- Account/portfolio edits require confirmation; balances do not automatically reconcile with backdated transactions. Quantity precision is ten decimals; monetary precision is four decimals.
- Receipt duplicate matching is heuristic. Separate purchases can match; a confirmed override is available. Poor receipts need explicit correction.
- A crash mid-request may leave an inbound request marked processing or an action outcome uncertain. Ponke avoids blind replay; inspect records before a new request. Durable conversational response delivery and automated recovery are recommended next.
- Export loads a user's records into memory; intended for personal-scale data, not multi-million-row ledgers. Excel recalculates formulas when opened; Python does not calculate Excel's formula cache.
- No automated specialist usefulness scores on tiny samples. Outcomes are stored and informational summaries are available; a properly evaluated calibration system is future work.

Recommended next: recurring-merchant review UI, cash reconciliation, dated FX/market providers, liabilities maturity tracking, stronger receipt similarity indexing, durable inbound/reply queue, user-specific preferences for timezone/briefing, provider-health alerts and a representative live evaluation set.

See [DELIVERY.md](DELIVERY.md) for the handoff checklist and [VERIFICATION.md](VERIFICATION.md) for tested versus unverified behavior.
