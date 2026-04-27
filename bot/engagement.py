"""
Engagement tracking for soft-push content selling and unprompted selfies.

Tracks NSFW message count per user and decides when Aishha should
hint at content or send a free selfie to build rapport.
"""

import random
import logging
import time
from bot.memory.db import get_connection

logger = logging.getLogger(__name__)

SOFT_PUSH_THRESHOLD = 8   # flirty messages before hinting
SELFIE_PROBABILITY = 0.20  # 20% chance after threshold


async def _ensure_table():
    conn = await get_connection()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS engagement_state (
                user_id INTEGER PRIMARY KEY,
                nsfw_count INTEGER NOT NULL DEFAULT 0,
                total_messages INTEGER NOT NULL DEFAULT 0,
                last_push_at REAL DEFAULT 0,
                last_selfie_at REAL DEFAULT 0,
                last_message_at REAL DEFAULT 0,
                last_reengage_at REAL DEFAULT 0
            )
        """)
        await conn.commit()
    finally:
        await conn.close()


async def track_message(user_id: int, classification: str) -> None:
    """Track a user message and its SFW/NSFW classification."""
    await _ensure_table()
    conn = await get_connection()
    try:
        now = time.time()
        await conn.execute("""
            INSERT INTO engagement_state (user_id, nsfw_count, total_messages, last_message_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                nsfw_count = CASE WHEN ? = 'nsfw'
                    THEN engagement_state.nsfw_count + 1
                    ELSE engagement_state.nsfw_count END,
                total_messages = engagement_state.total_messages + 1,
                last_message_at = ?
        """, (user_id, 1 if classification == "nsfw" else 0, now, classification, now))
        await conn.commit()
    finally:
        await conn.close()


async def should_soft_push(user_id: int) -> bool:
    """Check if we should inject a content hint into Aishha's next response."""
    await _ensure_table()
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT nsfw_count, last_push_at FROM engagement_state WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return False

        nsfw_count = row["nsfw_count"]
        last_push = row["last_push_at"] or 0

        # Need at least SOFT_PUSH_THRESHOLD nsfw messages since last push
        if nsfw_count < SOFT_PUSH_THRESHOLD:
            return False

        # Don't push if we pushed recently (within last 8 messages tracked via count reset)
        if last_push > 0 and nsfw_count < SOFT_PUSH_THRESHOLD:
            return False

        return True
    finally:
        await conn.close()


async def record_push(user_id: int) -> None:
    """Record that we just did a soft push, reset nsfw counter."""
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE engagement_state SET last_push_at = ?, nsfw_count = 0 WHERE user_id = ?",
            (time.time(), user_id),
        )
        await conn.commit()
    finally:
        await conn.close()


async def should_send_selfie(user_id: int) -> bool:
    """Check if we should send an unprompted free selfie (probability-based)."""
    await _ensure_table()
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT total_messages, last_selfie_at FROM engagement_state WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return False

        # Need at least 8 total messages for rapport
        if row["total_messages"] < 8:
            return False

        # Max 1 selfie per session (roughly 2 hours)
        last_selfie = row["last_selfie_at"] or 0
        if time.time() - last_selfie < 7200:
            return False

        # Probability gate
        if random.random() > SELFIE_PROBABILITY:
            return False

        # Record selfie send
        await conn.execute(
            "UPDATE engagement_state SET last_selfie_at = ? WHERE user_id = ?",
            (time.time(), user_id),
        )
        await conn.commit()
        logger.info("Sending unprompted selfie to user %d", user_id)
        return True
    finally:
        await conn.close()


async def get_engagement_state(user_id: int) -> dict | None:
    """Get engagement state for a user (used by re-engagement)."""
    await _ensure_table()
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT * FROM engagement_state WHERE user_id = ?",
            (user_id,),
        )
        return await cursor.fetchone()
    finally:
        await conn.close()


async def record_reengage(user_id: int) -> None:
    """Record that we sent a re-engagement message."""
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE engagement_state SET last_reengage_at = ? WHERE user_id = ?",
            (time.time(), user_id),
        )
        await conn.commit()
    finally:
        await conn.close()
