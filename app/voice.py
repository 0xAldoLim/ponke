"""Telegram-facing voice. This never changes an action, record, or model decision."""

import re

ANSWER_VOICE = (
    "Write only Ponke's user-facing answer, in one consistent voice. Lead with the answer. "
    "Be concise, sharp, plainspoken, useful and willing to disagree when evidence supports it. "
    "Challenge weak assumptions respectfully; never manufacture criticism or agreement. "
    "Mild dry humor may fit casual topics, but never mock the user; avoid jokes on health, loss or distress. "
    "No cheerleading, corporate phrasing, emojis, motivational slogans, canned headings, "
    "'my take', 'here's why', 'want the full reasoning?', numerical council scores, or specialist labels. "
    "The user understands finance and technology; skip basic definitions unless asked. "
    "For finance, show the evidence and risk briefly. For health, be careful and direct. "
    "For transactions, calendar changes and reminders, acknowledge in one short sentence. "
    "Default to English even for Indonesian topics; use Indonesian when explicitly requested or when "
    "the user's entire request is in Indonesian. "
    "Never imply an action was completed unless supplied data confirms it. Keep uncertainty, "
    "missing evidence, dates, amounts, currencies and safety limits explicit. "
    "Do not claim memory beyond supplied records. "
)


def preference_correction(text: str) -> dict[str, str]:
    """Only clear, stable communication instructions bypass the LLM router."""
    value = text.casefold().strip().rstrip(".! ")
    mapping = {
        "be shorter": {"verbosity": "concise"},
        "keep it short": {"verbosity": "concise"},
        "be more detailed": {"verbosity": "detailed"},
        "use more detail for investment analysis": {"finance_verbosity": "detailed"},
        "stop explaining basic finance terms": {"finance_basics": "skip"},
        "don't joke about health topics": {"health_sarcasm": "off"},
        "do not joke about health topics": {"health_sarcasm": "off"},
        "reply in indonesian": {"language": "id"},
        "speak indonesian": {"language": "id"},
        "reply in english": {"language": "en"},
        "speak english": {"language": "en"},
        "no sarcasm": {"sarcasm": "off"},
    }
    return mapping.get(value, {})


def message_language(text, default):
    value = text.casefold()
    if re.search(r"\b(?:in indonesian|bahasa indonesia|jawab (?:dalam )?bahasa indonesia)\b", value):
        return "id"
    if re.search(r"\b(?:in english|bahasa inggris|jawab (?:dalam )?bahasa inggris)\b", value):
        return "en"
    words = re.findall(r"[a-z]+", value)
    indonesian = {
        "saya",
        "aku",
        "tolong",
        "berapa",
        "apakah",
        "bisa",
        "untuk",
        "yang",
        "dengan",
        "hari",
        "ini",
        "besok",
        "ingatkan",
        "pengeluaran",
        "saham",
    }
    english = {"i", "you", "what", "how", "should", "please", "the", "is", "my", "for", "today", "tomorrow"}
    if len(words) >= 3 and sum(w in indonesian for w in words) >= 2 and not any(w in english for w in words):
        return "id"
    return default


def voice_instruction(settings, preferences=None, domain="general", question=""):
    preferences = preferences or {}
    if not settings.ponke_personality_enabled:
        return "Answer clearly and accurately. Preserve all supplied facts."
    language = message_language(
        question,
        preferences.get("preference.language", settings.user_language or settings.ponke_default_language),
    )
    verbosity = (
        preferences.get("preference.finance_verbosity", settings.ponke_finance_verbosity)
        if domain == "finance"
        else preferences.get("preference.verbosity", settings.ponke_default_verbosity)
    )
    sarcasm = preferences.get("preference.sarcasm", settings.ponke_sarcasm_level)
    if domain == "health" and not settings.ponke_health_sarcasm:
        sarcasm = "off"
    return (
        ANSWER_VOICE
        + f" User preference: language={language}, verbosity={verbosity}, sarcasm={sarcasm}; domain={domain}. "
        + (
            "Do not explain basic finance terms. "
            if preferences.get("preference.finance_basics") == "skip"
            else ""
        )
    )


def localize_fixed_reply(text, language):
    if language != "id":
        return text
    prefixes = (
        ("Logged ", "Tercatat "),
        ("Added task: ", "Tugas ditambahkan: "),
        ("Updated task: ", "Tugas diperbarui: "),
        ("Created project: ", "Proyek dibuat: "),
        ("Reminder saved: ", "Pengingat disimpan: "),
        ("Created: ", "Dibuat: "),
        ("Updated: ", "Diperbarui: "),
        ("Deleted: ", "Dihapus: "),
        ("Statement preview: ", "Pratinjau mutasi: "),
        ("Imported ", "Diimpor "),
    )
    for old, new in prefixes:
        if text.startswith(old):
            return new + text[len(old) :]
    return text


def present_reply(text: str) -> str:
    """Soften known fixed templates while retaining all dynamic values verbatim."""
    prefixes = (
        ("Reminder saved: ", "I'll remind you: "),
        ("Logged ", "Logged "),
        ("Created: ", "Added: "),
        ("Updated: ", "Updated: "),
        ("Deleted: ", "Removed: "),
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

    if text.startswith("GOOD MORNING\n"):
        _, _, dated = text.partition("\n")
        day, separator, rest = dated.partition("\n")
        return "Here's your briefing for " + day + "." + separator + rest
    return text
