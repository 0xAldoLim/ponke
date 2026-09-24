# Ponke: step-by-step setup

This guide gets your private Telegram assistant running with the existing Docker Compose configuration. You can test on your own computer or install on a small Linux server for reminders and briefings while your computer is off. You can keep Google Calendar without paying Google Cloud to host Ponke.

## What you need

1. A Telegram account and a new bot token from [BotFather](https://core.telegram.org/bots/tutorial).
2. A [Google AI Studio API key](https://aistudio.google.com/api-keys) in a Free Tier project for Gemini. No OpenAI account is required for the default configuration.
3. A Google account and a Google Cloud project with the Calendar API enabled **if you want Google Calendar**. Standard Calendar API use is available without extra charge within Google's published threshold.
4. Git and Docker with the Compose plugin. On Windows/macOS, use Docker Desktop. On Ubuntu, follow [Docker's official installation guide](https://docs.docker.com/engine/install/ubuntu/).
5. For 24/7 use, a Linux server with at least 2 GB RAM (4 GB gives more build headroom), SSH access, persistent disk, and outbound internet. A domain is optional if you connect Google Calendar from your computer through an SSH tunnel.

Keep the bot token, Gemini key, Google client secret, database password, and `APP_SECRET_KEY` private. Never add `.env` to Git.

## 1. Create your Telegram bot

1. In Telegram, open the verified **@BotFather** account.
2. Send `/newbot`, choose a display name, then an available username ending in `bot`.
3. Save the token BotFather returns. This becomes `TELEGRAM_BOT_TOKEN`.
4. Open your new bot's private chat and send `/start`. Leave Ponke stopped until you obtain your numeric Telegram ID in step 4.

## 2. Create a free-tier Gemini API key

1. Sign in to [Google AI Studio](https://aistudio.google.com/api-keys) with your Google account.
2. Create or select a project on the **Free Tier**. Keep billing disabled for this project if you want to stay on the Free Tier.
3. Create an API key and save it privately. In AI Studio, check that `gemini-3.5-flash-lite` is available and view your [active rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).

This key becomes `GEMINI_API_KEY`. It is separate from the Google Calendar OAuth client. Google's [pricing page](https://ai.google.dev/gemini-api/docs/pricing) lists standard Flash-Lite calls as free on the Free Tier, with usage limits. Google also says Free Tier data may be used to improve its products; Ponke sends task context and receipt images to this model. An optional OpenAI provider remains available in [README.md](README.md#gemini-free-tier-setup).

## 3. Download Ponke and make a private configuration file

On **Windows PowerShell**:

```powershell
git clone https://github.com/0xAldoLim/ponke.git
cd ponke
Copy-Item .env.example .env
docker compose build app
docker compose run --rm --no-deps app python scripts/generate_key.py
```

On **Ubuntu/Linux**:

```sh
git clone https://github.com/0xAldoLim/ponke.git
cd ponke
cp .env.example .env
sudo docker compose build app
sudo docker compose run --rm --no-deps app python scripts/generate_key.py
```

The last command prints a single encryption key. Paste it into `APP_SECRET_KEY` in `.env`. Keep the same key for the life of this installation, including restores.

Edit `.env` with a text editor. Set the following before starting the app:

```dotenv
APP_ENV=production
APP_SECRET_KEY=THE_KEY_GENERATED_ABOVE
TELEGRAM_BOT_TOKEN=THE_TOKEN_FROM_BOTFATHER
ALLOWED_TELEGRAM_USER_IDS=
AI_PROVIDER=gemini
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
GEMINI_PRIMARY_MODEL=gemini-3.5-flash-lite
GEMINI_FAST_MODEL=
GEMINI_REQUESTS_PER_MINUTE=8
POSTGRES_PASSWORD=YOUR_LONG_LETTERS_AND_NUMBERS_PASSWORD
DATABASE_URL=postgresql+asyncpg://ponke:YOUR_LONG_LETTERS_AND_NUMBERS_PASSWORD@db:5432/ponke
USER_TIMEZONE=Asia/Jakarta
DEFAULT_CURRENCY=IDR
```

Choose your own timezone/currency before starting; the example above uses the repository defaults for Indonesia. For Malaysia, use `USER_TIMEZONE=Asia/Kuala_Lumpur` and `DEFAULT_CURRENCY=MYR`. The database password must be identical in both lines. A password containing only letters and digits avoids URL encoding problems. Leave `GEMINI_FAST_MODEL` blank to use Flash-Lite for all calls. Keep the other `.env.example` settings unless you have a reason to change them.

On Linux, restrict file access after editing:

```sh
chmod 600 .env
```

## 4. Find your Telegram user ID

The bot must still be stopped. You already sent it `/start` in step 1. From the `ponke` directory:

```powershell
# Windows
docker compose run --rm --no-deps app python scripts/telegram_user_id.py
```

```sh
# Linux
sudo docker compose run --rm --no-deps app python scripts/telegram_user_id.py
```

Copy the printed number into `ALLOWED_TELEGRAM_USER_IDS` in `.env`, for example `ALLOWED_TELEGRAM_USER_IDS=123456789`. If no number appears, send the bot another private message and rerun the command. If Ponke is already running, stop its app container first so it does not consume the update.

## 5. Set up Google Calendar (optional, but required for calendar commands)

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable **Google Calendar API** under **APIs & Services → Library**. You do not need a Google Cloud VM to do this.
2. In **Google Auth Platform**, complete **Branding** with an app name, support email, and contact email.
3. Set **Audience** to **External** for a personal Gmail account. While the app is in **Testing**, add the Google account you will connect as a **test user**. Choose **Internal** only if you are using a Google Workspace organization that owns the project.
4. Under **Data Access**, add the `https://www.googleapis.com/auth/calendar.events` scope.
5. Under **Clients**, create an OAuth client of type **Web application**. Ponke does not use a Desktop OAuth client.
6. Add **one authorized redirect URI** that matches where you will open the authorization link:
   - Local computer or SSH tunnel: `http://localhost:8000/oauth/google/callback`
   - Public HTTPS server: `https://YOUR_DOMAIN/oauth/google/callback`
7. Copy the client ID and client secret to `.env`, and set the exact same URI there:

```dotenv
GOOGLE_CLIENT_ID=YOUR_GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET=YOUR_GOOGLE_CLIENT_SECRET
GOOGLE_REDIRECT_URI=http://localhost:8000/oauth/google/callback
GOOGLE_CALENDAR_ID=primary
```

Use the HTTPS domain instead of `localhost` in the example above if you chose the public option. Google checks the redirect URI exactly, including scheme and trailing slash. A raw server IP is not suitable for Google's public redirect URI rules.

**Testing-mode note:** Google says an External app in Testing can receive refresh tokens that expire after seven days. You may need to send `/connect_calendar` again after they expire. Review [Google's publishing and personal-use rules](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification) before changing the app's publishing status.

## 6. Start Ponke and connect Google

Run this on the machine where you cloned the repository:

```powershell
# Windows
docker compose up -d --build
docker compose ps
docker compose logs --tail 50 app
```

```sh
# Linux
sudo docker compose up -d --build
sudo docker compose ps
sudo docker compose logs --tail 50 app
```

Compose starts PostgreSQL, runs database migrations, and then starts Ponke. On that machine, `http://127.0.0.1:8000/health/ready` should return `{"status":"ready"}`. The database stays inside Docker; port 8000 listens only on the machine's loopback interface.

Send `/start` to your bot again. Then send `/connect_calendar` and open the link Ponke sends. Sign in with the Google account you added as a test user and approve access. The page should say **Google Calendar connected**. The link expires after ten minutes; request another if necessary.

For `localhost` OAuth, open the link in a browser **on the computer running Ponke**. If Ponke runs on a VPS, use the SSH tunnel in step 7 and open the link on your own computer. A phone opening `localhost` will point to the phone itself.

## 7. Optional: run it on a small VPS without buying a domain

1. Create an Ubuntu 24.04 LTS VPS with at least 2 GB RAM and an SSH key. A 4 GB server is more comfortable for Docker builds. Keep its IP address and SSH username.
2. In the provider firewall, allow SSH from your IP. Outbound HTTPS must work for Telegram and Google (and OpenAI only if selected). You do not need public port 8000.
3. Connect: `ssh YOUR_USERNAME@YOUR_SERVER_IP`.
4. Run `sudo apt update` and `sudo apt install -y git python3`. Install Docker Engine with the Compose plugin using the **Install using the apt repository** section of [Docker's Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/). Confirm `sudo docker compose version` and `sudo docker run hello-world` both work.
5. If you tested locally, stop the local app with `docker compose stop app` so only one process polls your Telegram bot. Repeat steps 3 and 4 on the VPS, sending the bot a fresh `/start` before running the ID helper. Configure Google as in step 5, and start the VPS app with the commands in step 6. Keep `GOOGLE_REDIRECT_URI=http://localhost:8000/oauth/google/callback` if using a tunnel. Complete `/connect_calendar` after opening the tunnel below. A fresh VPS installation starts with an empty database; restoring local data requires the [backup and recovery steps](README.md#backups-and-recovery).
6. When ready to authorize Google, run this command in a **separate terminal on your own computer** and leave it open:

```sh
ssh -N -L 8000:127.0.0.1:8000 YOUR_USERNAME@YOUR_SERVER_IP
```

7. On your own computer, open the `/connect_calendar` link in a browser. Google returns to your computer's port 8000, and SSH forwards the callback to Ponke on the VPS. Close the tunnel afterward. Repeat when you need to reconnect Google.

If you want to open the Google link directly on your phone, use a domain pointed at the VPS plus HTTPS. The [README's Caddy example](README.md#deployment-one-small-linux-vps) covers the reverse proxy; [Caddy can obtain HTTPS certificates automatically](https://caddyserver.com/docs/quick-starts/https). Allow inbound ports 80/443, set `GOOGLE_REDIRECT_URI` to the domain callback, and register that exact URI in Google Cloud. No Telegram webhook is needed; the bot uses outbound polling.

## 8. Confirm the features work

1. Send `Remind me in 2 minutes to water the plants.` Verify the notification arrives.
2. Send `Gym tomorrow at 5 PM.` Verify the event appears in your Google Calendar.
3. Send `Spent IDR 48000 on coffee.` Check that Ponke records the correct currency and amount. If you changed `DEFAULT_CURRENCY`, use that currency instead.
4. Send a clear JPEG/PNG receipt. Send it again and cancel the duplicate confirmation.
5. Send `How much did I spend on food this month?` and `Export my finances.`
6. Send `Should I spend IDR 1000000 on a laptop?` to try the decision council. This makes nine model calls and may take over a minute at the configured free-tier pace. Use your chosen currency if different.

For problems, run `docker compose logs --tail 100 app` (or `sudo docker compose logs --tail 100 app` on Linux). Common causes are an incorrect Telegram ID, invalid Gemini key, unavailable model, exhausted free-tier quota, missing Google test user, or a Google redirect URI mismatch. If the bot does not respond, check `docker compose ps` and the readiness URL first.

## 9. Keep it running safely

- Leave Docker running. On a VPS, Compose services have restart policies, so they return after normal restarts.
- Keep only **one** Ponke app instance for a bot token; multiple pollers conflict.
- On a Linux VPS, back up the database from the repository directory with `sudo python3 scripts/backup.py backups/UNIQUE_NAME.dump`. The helper needs Python on the host and Docker access. Encrypt and store a copy off the server; keep `APP_SECRET_KEY` separately.
- Before upgrades, back up, then follow the [README update steps](README.md#deployment-one-small-linux-vps).
- Check Gemini usage and the VPS bill after the first week. Gemini quotas vary by account; Calendar API standard use should remain within the free threshold for a personal bot. [Google publishes the Calendar quota and pricing rules](https://developers.google.com/workspace/calendar/api/guides/quota).

For deeper details, see [README.md](README.md), [DELIVERY.md](DELIVERY.md), and [VERIFICATION.md](VERIFICATION.md).
