import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import SecretStr
from sqlalchemy import select

from app.calendar import GoogleCalendar
from app.database import OAuthState, OAuthToken
from app.llm import OpenAIModel
from app.schemas import Answer
from app.validation import Clarification


async def test_google_oauth_pkce_encryption_refresh_and_replay(env):
    settings, sessions, _, _, _ = env
    settings.google_client_id = "client-id"
    settings.google_client_secret = SecretStr("client-secret")
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "private-access-token",
                "refresh_token": "private-refresh-token",
                "expires_in": 0,
            },
        )

    calendar = GoogleCalendar(settings, sessions, httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    query = parse_qs(urlparse(await calendar.connect_url(123)).query)
    assert query["code_challenge_method"] == ["S256"]
    await calendar.callback(query["state"][0], "authorization-code")
    async with sessions() as db:
        token = await db.scalar(select(OAuthToken))
        assert (
            "private-access-token" not in token.encrypted and "private-refresh-token" not in token.encrypted
        )
        assert await db.scalar(select(OAuthState)) is None
    with pytest.raises(Clarification):
        await calendar.callback(query["state"][0], "authorization-code")
    assert await calendar.access_token(123) == "private-access-token"
    assert len(calls) == 2
    await calendar.close()


async def test_google_create_idempotency_and_pagination(env, future):
    settings, sessions, _, _, _ = env
    calls = []

    def transport(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(409, json={"error": "exists"})
        if request.url.path.endswith("/events"):
            if "pageToken" not in request.url.params:
                return httpx.Response(200, json={"items": [{"id": "one"}], "nextPageToken": "next"})
            return httpx.Response(200, json={"items": [{"id": "two"}]})
        return httpx.Response(200, json={"id": "stable-existing-event"})

    calendar = GoogleCalendar(settings, sessions, httpx.AsyncClient(transport=httpx.MockTransport(transport)))

    async def token(user_id):
        return "test-token"

    calendar.access_token = token
    result = await calendar.create_event(123, "Gym", future, future + timedelta(hours=1), "source")
    assert result["id"] == "stable-existing-event"
    events = await calendar.get_events(123, future, future + timedelta(days=1))
    assert [e["id"] for e in events] == ["one", "two"]
    assert all(r.headers["Authorization"] == "Bearer test-token" for r in calls)
    assert calls[-1].url.params["timeZone"] == "Asia/Jakarta"
    await calendar.close()


async def test_google_unconnected_user(env):
    settings, sessions, _, _, _ = env
    calendar = GoogleCalendar(settings, sessions)
    with pytest.raises(Clarification, match="Connect Google"):
        await calendar.access_token(123)
    await calendar.close()


async def test_real_sdk_structured_request_and_response(env):
    settings, _, _, _, _ = env
    captured = []

    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": settings.openai_primary_model,
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": '{"text":"Hello"}', "annotations": []}],
                    }
                ],
                "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            },
        )

    model = OpenAIModel(settings)
    await model.client.close()
    model.client = AsyncOpenAI(
        api_key="test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    )
    result = await model.structured(Answer, "Be concise.", {"user": "hello"})
    assert result.text == "Hello"
    body = captured[0]
    assert body["store"] is False and body["model"] == "gpt-6-astra"
    assert body["text"]["format"]["type"] == "json_schema" and body["text"]["format"]["strict"] is True
    assert "DATA" in body["instructions"]
    await model.close()


async def test_model_refusal_does_not_execute(env):
    settings, _, _, _, _ = env
    model = OpenAIModel(settings)
    await model.client.close()
    model.client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=AsyncMock(return_value=SimpleNamespace(usage=None, output_parsed=None))
        )
    )
    with pytest.raises(Clarification):
        await model.structured(Answer, "test", {})
