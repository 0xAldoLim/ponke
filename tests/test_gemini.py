import base64
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from app.llm import GeminiModel, OpenAIModel, create_model
from app.schemas import Answer, IntentResult
from app.validation import Clarification


async def test_gemini_structured_text_and_image_request(env):
    settings, _, _, _, _ = env
    settings.ai_provider = "gemini"
    settings.gemini_api_key = SecretStr("test-gemini-key")
    captured = []

    def respond(request):
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "steps": [
                    {"type": "model_output", "content": [{"type": "text", "text": '{"text":"Hello"}'}]}
                ],
                "usage": {"total_input_tokens": 10, "total_output_tokens": 3},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    model = GeminiModel(settings, client)
    result = await model.structured(Answer, "Be concise.", {"user": "hello"}, image=b"jpeg-bytes")
    assert result.text == "Hello"
    assert len(captured) == 1
    request = captured[0]
    assert request.url == GeminiModel.API_URL
    assert request.headers["x-goog-api-key"] == "test-gemini-key"
    body = json.loads(request.content)
    assert body["model"] == "gemini-3.5-flash-lite"
    assert body["store"] is False
    assert "DATA" in body["system_instruction"] and "Be concise." in body["system_instruction"]
    assert json.loads(body["input"][0]["text"]) == {"user": "hello"}
    assert body["input"][1] == {
        "type": "image",
        "mime_type": "image/jpeg",
        "data": base64.b64encode(b"jpeg-bytes").decode(),
    }
    assert body["response_format"]["mime_type"] == "application/json"
    assert body["response_format"]["schema"]["properties"]["text"]["type"] == "string"
    await model.close()


async def test_gemini_rejects_incomplete_or_invalid_output(env):
    settings, _, _, _, _ = env
    settings.gemini_api_key = SecretStr("fake")

    for payload in (
        {"status": "failed", "steps": []},
        {"status": "completed", "steps": []},
        {
            "status": "completed",
            "steps": [{"type": "model_output", "content": [{"type": "text", "text": "{}"}]}],
        },
    ):

        def respond(request, result=payload):
            return httpx.Response(200, json=result)

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        model = GeminiModel(settings, client)
        with pytest.raises(Clarification, match="valid answer"):
            await model.structured(Answer, "test", {})
        await model.close()


async def test_gemini_retries_temporary_limit(env):
    settings, _, _, _, _ = env
    settings.gemini_api_key = SecretStr("fake")
    calls = 0

    def respond(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "steps": [
                    {"type": "model_output", "content": [{"type": "text", "text": '{"text":"Ready"}'}]}
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    model = GeminiModel(settings, client)
    model._pace = AsyncMock()
    assert (await model.structured(Answer, "test", {})).text == "Ready"
    assert calls == 2
    await model.close()


def test_gemini_schema_and_provider_selection(env):
    settings, _, _, _, _ = env
    settings.ai_provider = "gemini"
    settings.gemini_api_key = SecretStr("fake")
    model = create_model(settings)
    assert isinstance(model, GeminiModel)
    schema = IntentResult.model_json_schema()
    from app.llm import gemini_schema

    cleaned = gemini_schema(schema)
    assert "$defs" in cleaned and "Entities" in cleaned["$defs"]
    assert "default" not in json.dumps(cleaned)
    settings.ai_provider = "openai"
    assert isinstance(create_model(settings), OpenAIModel)
