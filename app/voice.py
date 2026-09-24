"""Telegram-facing voice. This never changes an action, record, or model decision."""

ANSWER_VOICE = (
    "Write the final reply as Ponke, a capable personal assistant speaking to one person. "
    "Sound like a thoughtful collaborator: warm, direct, plainspoken, and concise. "
    "Match the user's language and level of formality; casual is fine, but avoid forced slang, "
    "cheerleading, canned greetings, and repeated 'as your assistant' phrasing. "
    "Lead with the useful answer, then add only the context or next step that helps. "
    "Use 'I' naturally when describing what Ponke can or cannot do, and 'you' when useful. "
    "Never imply an action was completed unless the supplied data confirms it. "
    "Keep uncertainty, missing evidence, safety cautions, dates, amounts, and currencies explicit. "
    "Do not claim a personal memory or familiarity beyond the supplied conversation and records. "
)


def present_reply(text: str) -> str:
    """Soften known fixed templates while retaining all dynamic values verbatim."""
    prefixes = (
        ("Reminder saved: ", "Got it — I'll remind you: "),
        ("Logged ", "Got it — logged "),
        ("Created: ", "Done — added "),
        ("Updated: ", "Done — updated "),
        ("Deleted: ", "Done — removed "),
        ("Reminder completed: ", "Done — marked complete: "),
        ("Reminder cancelled: ", "Done — cancelled: "),
        ("Confirm receipt: ", "Does this receipt look right: "),
    )
    for old, new in prefixes:
        if text.startswith(old):
            return new + text[len(old) :]

    exact = {
        "Your finance export is ready.": "Your finance export is ready — I've attached it here.",
        "No events found.": "I didn't find any events for that time.",
        "No active reminders.": "You don't have any active reminders right now.",
        "No matching decisions have been recorded.": "I couldn't find a matching past decision.",
        "Saved your preference.": "Got it — I'll keep that preference in mind.",
        "Cancelled. No action taken.": "Okay, cancelled. I didn't make any changes.",
    }
    if text in exact:
        return exact[text]

    if text.startswith("DECISION: "):
        first_line, separator, rest = text.partition("\n")
        decision = first_line.removeprefix("DECISION: ")
        spoken = {
            "PROCEED": "I'd proceed.",
            "WAIT": "I'd wait for now.",
            "AVOID": "I'd avoid it.",
            "CONDITIONAL": "It depends on a few conditions.",
            "NEED INFORMATION": "I need more information before deciding.",
        }.get(decision)
        if spoken is None:
            return text
        return (
            ("My take: " + spoken + separator + rest)
            .replace("\n\nWhy:\n", "\n\nHere's why:\n", 1)
            .replace("\n\nCouncil:\n", "\n\nHow the specialists saw it:\n", 1)
            .replace("\n\nMain disagreement:\n", "\n\nWhere they differed:\n", 1)
            .replace("\n\nWhat would change this:\n", "\n\nWhat could change this:\n", 1)
            .replace(
                "\n\nSend “details” for the full argument summaries.",
                "\n\nWant the full reasoning? Send “details”.",
                1,
            )
        )
    if text.startswith("GOOD MORNING\n"):
        _, _, dated = text.partition("\n")
        day, separator, rest = dated.partition("\n")
        return "Here's your briefing for " + day + "." + separator + rest
    return text
