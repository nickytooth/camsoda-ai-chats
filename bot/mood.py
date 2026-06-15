"""
Short-term mood state for Sexting mode.

Separate from the intimacy *stage* (which is the slow, never-going-backwards
relationship progression). Mood is the fast, volatile emotional colour that
shifts turn-to-turn based on how the user is treating Victoria right now.

Mood is derived (cheaply, no extra LLM call) from the per-message signals that
the intimacy evaluator already produces, plus the SFW/NSFW classification and
the current time-of-day.
"""

import logging
import time
from bot.memory.db import get_connection

logger = logging.getLogger(__name__)

# Recognised moods and a short instruction injected into the prompt for each.
MOODS = {
    "warm": "You feel warm and open toward him right now — relaxed, affectionate, glad he's here.",
    "playful": "You're in a playful, teasing mood — witty, light, a little mischievous.",
    "tender": "You feel tender and a little vulnerable right now — softer, more intimate, guard down.",
    "aroused": "You're turned on right now — your composure is slipping in the most delicious way.",
    "distant": "You feel a little distant and unimpressed right now — cooler, harder to win over, giving short answers.",
    "annoyed": "You're mildly annoyed with him right now — you don't hide it, but you stay elegant. He has to earn his way back.",
}

DEFAULT_MOOD = "warm"

# How long a mood "sticks" before it naturally drifts back toward neutral warmth.
MOOD_DECAY_SECONDS = 1800  # 30 min


async def _ensure_table():
    conn = await get_connection()
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mood_state (
                user_id INTEGER PRIMARY KEY,
                mood TEXT NOT NULL DEFAULT 'warm',
                intensity INTEGER NOT NULL DEFAULT 1,
                updated_at REAL NOT NULL DEFAULT 0
            )
            """
        )
        await conn.commit()
    finally:
        await conn.close()


async def get_mood(user_id: int) -> dict:
    """Return the user's current mood, decaying toward warm if it's gone stale."""
    await _ensure_table()
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT mood, intensity, updated_at FROM mood_state WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
    finally:
        await conn.close()

    if not row:
        return {"mood": DEFAULT_MOOD, "intensity": 1}

    mood = row["mood"]
    intensity = row["intensity"]
    age = time.time() - (row["updated_at"] or 0)

    # Stale mood drifts back to gentle warmth.
    if age > MOOD_DECAY_SECONDS:
        return {"mood": DEFAULT_MOOD, "intensity": 1}

    return {"mood": mood, "intensity": intensity}


def _derive_mood(signals: dict, classification: str, time_period: str) -> tuple[str, int]:
    """Pure logic: map per-message signals + context to a (mood, intensity) pair."""
    charm = signals.get("charm", 0)
    respect = signals.get("respect", 0)
    humor = signals.get("humor", 0)
    vulgarity = signals.get("vulgarity", 0)
    pushing = signals.get("pushing", 0)

    # Negative behaviour dominates — she cools off or gets annoyed.
    if respect <= -3 or vulgarity <= -5:
        return "annoyed", 3
    if pushing <= -3 or vulgarity <= -2 or respect <= -1:
        return "distant", 2

    # Genuine heat — she's always open, so explicit talk turns her on.
    if classification == "nsfw":
        return "aroused", 3

    # Late night + decent behaviour → her softer, lonelier side.
    if time_period in ("late_night", "night") and charm >= 1:
        return "tender", 2

    # Fun, clever energy.
    if humor >= 2 or charm >= 3:
        return "playful", 2

    # Polite, pleasant exchange.
    if charm >= 1 and respect >= 0:
        return "warm", 1

    # Bland / low-effort messages bore her a little.
    if charm <= 0 and humor <= 0:
        return "distant", 1

    return DEFAULT_MOOD, 1


async def update_mood(
    user_id: int,
    signals: dict,
    classification: str,
    time_period: str,
) -> dict:
    """Recompute and persist the user's mood from the latest message signals."""
    await _ensure_table()
    mood, intensity = _derive_mood(signals or {}, classification, time_period)

    conn = await get_connection()
    try:
        await conn.execute(
            """
            INSERT INTO mood_state (user_id, mood, intensity, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                mood = ?, intensity = ?, updated_at = ?
            """,
            (user_id, mood, intensity, time.time(), mood, intensity, time.time()),
        )
        await conn.commit()
    finally:
        await conn.close()

    logger.info("Mood for user %d: %s (intensity %d)", user_id, mood, intensity)
    return {"mood": mood, "intensity": intensity}


def format_mood_for_prompt(mood: dict | None) -> str | None:
    """Turn a mood dict into a short system-prompt line."""
    if not mood:
        return None
    name = mood.get("mood", DEFAULT_MOOD)
    instruction = MOODS.get(name)
    if not instruction:
        return None
    return f"YOUR MOOD RIGHT NOW ({name}): {instruction} Let it colour your tone naturally — don't announce it."
