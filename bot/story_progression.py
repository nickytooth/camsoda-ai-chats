"""
Story progression — a simple 3-level heat meter for Story mode.

The "Caught" scene runs on a step counter `heat` 0..MAX_HEAT (3 levels x
STEPS_PER_LEVEL steps). Each NON-rude exchange advances the needle by one step;
a rude / insulting message advances nothing (she sets a boundary instead). The
level gates how far she'll go:

    Angry (heat 0-4)  ->  Flirty (heat 5-9)  ->  Hot (heat 10-15, explicit)

There is no cool-down: the needle only ever rises (or holds on a rude turn).
"""

import logging

from bot.memory.db import get_connection

logger = logging.getLogger(__name__)

STEPS_PER_LEVEL = 5
MAX_HEAT = 15  # 3 levels x STEPS_PER_LEVEL

# One quick yes/no classification per story turn. Only a direct insult/abuse
# blocks progress; ordinary (even bland or clumsy) messages count as a step.
RUDE_PROMPT = """In an adult roleplay, a man is talking to a woman. Decide if his LATEST message is RUDE — a direct insult, name-calling, demeaning slur, threat, or genuinely abusive/hostile language aimed at her.

Crude flirting, being forward, awkwardness, or sexual interest is NOT rude. Only hostile/insulting/abusive language is rude.

His message: "{msg}"

Answer with ONLY one word: YES (rude) or NO (not rude)."""


def level_for(heat: int) -> tuple[int, str]:
    """Map a heat value (0..MAX_HEAT) to (level_number 1-3, label)."""
    if heat <= 4:
        return 1, "Angry"
    if heat <= 9:
        return 2, "Flirty"
    return 3, "Hot"


def _state(heat: int) -> dict:
    heat = max(0, min(MAX_HEAT, int(heat)))
    level, label = level_for(heat)
    return {
        "heat": heat,
        "level": level,
        "label": label,
        "max_heat": MAX_HEAT,
        "climax": heat >= MAX_HEAT,
        # explicit content unlocks at the Hot level
        "explicit": heat >= 10,
    }


async def get_heat(user_id: int) -> dict:
    """Return the current heat state {heat, level, label, max_heat, climax, explicit}."""
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT heat FROM story_progress WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        heat = int(row["heat"]) if row and row["heat"] is not None else 0
    finally:
        await conn.close()
    return _state(heat)


async def is_rude(user_msg: str, llm_call) -> bool:
    """One fast classification: is his message a direct insult/abuse? On any
    error, default to False (treat as not rude) so progress never wrongly stalls."""
    if not (user_msg or "").strip():
        return False
    try:
        out = (await llm_call(RUDE_PROMPT.format(msg=user_msg[:500]))).strip().lower()
        return out.startswith("y")
    except Exception as e:
        logger.warning("Story rude-check failed: %s", e)
        return False


async def record_step(user_id: int, rude: bool) -> dict:
    """Advance the needle by one step unless the turn was rude, persist, and
    return the new heat state. Never decreases; caps at MAX_HEAT."""
    current = await get_heat(user_id)
    heat = current["heat"]
    if not rude:
        heat = min(MAX_HEAT, heat + 1)

    conn = await get_connection()
    try:
        await conn.execute(
            """
            INSERT INTO story_progress (user_id, chapter, scene, heat)
            VALUES (?, 1, 0, ?)
            ON CONFLICT(user_id) DO UPDATE SET heat = ?
            """,
            (user_id, heat, heat),
        )
        await conn.commit()
    finally:
        await conn.close()

    state = _state(heat)
    logger.info(
        "Story heat user %d: %d/%d (%s)%s",
        user_id, heat, MAX_HEAT, state["label"], " [rude, held]" if rude else "",
    )
    return state
