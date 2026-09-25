import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.council import render_verdict
from app.schemas import Answer, IntentResult
from app.telegram import Gateway
from app.voice import ANSWER_VOICE, present_reply


def test_fixed_reply_voice_preserves_action_details():
    original = "Logged Rp48,000\nCoffee\nFood & Drinks\nBCA\nID: tx-123"
    shown = present_reply(original)
    assert shown.startswith("Logged ")
    assert shown.endswith("Rp48,000\nCoffee\nFood & Drinks\nBCA\nID: tx-123")
    assert present_reply("Confirm receipt: Cafe, 2026-09-24, Rp48,000?").endswith(
        "Cafe, 2026-09-24, Rp48,000?"
    )


def test_decision_reply_is_concise_without_scores_or_canned_headings():
    verdict = {
        "decision_type": "investment",
        "decision": "NEED INFORMATION",
        "confidence": 50,
        "weights": {"macro": 50, "risk": 50, "lifestyle": 0, "health": 0},
        "relevance_explanation": "Only investment views are relevant.",
        "recommended_action": "I wouldn't commit money to crypto yet.",
        "common_ground": "Both views agree that volatility makes position size important.",
        "reasons": ["Volatility is high"],
        "facts": [],
        "assumptions": [],
        "main_disagreement": "The upside case is plausible, but the risk case stresses drawdowns.",
        "missing_evidence": ["your time horizon"],
        "what_would_change": [],
    }
    shown = present_reply(render_verdict(verdict))
    assert "I wouldn't commit money to crypto yet." in shown
    assert "Both views agree" in shown
    assert "upside case" in shown
    assert "your time horizon" in shown
    assert all(
        phrase not in shown for phrase in ("50/100", "My take:", "Here's why:", "Council:", "Send “details”")
    )


def test_historic_decision_without_new_field_still_renders():
    old = {
        "decision_type": "purchase",
        "decision": "WAIT",
        "confidence": 50,
        "weights": {"macro": 0, "risk": 50, "lifestyle": 50, "health": 0},
        "relevance_explanation": "Old format",
        "recommended_action": "Wait until your cash buffer is clear.",
        "reasons": ["Reserves unknown"],
        "facts": [],
        "assumptions": [],
        "main_disagreement": "The upgrade is useful, but it may strain cash.",
        "missing_evidence": ["Current balance"],
        "what_would_change": [],
    }
    shown = render_verdict(old)
    assert "Wait until your cash buffer is clear." in shown
    assert "upgrade is useful" in shown
    assert "/100" not in shown


def test_briefing_voice_keeps_date_and_report():
    original = "GOOD MORNING\nThursday, 24 September\n\nFINANCE\nYesterday: Rp48,000"
    assert present_reply(original) == (
        "Here's your briefing for Thursday, 24 September.\n\nFINANCE\nYesterday: Rp48,000"
    )


async def test_gateway_changes_only_delivered_text(env):
    settings, _, _, _, service = env
    gateway = Gateway(settings, service)
    bot = SimpleNamespace(send_message=AsyncMock())
    gateway.application = SimpleNamespace(bot=bot)
    original = "Reminder saved: water the plants\nThu, 24 Sep 2026 at 20:00 MYT"
    await gateway.send(123, original, reminder_id="abc123")
    sent = bot.send_message.call_args
    assert sent.args[1] == "I'll remind you: water the plants\nThu, 24 Sep 2026 at 20:00 MYT"
    assert sent.kwargs["reply_markup"] is not None
    assert original.startswith("Reminder saved:")


async def test_long_request_shows_typing_and_one_progress_message(env):
    settings, _, _, _, service = env
    gateway = Gateway(settings, service)
    bot = SimpleNamespace(send_message=AsyncMock(), send_chat_action=AsyncMock())
    gateway.application = SimpleNamespace(bot=bot)
    sleeps = 0

    async def tick(_):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 4:
            raise asyncio.CancelledError

    with patch("app.telegram.asyncio.sleep", new=tick), pytest.raises(asyncio.CancelledError):
        await gateway.show_progress(123)
    assert bot.send_chat_action.await_count == 4
    bot.send_message.assert_awaited_once_with(
        123, "I'm still working on this. Give me a moment.", reply_markup=None
    )


async def test_voice_instruction_is_only_for_final_answer(env):
    _, _, model, _, service = env
    await service.handle(123, "hello", "Hey Ponke")
    routed = [call for call in model.calls if call[0] is IntentResult]
    answers = [call for call in model.calls if call[0] is Answer]
    assert len(routed) == len(answers) == 1
    assert ANSWER_VOICE not in routed[0][1]
    assert ANSWER_VOICE in answers[0][1]
