"""
Story progression scoring — mirrors the Sexting intimacy system for Story mode.

Instead of a single yes/no check (which made chapters fly by after one
message), each exchange is scored 0-10 for how much it advances the chapter's
goal. A chapter advances only once enough exchanges have happened AND the
accumulated score crosses a threshold (or the goal is clearly, fully met).
"""

import json
import logging
import time

from bot.memory.db import get_connection

logger = logging.getLogger(__name__)

# Pacing thresholds (analogous to intimacy STAGE_*_MIN_* constants)
STORY_MIN_MESSAGES_PER_CHAPTER = 6   # minimum exchanges before a normal advance
STORY_ADVANCE_SCORE = 22             # accumulated advancement needed to move on
STORY_TRIGGER_MIN_MESSAGES = 3       # allow an early advance once goal is clearly met

EVAL_PROMPT = """You are pacing an interactive roleplay story. Score how much the LATEST exchange moves the current chapter toward its goal.

Chapter: {title}
Progression goal: "{trigger}"

User: "{user_msg}"
Character: "{response}"

Return ONLY a JSON object:
{{
  "advancement": <int 0 to 10>,
  "trigger_met": <true or false>,
  "reasoning": "<one short sentence>"
}}

Scoring guide:
- 0-2: stalling, small talk, repetition, off-topic
- 3-6: meaningful progress, tension building, getting closer
- 7-10: a major story beat lands
- trigger_met: true ONLY if the progression goal is clearly and fully satisfied right now.
"""


async def _ensure_columns() -> None:
    """Add scoring columns to story_progress if an older DB is missing them."""
    conn = await get_connection()
    try:
        cursor = await conn.execute("PRAGMA table_info(story_progress)")
        cols = {row["name"] for row in await cursor.fetchall()}
        if "chapter_score" not in cols:
            await conn.execute(
                "ALTER TABLE story_progress ADD COLUMN chapter_score INTEGER NOT NULL DEFAULT 0"
            )
        if "chapter_messages" not in cols:
            await conn.execute(
                "ALTER TABLE story_progress ADD COLUMN chapter_messages INTEGER NOT NULL DEFAULT 0"
            )
        await conn.commit()
    finally:
        await conn.close()


async def get_progress(user_id: int) -> dict:
    """Return {chapter, score, messages} for the current chapter."""
    await _ensure_columns()
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT chapter, chapter_score, chapter_messages "
            "FROM story_progress WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row:
            return {
                "chapter": row["chapter"],
                "score": row["chapter_score"],
                "messages": row["chapter_messages"],
            }
        return {"chapter": 1, "score": 0, "messages": 0}
    finally:
        await conn.close()


async def record_turn(
    user_id: int,
    chapter: int,
    user_msg: str,
    response: str,
    chapter_meta: dict,
    llm_call,
) -> bool:
    """
    Score the latest exchange, accumulate progress, and decide whether the
    chapter should advance. Returns True if the caller should advance the chapter.
    Does NOT change the chapter number itself.
    """
    await _ensure_columns()

    state = await get_progress(user_id)
    score = state["score"]
    messages = state["messages"]

    prompt = EVAL_PROMPT.format(
        title=chapter_meta.get("title", ""),
        trigger=chapter_meta.get("progression_trigger", ""),
        user_msg=user_msg[:500],
        response=response[:800],
    )

    advancement = 0
    trigger_met = False
    try:
        raw = (await llm_call(prompt)).strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(raw)
        advancement = max(0, min(10, int(data.get("advancement", 0))))
        trigger_met = bool(data.get("trigger_met", False))
        logger.info(
            "Story eval user %d ch%d: +%d (trigger_met=%s) | %s",
            user_id, chapter, advancement, trigger_met, data.get("reasoning", ""),
        )
    except Exception as e:
        logger.warning("Story eval failed for user %d: %s", user_id, e)
        advancement = 1  # small nudge so progression never fully stalls

    new_score = score + advancement
    new_messages = messages + 1

    should_advance = (
        (new_messages >= STORY_MIN_MESSAGES_PER_CHAPTER and new_score >= STORY_ADVANCE_SCORE)
        or (trigger_met and new_messages >= STORY_TRIGGER_MIN_MESSAGES)
    )

    # Persist accumulated progress (ensure the row exists)
    conn = await get_connection()
    try:
        await conn.execute(
            """
            INSERT INTO story_progress (user_id, chapter, scene, chapter_score, chapter_messages)
            VALUES (?, ?, 0, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                chapter_score = ?,
                chapter_messages = ?
            """,
            (user_id, chapter, new_score, new_messages, new_score, new_messages),
        )
        await conn.commit()
    finally:
        await conn.close()

    return should_advance
