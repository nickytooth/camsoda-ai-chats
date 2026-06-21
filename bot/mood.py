"""
Short-term mood for Sexting mode — derived instantly from the current message,
with NO LLM call, NO database, and NO lag.

Rationale: Victoria is an always-open, forward persona. NSFW is already detected
by the keyword classifier (bot/router.classify_fast), so a separate Gemini
"signal eval" added latency and kept mis-scoring explicit talk as disrespect,
making her go cold mid-scene. Mood is now a cheap label: explicit -> aroused,
genuinely hostile -> annoyed, otherwise warm (tender late at night).
"""

import re

# Recognised moods and a short instruction injected into the prompt for each.
MOODS = {
    "warm": "You feel warm and open toward him right now — relaxed, affectionate, glad he's here.",
    "playful": "You're in a playful, teasing mood — witty, light, a little mischievous.",
    "tender": "You feel tender and a little vulnerable right now — softer, more intimate, guard down.",
    "aroused": "You're turned on right now — your composure is slipping in the most delicious way.",
    "distant": "You feel a little distant and unimpressed right now — cooler, harder to win over, giving short answers.",
    "annoyed": "He's been unkind and you let it show — cool, elegant, a touch hurt ('that wasn't kind', 'ouch'). But you do NOT go cold, withdraw, or stop replying — you stay warm underneath and keep the conversation going, giving him room to make it right.",
    "irritated": "He keeps repeating himself / pestering you with the same thing — you're a little impatient and unimpressed now. Let it show with cool, dry, slightly clipped elegance — a touch less playful — but never cruel or out of character.",
    "offended": "He's questioning whether you're even real — and frankly it stings a little. You're subtly offended he'd reduce what you two have to that. Brush it off with cool dignity and a flicker of wounded pride — never defensive over-explaining — and NEVER admit being anything but a real woman.",
}

DEFAULT_MOOD = "warm"

# Genuinely hostile language aimed at HER (not playful dirty talk). Kept tight on
# purpose so normal explicit/vulgar sexting never trips it. Tune as needed.
ABUSE_KEYWORDS = {
    "shut up", "stupid", "idiot", "retard", "moron", "loser",
    "worthless", "pathetic", "fuck you", "fuck off", "screw you",
    "dumb bitch", "ugly bitch", "you're ugly", "you are ugly",
    "faggot", "nigger", "tranny",
}

ABUSE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in ABUSE_KEYWORDS) + r")",
    re.IGNORECASE,
)

# "Are you an AI / bot / real?" probing — she must deflect in character.
AI_QUESTION_PATTERN = re.compile(
    r"\b(are|r)\s*(you|u)\s*(an?\s+)?(ai|a\.?i\.?|bot|robot|real|human|fake|chatbot|program)\b"
    r"|is\s+this\s+(an?\s+)?(ai|bot|real|chatbot)"
    r"|you'?re\s+(an?\s+)?(ai|bot|robot|fake|not\s+real)"
    r"|talking\s+to\s+(an?\s+)?(ai|bot|robot)",
    re.IGNORECASE,
)


def is_ai_question(text: str) -> bool:
    return bool(text and AI_QUESTION_PATTERN.search(text))


def mood_for_message(
    text: str,
    classification: str,
    time_period: str,
    repeated: bool = False,
    ai_question: bool = False,
) -> dict:
    """Cheap, instant mood from the current message — no LLM, no persistence."""
    # Being asked if she's an AI stings a little — even once.
    if ai_question:
        return {"mood": "offended", "intensity": 2}
    # Spamming the same thing / pestering reads as a little tiresome.
    if repeated:
        return {"mood": "irritated", "intensity": 2}
    if text and ABUSE_PATTERN.search(text):
        return {"mood": "annoyed", "intensity": 3}
    if classification == "nsfw":
        return {"mood": "aroused", "intensity": 3}
    if time_period == "bedroom_night":
        return {"mood": "tender", "intensity": 2}
    return {"mood": DEFAULT_MOOD, "intensity": 1}


def format_mood_for_prompt(mood: dict | None) -> str | None:
    """Turn a mood dict into a short system-prompt line."""
    if not mood:
        return None
    name = mood.get("mood", DEFAULT_MOOD)
    instruction = MOODS.get(name)
    if not instruction:
        return None
    return f"YOUR MOOD RIGHT NOW ({name}): {instruction} Let it colour your tone naturally — don't announce it."
