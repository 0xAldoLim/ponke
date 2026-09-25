# Ponke

A private Telegram assistant for reminders, tasks, Google Calendar, personal finance, statement imports and considered decisions. Python 3.12, FastAPI, PostgreSQL, SQLAlchemy 2 and configurable Gemini or OpenAI, packaged as one service. Gemini 3.5 Flash-Lite is the default and has a free API tier.

**Start here:** create your credentials, follow the setup below, then run the acceptance checklist. No credentials are bundled, and live Telegram/Google/Gemini behavior requires your own authorization. The automated tests use controlled API responses rather than claiming that a mock proves live model accuracy.

For a beginner-friendly setup checklist, including a low-cost VPS path without a domain, see [SETUP_STEP_BY_STEP.md](SETUP_STEP_BY_STEP.md).

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
- “Finish internship report by Friday.” / “Mark internship report done.” / “What tasks are overdue?”
- “Create a project called Ponke V2.” / “What projects do I have?”
- Send a CSV, XLSX or text-extractable PDF bank statement to preview its rows, then confirm ready rows.
- “What is BTC's price?” / “Analyze BBCA.JK.” / “Should I add Rp5m to BTC?”
- “Deep council: should I buy a Rp500m car?” / “How have my decisions worked out?”
- `/data` shows where records and market values come from; `/calibration` summarizes sufficiently sampled outcomes.

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

Fill in the Telegram and Gemini credentials below. Choose a strong alphanumeric `POSTGRES_PASSWORD` and put the same password in `DATABASE_URL`. The Compose database hostname is `db`. If the password contains URL-reserved characters, percent-encode it in `DATABASE_URL` only.

If another local service uses port 8000, set `PONKE_HOST_PORT=8001` and `GOOGLE_REDIRECT_URI=http://localhost:8001/oauth/google/callback` in `.env`. Register that exact callback in Google Cloud if you connect Calendar. The container still listens on port 8000.

```powershell
docker compose up -d --build
docker compose ps
docker compose logs --tail 50 app
```

Compose waits for PostgreSQL, runs `alembic upgrade head`, then starts one application worker. Readiness is at [localhost:8000/health/ready](http://localhost:8000/health/ready). Telegram uses outbound long polling. There is no Telegram webhook to configure.

### Start automatically on Windows

Run `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_windows_startup.ps1` once. This installs a shortcut in your own Windows Startup folder. After you sign in, it starts Docker Desktop if needed, waits for Docker, starts the existing Compose stack without rebuilding or replacing the database volume, and writes a result to `%LOCALAPPDATA%\Ponke\startup.log`. You can run `scripts/start_ponke_windows.ps1` manually to check the same path now. Reinstall the shortcut if you move the project directory. Delete the `Ponke.lnk` shortcut from your Startup folder to disable automatic launch.

PostgreSQL data lives in Docker's named `ponke_pgdata` volume. Normal shutdown, reboot, container recreation and `docker compose down` keep that volume. `docker compose down -v` deletes it. Recent conversation context is limited to eight messages from seven days; expenses, reminders, preferences, decisions and other structured records remain in PostgreSQL until explicitly changed or deleted. A backup is still needed against disk loss or a damaged Docker installation.

## Telegram setup

1. Open the verified [BotFather](https://t.me/BotFather) in Telegram. Send `/newbot`, choose a display name and an available bot username ending in `bot`.
2. Copy the token into `TELEGRAM_BOT_TOKEN` in `.env`. Do not paste it into a browser address bar or commit it.
3. Open your new bot and send `/id` to get your numeric Telegram user ID. This command works in a private chat even before your ID is allowed, and reveals only your own ID. To add someone else, ask them to send `/id` to the bot and give you the number.
4. Alternatively, before Ponke starts, run `.\.venv\Scripts\python scripts/telegram_user_id.py`. It calls Telegram using the token from `.env` and prints numeric IDs and usernames, not message contents.
5. Put your numeric ID in `ALLOWED_TELEGRAM_USER_IDS`. Multiple approved IDs are comma-separated. Each gets separate database records and OAuth tokens; timezone, briefing configuration, calendar ID and model quota are deployment-wide. Only add people you trust with access to the bot's shared API quota. After editing the allowlist, run `docker compose up -d --force-recreate app` to load it.
6. Start Ponke and send `/start`. People outside the allowlist receive their own ID and access instructions; `/id` also works before approval. Only allowlisted users in private one-to-one chats can use assistant actions. In groups, Ponke directs `/start` and `/id` senders to a private chat without posting their ID; other group messages and edited messages do not trigger actions.

If the ID helper finds no updates, use `/id` in a private bot chat instead. [Telegram's official bot tutorial](https://core.telegram.org/bots/tutorial) explains BotFather and tokens.

Optional shortcuts: `/connect_calendar`, `/export_finance`, `/briefing`, `/reminders`, `/tasks`, `/projects`, `/data`, `/calibration`. Normal use is natural language.

## V2 market data and research

Ponke has swappable market providers with a PostgreSQL TTL cache. Public [Binance Spot market data](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md) supplies no-key BTC/ETH and other supported USDT pair quotes. Set `COINGECKO_DEMO_API_KEY` to use [CoinGecko Demo](https://support.coingecko.com/hc/en-us/articles/21880397454233-User-Guide-How-to-sign-up-for-CoinGecko-Demo-API-and-generate-an-API-key) for USD crypto prices, market cap and volume. Set `ALPHA_VANTAGE_API_KEY` for [equity quotes, compact daily history and available fundamentals](https://www.alphavantage.co/documentation/); `.JK` symbols are sent to the provider as entered, and unsupported tickers remain unavailable. [Frankfurter](https://frankfurter.dev/) supplies no-key daily reference FX rates. Set `FRED_API_KEY` for [US macro observations](https://fred.stlouisfed.org/docs/api/fred/series_observations.html). These are optional free or free-tier services with their own quotas and coverage.

Every quote names its source, observation date and LIVE/CACHED/MANUAL freshness. If a feed fails, Ponke uses an existing cached value with a stale warning, then a user-entered manual price when available. It never silently converts currencies. Research keeps absent financial metrics as missing, computes supported growth and valuation fields in Python, and considers recorded holdings and cash. A purchase scenario is hypothetical and **no trade is placed**. A USDT pair is not labeled as USD. A free feed does not imply complete historical fundamentals or Indonesian macro coverage.

## Statement imports and Sheets

Send a CSV, XLSX or text-extractable PDF privately. Generic headers such as `date`, `description`, `debit`, `credit`, `amount`, `currency` (including common Indonesian variants) are recognized. Rows with an unsigned amount and no debit/credit column remain **review-only** because direction is ambiguous. Ponke previews row counts and likely duplicates before showing Confirm/Cancel. Confirmation imports only ready rows, with idempotent source IDs and another duplicate check. Add an existing account name as the caption if you want rows linked to it; otherwise they are unlinked. PDF extraction is conservative; image-only or non-tabular PDFs need a CSV/XLSX export instead. Original statement bytes are not stored, but parsed preview rows remain in PostgreSQL until cleaned up.

Google Sheets is optional and never replaces PostgreSQL. Create a spreadsheet, enable the [Google Sheets API](https://developers.google.com/workspace/sheets/api/quickstart/python) in the same Google Cloud project, set `GOOGLE_SHEETS_ENABLED=true` and `GOOGLE_FINANCE_SHEET_ID` in `.env`, then send `/connect_calendar` again so OAuth requests the [Sheets scope](https://developers.google.com/workspace/sheets/api/scopes). Ponke creates tabs named Transactions, Accounts, Monthly Summary, Investments, Net Worth and Decision History and updates rows by stable ID. It uses a durable outbox with retries; a Sheets outage never rolls back a finance entry. Existing rows made before enabling Sheets are not backfilled automatically. The chosen spreadsheet is shared by any allowed user who grants access, with user-prefixed row IDs; use separate deployments/spreadsheets for strict external sharing boundaries.

## Gemini free-tier setup

In [Google AI Studio](https://aistudio.google.com/api-keys), create an API key in a **Free Tier** project. This is separate from the Google Calendar OAuth client. Set:

```dotenv
AI_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-key
GEMINI_PRIMARY_MODEL=gemini-3.5-flash-lite
GEMINI_FAST_MODEL=
GEMINI_REQUESTS_PER_MINUTE=8
```

Gemini 3.5 Flash-Lite supports image inputs and structured JSON output, and Google lists its standard API usage as free within your project's [active rate limits](https://ai.google.dev/gemini-api/docs/rate-limits). If its model is unavailable for your project or region, choose another free-tier model with both capabilities in AI Studio and update `GEMINI_PRIMARY_MODEL`. Ponke spaces requests for the configured per-minute rate and retries temporary limit errors. A single-domain decision uses one specialist call after routing; a mixed decision uses two specialists and one synthesis call. A daily quota or provider outage returns a clear retry message. Check your actual limits in AI Studio; they vary by account.

Google's [pricing table](https://ai.google.dev/gemini-api/docs/pricing) says Free Tier data may be used to improve its products. Ponke sends the task's bounded context and receipt image to Gemini; do not send sensitive records unless you accept those terms. Ponke sets `store=false` on each [Interactions API](https://ai.google.dev/gemini-api/docs/interactions-overview) request, which opts out of interaction history storage but does not override the Free Tier data-use terms.

If you instead choose OpenAI later, set `AI_PROVIDER=openai`, fill `OPENAI_API_KEY` and `OPENAI_PRIMARY_MODEL`, and optionally set `OPENAI_FAST_MODEL` to a model supporting structured outputs and image inputs. OpenAI calls use the [Responses structured output interface](https://developers.openai.com/api/docs/guides/structured-outputs). OpenAI API billing is separate from ChatGPT. Classification, receipts and simple replies use the fast model; complex analysis and council calls use the primary model. Optional per-million-token OpenAI prices in `.env` enable approximate usage cost logs. Unconfigured prices produce token counts without invented cost estimates.

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

The default suite uses SQLite with foreign keys and mocked APIs, including Gemini Interactions request/response tests and the OpenAI SDK against a mock HTTP transport. It verifies validation, routing, user boundaries, money, timezones/DST, recurrence, transaction persistence, receipts, category corrections, exports, council rounds, decision memory, OAuth encryption/refresh, confirmations and failure handling. It does not estimate live model extraction accuracy.

For the same service suite against PostgreSQL, use a **disposable database whose name ends in `_test`**. Apply migrations first, then set `TEST_DATABASE_URL` to that database and run pytest. Fixtures use outer transactions and savepoints to isolate test data. GitHub Actions provisions PostgreSQL 17, runs migrations, migration drift checks, the test suite and a Docker build.

After you supply credentials, run these live checks with small test entries:

The V2 acceptance prompts are:

| Case | Send | Check |
| --- | --- | --- |
| A | `Spent 48k on coffee using BCA.` | Correct deterministic IDR transaction. |
| B | `Finish internship report by Friday.` | Creates a Task, not a Reminder. |
| C | `What's important today?` | Briefing includes today's calendar and ranked tasks. |
| D | Upload a small CSV bank statement. | Preview shows ready, duplicate and review counts. |
| E | Confirm the statement preview. | Only ready nonduplicates are committed. |
| F | `Analyze BTC.` | Source, currency, as-of timestamp and missing fields are explicit. |
| G | `Should I add Rp5m to BTC?` | Recorded portfolio/cash and Macro + Risk inform a hypothetical scenario; no trade. |
| H | `Deep council: should I buy a Rp500m car?` | Explicit second round only; response remains concise. |
| I | `Analyze BBCA.JK.` | Available quote/fundamentals/valuation, with unknowns stated. |
| J | `How have my decisions worked out?` | Recorded outcomes; calibration says when sample is below 20. |
| K | Log an expense during a Sheets outage. | PostgreSQL write succeeds and outbox retries. |

The original MVP checks remain useful:

| Test | Send in Telegram | Verify |
|---|---|---|
| A | Remind me in 2 minutes to water the plants. | Saved reminder; notification arrives; Done records completion. |
| B | Gym Friday at 5 PM. | Ponke confirms a real event; verify it in Google Calendar. |
| C | Spent 48k on coffee using BCA. | IDR 48,000, Food & Drinks > Coffee; raw message is in export. |
| D | Send a receipt, then send it again. | First logs; duplicate asks before adding; Cancel keeps one entry. |
| E | How much did I spend on food this month? | Database total includes C and eligible D, excludes other categories. |
| F | Export my finances. | Telegram receives a valid workbook with eight sheets; CSV also works. |
| G | Should I spend Rp12m on a new PC? | Lifestyle and risk views synthesized briefly, missing evidence called out, persisted decision. |
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
  ├─ relevant specialist(s) → synthesis when needed → decision memory
  └─ bounded conversation context / explicit preferences / analyst / briefings
```

Modules are in `app/`; the orchestrator calls explicit validated Python functions, never model-generated SQL or shell. SQLAlchemy scopes reads and writes by the authenticated Telegram ID. The council selects only relevant specialists: health alone for health decisions, macro and risk for investments, lifestyle and risk for purchases and career choices. Fast mode uses one independent round and a concise synthesis where needed. Explicit deep mode can use up to four relevant specialists, one cross-review round, and a final synthesis. The reply gives the recommendation, shared ground, meaningful disagreement and critical missing evidence in natural prose. New council calls do not request numerical specialist scores or weights. Legacy numeric database columns remain for compatibility and store zero as a sentinel for new decisions; exports leave unscored confidence blank.

Financial amounts use `Decimal` and database `NUMERIC`. Totals, category spending, cash flow, savings rate, recorded-month averages, repeated-charge candidates, holding values, allocation and reported net worth are computed in code. FX is not inferred. Bank/cash/e-wallet balances are user-reconciled snapshots; expense logging does not silently rewrite a snapshot with unknown coverage. Investment-account balance snapshots are excluded from cash totals to avoid double-counting holdings. Reported net worth subtracts recorded liability-account balances; incomplete coverage is always explicit.

Receipt files are validated, decoded/re-encoded without metadata and sent to the vision model. Originals are not retained on disk. Extracted fields, hashes, the Telegram file identifier and transaction audit input are stored. Duplicate checks combine exact file/hash identity and merchant/date/amount with payment or perceptual similarity. Photos and model content cannot redefine application instructions. Structured output is a defense layer, not a claim of perfect prompt-injection immunity.

Conversation retrieval is at most eight entries from seven days. Older entries are pruned when that user next talks to Ponke. Structured preferences, transactions and decisions remain until deliberately managed. Relevant aggregates are retrieved for analysis; the whole database is never sent to the model. Plain Telegram responses avoid Markdown injection; spreadsheet exports escape formula-looking text.

Ponke's Telegram voice is direct and concise, with mild dry humor only when appropriate. It challenges weak assumptions without a canned template. English is the default even for Indonesian finance topics; an explicit Indonesian request or a fully Indonesian message can change the reply language. Stable corrections such as “Be shorter” are saved per user. Personality applies to user-facing model answers, not calculations, records or exports. Fixed tool confirmations stay brief and preserve their values. Longer requests show typing progress and one status message.

Reminders use one row plus RFC5545 daily/weekly/monthly/yearly recurrence. The scheduler produces at most one overdue occurrence per reminder after downtime and advances from the original recurrence, preserving local wall-clock time. Outbox entries persist through restart and retry delivery with backoff. Telegram has no client idempotency key: a crash after Telegram accepted a message but before the database marked it sent can produce a duplicate notification. This is **at-least-once**, not exactly-once delivery.

Daily briefings run once per local date after `DAILY_BRIEFING_TIME`; a restart later that day catches up once. Set `DAILY_BRIEFING_ENABLED=false` to disable. `DAILY_BRIEFING_SECTIONS` accepts `today,reminders,tasks,finance,notable,priorities`. Missing calendar data degrades to a clear unavailable message. Task priorities use explicit priority, deadline, overdue status and estimated effort. Insights distinguish recorded FACT from POSSIBLE PATTERN and avoid psychological claims. Decision follow-ups use the durable Telegram delivery queue.

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
- Optional market providers supply quotes and limited daily history; free-tier coverage, historical financial statements and some Indonesian macro data remain incomplete. No live news, medical evidence search, brokerage execution, banking sync or automatic FX conversion. Time-sensitive evidence is identified as missing.
- Reported net worth depends on your recorded assets, liability snapshots and prices. Unknown balances are never fabricated; stale snapshots are flagged.
- No calendar recurrence creation/editing, recurring exception editor, OCR for scanned statements, voice, arbitrary administrative operations, or web dashboard. These are outside this MVP's implemented interface.
- Account/portfolio edits require confirmation; balances do not automatically reconcile with backdated transactions. Quantity precision is ten decimals; monetary precision is four decimals.
- Receipt duplicate matching is heuristic. Separate purchases can match; a confirmed override is available. Poor receipts need explicit correction.
- A crash mid-request may leave an inbound request marked processing or an action outcome uncertain. Ponke avoids blind replay; inspect records before a new request. Durable conversational response delivery and automated recovery are recommended next.
- Export loads a user's records into memory; intended for personal-scale data, not multi-million-row ledgers. Excel recalculates formulas when opened; Python does not calculate Excel's formula cache.
- No automated specialist usefulness scores on tiny samples. Outcomes are stored and informational summaries are available; a properly evaluated calibration system is future work. Legacy numeric council fields are kept for compatibility but new council calls do not generate scores.

Recommended next: recurring-merchant review UI, cash reconciliation, dated FX/market providers, liabilities maturity tracking, stronger receipt similarity indexing, durable inbound/reply queue, user-specific preferences for timezone/briefing, provider-health alerts and a representative live evaluation set.

See [DELIVERY.md](DELIVERY.md) for the handoff checklist and [VERIFICATION.md](VERIFICATION.md) for tested versus unverified behavior.
