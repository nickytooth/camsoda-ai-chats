"""
Intimacy progression system for Sexting mode.

Tracks per-user intimacy stage (1-3) and flirt score.
Uses Gemini to evaluate each user message for charm, respect, humor,
vulgarity, and boundary-pushing.
"""

import logging
import time
import json
from bot.memory.db import get_connection

logger = logging.getLogger(__name__)

# Stage transition thresholds
STAGE_2_MIN_MESSAGES = 15
STAGE_2_MIN_SCORE = 30
STAGE_3_MIN_MESSAGES = 30
STAGE_3_MIN_SCORE = 70

# Evaluation prompt for Gemini
EVAL_PROMPT = """You are scoring a user's message in a flirtatious chat with an elegant, sophisticated older woman.
The user is trying to seduce her. She values charm, wit, respect, and patience.

Current intimacy stage: {stage} (1=distant/curious, 2=warming up, 3=fully open)
Message count so far: {msg_count}
Current score: {current_score}

User's message: "{message}"

Score this message on the following dimensions. Return ONLY a JSON object:
{{
  "charm": <int -2 to 5>,
  "respect": <int -5 to 3>,
  "humor": <int -1 to 4>,
  "vulgarity": <int -10 to 0>,
  "pushing": <int -5 to 0>,
  "reasoning": "<brief 1-sentence explanation>"
}}

Rules:
- "charm": wit, compliments, playful banter, showing genuine interest = positive. Boring/generic = 0 or -1.
- "respect": respecting boundaries, proper tone = positive. Demanding, entitled = negative.
- "humor": making her laugh, clever wordplay = positive. Trying too hard = 0.
- "vulgarity": crude language, slurs, crass sexual demands = very negative. Clean = 0.
- "pushing": demanding sex/nudes/explicit content before stage 3 = negative. Patient = 0.

At stage 1, vulgarity and pushing are penalized HEAVILY (-8 to -10).
At stage 3, mild sexual language is acceptable (vulgarity penalty reduced to -1 to -3 for moderate content).
"""


async def _ensure_table():
    conn = await get_connection()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS intimacy_state (
                user_id INTEGER PRIMARY KEY,
                stage INTEGER NOT NULL DEFAULT 1,
                flirt_score INTEGER NOT NULL DEFAULT 0,
                message_count INTEGER NOT NULL DEFAULT 0,
                last_evaluated_at REAL DEFAULT 0
            )
        """)
        await conn.commit()
    finally:
        await conn.close()


async def get_stage(user_id: int) -> int:
    """Get current intimacy stage for a user (1, 2, or 3)."""
    await _ensure_table()
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT stage FROM intimacy_state WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row["stage"] if row else 1
    finally:
        await conn.close()


async def get_intimacy_state(user_id: int) -> dict:
    """Get full intimacy state for a user."""
    await _ensure_table()
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT stage, flirt_score, message_count FROM intimacy_state WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row:
            return {"stage": row["stage"], "flirt_score": row["flirt_score"], "message_count": row["message_count"]}
        return {"stage": 1, "flirt_score": 0, "message_count": 0}
    finally:
        await conn.close()


async def evaluate_message(user_id: int, text: str, llm_call) -> int:
    """
    Evaluate a user message and update intimacy score/stage.
    
    Args:
        user_id: User ID
        text: The user's message text
        llm_call: async function(prompt: str) -> str (Gemini)
    
    Returns:
        Current stage after evaluation
    """
    await _ensure_table()

    # Get current state
    state = await get_intimacy_state(user_id)
    stage = state["stage"]
    score = state["flirt_score"]
    msg_count = state["message_count"]

    # Build evaluation prompt
    prompt = EVAL_PROMPT.format(
        stage=stage,
        msg_count=msg_count,
        current_score=score,
        message=text[:500],  # Limit message length for eval
    )

    # Get score from LLM
    score_delta = 0
    try:
        response = await llm_call(prompt)
        # Parse JSON from response
        response = response.strip()
        if response.startswith("```"):
            response = response.split("\n", 1)[1].rsplit("```", 1)[0]
        
        data = json.loads(response)
        score_delta = (
            data.get("charm", 0)
            + data.get("respect", 0)
            + data.get("humor", 0)
            + data.get("vulgarity", 0)
            + data.get("pushing", 0)
        )
        logger.info(
            "Intimacy eval user %d: delta=%+d (charm=%d, respect=%d, humor=%d, vulgar=%d, push=%d) | %s",
            user_id, score_delta,
            data.get("charm", 0), data.get("respect", 0), data.get("humor", 0),
            data.get("vulgarity", 0), data.get("pushing", 0),
            data.get("reasoning", ""),
        )
    except Exception as e:
        logger.warning("Intimacy evaluation failed for user %d: %s", user_id, e)
        # Default: small positive for any message (keeps progression moving)
        score_delta = 1

    # Update score (never below 0)
    new_score = max(0, score + score_delta)
    new_msg_count = msg_count + 1

    # Check stage transitions (never go backwards)
    new_stage = stage
    if stage == 1 and new_msg_count >= STAGE_2_MIN_MESSAGES and new_score >= STAGE_2_MIN_SCORE:
        new_stage = 2
        logger.info("User %d advanced to Stage 2 (score=%d, msgs=%d)", user_id, new_score, new_msg_count)
    elif stage == 2 and new_msg_count >= STAGE_3_MIN_MESSAGES and new_score >= STAGE_3_MIN_SCORE:
        new_stage = 3
        logger.info("User %d advanced to Stage 3 (score=%d, msgs=%d)", user_id, new_score, new_msg_count)

    # Persist
    conn = await get_connection()
    try:
        await conn.execute("""
            INSERT INTO intimacy_state (user_id, stage, flirt_score, message_count, last_evaluated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                stage = ?,
                flirt_score = ?,
                message_count = ?,
                last_evaluated_at = ?
        """, (user_id, new_stage, new_score, new_msg_count, time.time(),
              new_stage, new_score, new_msg_count, time.time()))
        await conn.commit()
    finally:
        await conn.close()

    return new_stage
