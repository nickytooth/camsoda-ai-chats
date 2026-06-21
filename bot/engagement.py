"""
Engagement tracking for soft-push content selling.

Tracks NSFW message count per user and decides when Victoria should
hint at content to build rapport.
"""

import logging
import time
from bot.memory.db import get_connection

logger = logging.getLogger(__name__)

SOFT_PUSH_THRESHOLD = 8        # nsfw messages before pushing a photo
# Min seconds between two proactive photos — BUT this is waived if the user
# bought (unlocked) the last photo we pushed. Paying users keep getting new
# photos as soon as they hit the next SOFT_PUSH_THRESHOLD; non-payers wait.
SOFT_PUSH_COOLDOWN = 300       # 5 min


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
                last_reengage_at REAL DEFAULT 0,
                last_push_content_id TEXT
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


async def can_push_photo(user_id: int) -> bool:
    """Whether the proactive-photo cooldown allows another push right now.

    The 5-minute cooldown is WAIVED if the user bought (unlocked) the last
    photo we proactively pushed — paying users keep the content flowing.
    """
    await _ensure_table()
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT last_push_at, last_push_content_id FROM engagement_state WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
    finally:
        await conn.close()

    if not row:
        return True

    last_push = row["last_push_at"] or 0
    last_content = row["last_push_content_id"]

    # Never pushed before → allow.
    if last_push <= 0:
        return True

    # Bought the last pushed photo → cooldown waived.
    if last_content:
        from bot.photo_content import is_photo_unlocked
        if await is_photo_unlocked(user_id, last_content):
            return True

    # Otherwise enforce the time cooldown.
    return (time.time() - last_push) >= SOFT_PUSH_COOLDOWN


async def should_soft_push(user_id: int) -> bool:
    """True when Victoria should proactively push a photo on her next reply:
    enough nsfw messages since the last push AND the cooldown allows it."""
    await _ensure_table()
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT nsfw_count FROM engagement_state WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
    finally:
        await conn.close()

    if not row:
        return False
    # Need at least SOFT_PUSH_THRESHOLD nsfw messages since the last push.
    # (record_push resets nsfw_count to 0, so this also enforces "since last".)
    if row["nsfw_count"] < SOFT_PUSH_THRESHOLD:
        return False
    return await can_push_photo(user_id)


async def record_push(user_id: int, content_id: str | None = None) -> None:
    """Record that we just pushed a photo (or a tease), reset nsfw counter, and
    remember which photo went out so can_push_photo can check if it gets paid.
    Upserts so it works even if the user has no engagement row yet."""
    await _ensure_table()
    conn = await get_connection()
    try:
        now = time.time()
        await conn.execute(
            "INSERT INTO engagement_state (user_id, nsfw_count, last_push_at, last_push_content_id) "
            "VALUES (?, 0, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "last_push_at = ?, nsfw_count = 0, last_push_content_id = ?",
            (user_id, now, content_id, now, content_id),
        )
        await conn.commit()
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
