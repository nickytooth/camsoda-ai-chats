"""
Story progression — a smooth 13-phase heat gradient for Story mode.

The "Caught" scene runs on a raw step counter (stored in `scene`); the displayed
phase is `heat = scene // STEPS_PER_PHASE`, where each `heat` value maps 1:1 to a
phase defined in stories/victoria_story.yaml (`stages`). Each NON-rude exchange
advances the raw counter by one, so every phase is held for STEPS_PER_PHASE
exchanges before the needle moves; a rude / insulting message advances nothing
(she sets a boundary instead). The active phase's `behavior` gates how far she'll
go, and its `zone` (angry/flirty/hot) only colours the gauge.

There is no cool-down: the needle only ever rises (or holds on a rude turn).
The phases are the single source of truth in the YAML — add/remove entries
there and MAX_HEAT follows automatically.
"""

import logging
from pathlib import Path

import yaml

from bot.config import STORY_FILE
from bot.memory.db import get_connection

logger = logging.getLogger(__name__)

# Maps a phase `zone` to the 1-3 gauge level the frontend uses for colour.
_ZONE_LEVEL = {"angry": 1, "flirty": 2, "hot": 3}
_FALLBACK_MAX_HEAT = 12  # used only if the story file can't be read
STEPS_PER_PHASE = 2  # non-rude exchanges required to advance one phase

# One quick yes/no classification per story turn. Only a direct insult/abuse
# blocks progress; ordinary (even bland or clumsy) messages count as a step.
RUDE_PROMPT = """In an adult roleplay, a man is talking to a woman. Decide if his LATEST message is RUDE — a direct insult, name-calling, demeaning slur, threat, or genuinely abusive/hostile language aimed at her.

Crude flirting, being forward, awkwardness, or sexual interest is NOT rude. Only hostile/insulting/abusive language is rude.

His message: "{msg}"

Answer with ONLY one word: YES (rude) or NO (not rude)."""


def _load_stages() -> list[dict]:
    """Load the phase list from the story YAML. Read fresh each call so edits to
    the file take effect without a restart (mirrors prompt_builder._load_story)."""
    try:
        path = Path(STORY_FILE)
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("stages", []) or []
    except Exception as e:
        logger.warning("Failed to load story stages: %s", e)
        return []


def _max_heat(stages: list[dict] | None = None) -> int:
    stages = _load_stages() if stages is None else stages
    return (len(stages) - 1) if stages else _FALLBACK_MAX_HEAT


def _state(heat: int) -> dict:
    stages = _load_stages()
    max_heat = _max_heat(stages)
    heat = max(0, min(max_heat, int(heat)))

    if stages:
        stage = stages[heat]
        label = stage.get("label", "")
        zone = stage.get("zone", "angry")
        level = _ZONE_LEVEL.get(zone, 1)
        explicit = bool(stage.get("explicit", False))
        climax = bool(stage.get("climax", False)) or heat >= max_heat
    else:
        label, level, explicit, climax = "", 1, False, heat >= max_heat

    return {
        "heat": heat,
        "stage": heat + 1,          # 1-indexed phase number for the gauge
        "level": level,             # 1-3 zone, drives the gauge colour
        "label": label,
        "max_heat": max_heat,
        "climax": climax,
        "explicit": explicit,
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
    """Advance the raw step counter by one unless the turn was rude, derive the
    phase (one phase per STEPS_PER_PHASE steps), persist, and return the new heat
    state. Never decreases; caps at MAX_HEAT."""
    max_heat = _max_heat()
    max_step = (max_heat + 1) * STEPS_PER_PHASE

    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT scene, heat FROM story_progress WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        step = int(row["scene"]) if row and row["scene"] is not None else 0
        # Legacy sessions tracked only `heat` (scene stayed 0). Seed the step
        # counter from the stored phase so returning users don't reset to phase 1.
        if step == 0 and row and row["heat"]:
            step = int(row["heat"]) * STEPS_PER_PHASE

        if not rude:
            step = min(max_step, step + 1)
        heat = min(max_heat, step // STEPS_PER_PHASE)

        await conn.execute(
            """
            INSERT INTO story_progress (user_id, chapter, scene, heat)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET scene = ?, heat = ?
            """,
            (user_id, step, heat, step, heat),
        )
        await conn.commit()
    finally:
        await conn.close()

    state = _state(heat)
    logger.info(
        "Story heat user %d: phase %d/%d (%s)%s",
        user_id, state["stage"], max_heat + 1, state["label"], " [rude, held]" if rude else "",
    )
    return state
