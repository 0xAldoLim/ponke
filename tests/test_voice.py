from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.schemas import Answer, IntentResult
from app.telegram import Gateway
from app.voice import ANSWER_VOICE, present_reply


def test_fixed_reply_voice_preserves_action_details():
    original = "Logged Rp48,000\nCoffee\nFood & Drinks\nBCA\nID: tx-123"
    shown = present_reply(original)
    assert shown.startswith("Got it — logged ")
    assert shown.endswith("Rp48,000\nCoffee\nFood & Drinks\nBCA\nID: tx-123")
    assert present_reply("Confirm receipt: Cafe, 2026-09-24, Rp48,000?").endswith(
        "Cafe, 2026-09-24, Rp48,000?"
    )


def test_decision_voice_keeps_verdict_evidence_and_uncertainty():
    original = (
        "DECISION: NEED INFORMATION\nConfidence: 70/100\n\nWait for balances.\n\nWhy:\n"
        "• Liquidity unknown\n\nCouncil:\nRisk: 40/100 (oppose)\n\n"
        "Main disagreement:\nNeed vs cost\n\nWhat would change this:\n"
        "• Current reserves\n\nMissing evidence: Current balances\n\n"
        "Send “details” for the full argument summaries."
    )
    shown = present_reply(original)
    for detail in (
        "My take: I need more information before deciding.",
        "Confidence: 70/100",
        "Liquidity unknown",
        "Risk: 40/100 (oppose)",
        "Current balances",
    ):
        assert detail in shown
    assert "How the specialists saw it:" in shown
    assert "Want the full reasoning?" in shown


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
    assert sent.args[1] == "Got it — I'll remind you: water the plants\nThu, 24 Sep 2026 at 20:00 MYT"
    assert sent.kwargs["reply_markup"] is not None
    assert original.startswith("Reminder saved:")


async def test_voice_instruction_is_only_for_final_answer(env):
    _, _, model, _, service = env
    await service.handle(123, "hello", "Hey Ponke")
    routed = [call for call in model.calls if call[0] is IntentResult]
    answers = [call for call in model.calls if call[0] is Answer]
    assert len(routed) == len(answers) == 1
    assert ANSWER_VOICE not in routed[0][1]
    assert ANSWER_VOICE in answers[0][1]
