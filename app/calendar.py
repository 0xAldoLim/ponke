import base64
import hashlib
import json
import secrets
from datetime import timedelta
from urllib.parse import quote, urlencode

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.database import OAuthState, OAuthToken, utcnow
from app.validation import Clarification, aware

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/calendar.events"


class GoogleCalendar:
    def __init__(self, settings, sessions, client=None):
        self.settings, self.sessions = settings, sessions
        self.cipher = Fernet(settings.app_secret_key.get_secret_value().encode())
        self.http = client or httpx.AsyncClient(timeout=20)

    async def connect_url(self, user_id):
        if not self.settings.google_client_id or not self.settings.google_client_secret.get_secret_value():
            raise Clarification("Google Calendar needs its client ID and secret configured first.")
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        async with self.sessions.begin() as db:
            db.add(
                OAuthState(
                    user_id=user_id,
                    digest=hashlib.sha256(state.encode()).hexdigest(),
                    verifier_encrypted=self.cipher.encrypt(verifier.encode()).decode(),
                    expires_at=utcnow() + timedelta(minutes=10),
                )
            )
        return (
            AUTH_URL
            + "?"
            + urlencode(
                dict(
                    client_id=self.settings.google_client_id,
                    redirect_uri=self.settings.google_redirect_uri,
                    response_type="code",
                    scope=SCOPE,
                    access_type="offline",
                    prompt="consent",
                    state=state,
                    code_challenge=challenge,
                    code_challenge_method="S256",
                )
            )
        )

    async def callback(self, state, code):
        async with self.sessions.begin() as db:
            record = await db.scalar(
                select(OAuthState)
                .where(OAuthState.digest == hashlib.sha256(state.encode()).hexdigest())
                .with_for_update()
            )
            if (
                not record
                or aware(record.expires_at) < utcnow()
                or record.user_id not in self.settings.allowed_ids
            ):
                raise Clarification(
                    "This authorization link expired or was already used. Request a new one in Telegram."
                )
            user_id = record.user_id
            verifier = self.cipher.decrypt(record.verifier_encrypted.encode()).decode()
            await db.delete(record)
        response = await self.http.post(
            TOKEN_URL,
            data={
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret.get_secret_value(),
                "redirect_uri": self.settings.google_redirect_uri,
                "code": code,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )
        response.raise_for_status()
        data = response.json()
        if "access_token" not in data:
            raise Clarification("Google did not return an access token. Please reconnect.")
        data["expires_at"] = (utcnow() + timedelta(seconds=data.get("expires_in", 3600))).isoformat()
        async with self.sessions.begin() as db:
            token = await db.scalar(select(OAuthToken).where(OAuthToken.user_id == user_id))
            if token:
                previous = json.loads(self.cipher.decrypt(token.encrypted.encode()))
                data.setdefault("refresh_token", previous.get("refresh_token"))
            else:
                token = OAuthToken(user_id=user_id)
                db.add(token)
            token.encrypted = self.cipher.encrypt(json.dumps(data).encode()).decode()

    async def access_token(self, user_id):
        from datetime import datetime

        async with self.sessions.begin() as db:
            token = await db.scalar(select(OAuthToken).where(OAuthToken.user_id == user_id).with_for_update())
            if not token:
                raise Clarification("Connect Google Calendar first: send /connect_calendar.")
            data = json.loads(self.cipher.decrypt(token.encrypted.encode()))
            if datetime.fromisoformat(data["expires_at"]) < utcnow() + timedelta(minutes=2):
                if not data.get("refresh_token"):
                    raise Clarification("Google authorization expired. Send /connect_calendar again.")
                response = await self.http.post(
                    TOKEN_URL,
                    data={
                        "client_id": self.settings.google_client_id,
                        "client_secret": self.settings.google_client_secret.get_secret_value(),
                        "refresh_token": data["refresh_token"],
                        "grant_type": "refresh_token",
                    },
                )
                if response.status_code == 400:
                    raise Clarification(
                        "Google authorization expired or was revoked. Send /connect_calendar again."
                    )
                response.raise_for_status()
                data.update(response.json())
                data["expires_at"] = (utcnow() + timedelta(seconds=data.get("expires_in", 3600))).isoformat()
                token.encrypted = self.cipher.encrypt(json.dumps(data).encode()).decode()
            return data["access_token"]

    async def request(self, user_id, method, path="", **kwargs):
        token = await self.access_token(user_id)
        url = (
            "https://www.googleapis.com/calendar/v3/calendars/"
            + quote(self.settings.google_calendar_id, safe="")
            + "/events"
            + path
        )
        response = await self.http.request(
            method, url, headers={"Authorization": "Bearer " + token}, **kwargs
        )
        if response.status_code == 409 and method == "POST":
            # Caller-generated stable event ID makes create retries safe.
            return await self.request(user_id, "GET", "/" + kwargs["json"]["id"])
        if response.status_code == 410 and method == "DELETE":
            return {}
        response.raise_for_status()
        return response.json() if response.content else {}

    async def get_events(self, user_id, start, end, search=None):
        params = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 250,
            "timeZone": self.settings.user_timezone,
        }
        if search:
            params["q"] = search
        events = []
        for _ in range(20):
            data = await self.request(user_id, "GET", params=params)
            events.extend(data.get("items", []))
            if not data.get("nextPageToken"):
                return events
            params["pageToken"] = data["nextPageToken"]
        raise Clarification("That calendar range has too many events. Please use a shorter range.")

    async def get_event(self, user_id, event_id):
        return await self.request(user_id, "GET", "/" + quote(event_id, safe=""))

    async def create_event(self, user_id, title, start, end, operation_id):
        return await self.request(
            user_id,
            "POST",
            json={
                "id": hashlib.sha256(f"{user_id}:{operation_id}".encode()).hexdigest(),
                "summary": title,
                "start": {"dateTime": start.isoformat(), "timeZone": self.settings.user_timezone},
                "end": {"dateTime": end.isoformat(), "timeZone": self.settings.user_timezone},
            },
        )

    async def update_event(self, user_id, event_id, title, start, end, etag):
        # Preflight fetched again by service; use If-Match to reject concurrent changes.
        token = await self.access_token(user_id)
        url = (
            "https://www.googleapis.com/calendar/v3/calendars/"
            + quote(self.settings.google_calendar_id, safe="")
            + "/events/"
            + quote(event_id, safe="")
        )
        body = {"start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}}
        if title:
            body["summary"] = title
        response = await self.http.patch(
            url, headers={"Authorization": "Bearer " + token, "If-Match": etag}, json=body
        )
        response.raise_for_status()
        return response.json()

    async def delete_event(self, user_id, event_id):
        await self.request(user_id, "DELETE", "/" + quote(event_id, safe=""))

    async def close(self):
        await self.http.aclose()
