"""
Re-engagement background task.

Periodically checks for users who haven't messaged in 24h and sends
a casual "hey" from Aishha to re-start the conversation.
"""

import asyncio
import random
import logging
import time
from bot.memory.db import get_connection
from bot.engagement import get_engagement_state, record_reengage

logger = logging.getLogger(__name__)

REENGAGE_AFTER_SECONDS = 24 * 3600      # 24 hours
REENGAGE_COOLDOWN_SECONDS = 48 * 3600   # 48 hours between re-engagements
MIN_MESSAGES_FOR_REENGAGE = 5           # don't re-engage strangers
CHECK_INTERVAL_SECONDS = 3600           # check every hour

REENGAGE_MESSAGES = [
    "heyyy where'd u go 😭",
    "i was just thinking about u lol",
    "bored. entertain me 😏",
    "hiii u alive? 😂",
    "ok so i just did the dumbest thing and i need to tell someone 😭",
    "u disappeared on me 🥺",
    "hey stranger 👋 miss talking to u",
]


async def _get_stale_users() -> list[dict]:
    """Find users who haven't messaged in 24h+ and meet re-engagement criteria."""
    conn = await get_connection()
    try:
        now = time.time()
        cutoff = now - REENGAGE_AFTER_SECONDS
        cooldown_cutoff = now - REENGAGE_COOLDOWN_SECONDS

        cursor = await conn.execute("""
            SELECT user_id, total_messages, last_message_at, last_reengage_at
            FROM engagement_state
            WHERE last_message_at < ?
              AND last_message_at > 0
              AND total_messages >= ?
              AND (last_reengage_at IS NULL OR last_reengage_at < ?)
        """, (cutoff, MIN_MESSAGES_FOR_REENGAGE, cooldown_cutoff))

        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def reengage_loop(userbot):
    """Background loop that sends re-engagement messages."""
    logger.info("Re-engagement loop started (check every %ds)", CHECK_INTERVAL_SECONDS)

    while True:
        try:
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

            stale_users = await _get_stale_users()
            if not stale_users:
                logger.debug("No users to re-engage")
                continue

            logger.info("Found %d users to re-engage", len(stale_users))

            for user in stale_users:
                user_id = user["user_id"]
                msg = random.choice(REENGAGE_MESSAGES)

                try:
                    await userbot.send_message(chat_id=user_id, text=msg)
                    await record_reengage(user_id)

                    # Store in STM so Aishha knows she sent it
                    from bot.memory.stm import add_message
                    await add_message(user_id, "assistant", msg)

                    logger.info("Re-engaged user %d: %s", user_id, msg[:40])

                    # Small delay between users to avoid rate limits
                    await asyncio.sleep(5)

                except Exception as e:
                    logger.error("Failed to re-engage user %d: %s", user_id, e)

        except asyncio.CancelledError:
            logger.info("Re-engagement loop cancelled")
            break
        except Exception as e:
            logger.error("Re-engagement loop error: %s", e, exc_info=True)
            await asyncio.sleep(60)
