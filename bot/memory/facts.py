"""Structured fact store — hard facts injected deterministically every turn."""

import time
import logging
from bot.memory.db import get_connection

logger = logging.getLogger(__name__)

# Hard fact keys that are always injected into the prompt
HARD_FACT_KEYS = {
    "name", "location", "age", "job", "gender",
    "boundaries", "agreed_prices", "relationship_status",
}


async def upsert_fact(user_id: int, key: str, value: str, confidence: float = 0.8) -> None:
    """Insert or update a fact. Latest value wins on conflicts."""
    now = time.time()
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT id, value FROM user_facts WHERE user_id = ? AND key = ?",
            (user_id, key),
        )
        existing = await cursor.fetchone()
        if existing:
            if existing["value"] != value:
                await conn.execute(
                    "UPDATE user_facts SET value = ?, confidence = ?, updated_at = ? "
                    "WHERE user_id = ? AND key = ?",
                    (value, confidence, now, user_id, key),
                )
                logger.info("Updated fact for user %d: %s = %s (was: %s)", user_id, key, value, existing["value"])
        else:
            await conn.execute(
                "INSERT INTO user_facts (user_id, key, value, confidence, first_seen, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, key, value, confidence, now, now),
            )
            logger.info("Stored new fact for user %d: %s = %s", user_id, key, value)
        await conn.commit()
    finally:
        await conn.close()


async def get_facts(user_id: int) -> list[dict]:
    """Get all facts for a user, ordered by key."""
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT key, value, confidence, first_seen, updated_at "
            "FROM user_facts WHERE user_id = ? ORDER BY key",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "key": row["key"],
                "value": row["value"],
                "confidence": row["confidence"],
                "first_seen": row["first_seen"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    finally:
        await conn.close()


def format_facts_for_prompt(facts: list[dict]) -> str | None:
    """Format facts into a compact prompt section. Returns None if no facts."""
    if not facts:
        return None

    hard = []
    soft = []
    for f in facts:
        line = f"{f['key']}: {f['value']}"
        if f["key"] in HARD_FACT_KEYS:
            hard.append(line)
        else:
            soft.append(line)

    parts = ["Known facts about this person (use naturally, don't recite):"]
    if hard:
        parts.extend(f"- {h}" for h in hard)
    if soft:
        parts.extend(f"- {s}" for s in soft)
    return "\n".join(parts)
