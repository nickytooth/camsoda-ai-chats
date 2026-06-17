"""
Authored fantasy/story libraries + per-user "already shared" tracking.

The libraries (library/*.yaml) are the same for everyone. Which items Victoria
has already told a given user is tracked in Postgres (shared_content), so the
"Hear a fantasy" / "Hear a story" cards never repeat until the pool is exhausted.
"""

import time
import random
import logging
import yaml

from bot.config import FANTASIES_FILE, STORIES_FILE
from bot.memory.db import get_connection

logger = logging.getLogger(__name__)

# kind -> (file path, top-level yaml key)
_SOURCES = {
    "fantasy": (FANTASIES_FILE, "fantasies"),
    "story": (STORIES_FILE, "stories"),
}

_cache: dict[str, list[dict]] = {}


def _load(kind: str) -> list[dict]:
    """Load and cache a library file. Returns a list of {id, text, tags}."""
    if kind in _cache:
        return _cache[kind]
    src = _SOURCES.get(kind)
    if not src:
        return []
    path, key = src
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        items = [it for it in (data.get(key) or []) if it.get("id") and it.get("text")]
    except Exception as e:
        logger.warning("Failed to load %s library from %s: %s", kind, path, e)
        items = []
    _cache[kind] = items
    return items


async def _shared_ids(user_id: int, kind: str) -> set[str]:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT item_id FROM shared_content WHERE user_id = ? AND kind = ?",
            (user_id, kind),
        )
        rows = await cursor.fetchall()
        return {row["item_id"] for row in rows}
    finally:
        await conn.close()


async def pick_unshared(user_id: int, kind: str) -> dict | None:
    """Return a random library item this user hasn't been told yet, or None if
    the pool is exhausted (caller should then fall back to a personalised one)."""
    items = _load(kind)
    if not items:
        return None
    shared = await _shared_ids(user_id, kind)
    candidates = [it for it in items if it["id"] not in shared]
    if not candidates:
        return None
    return random.choice(candidates)


async def mark_shared(user_id: int, kind: str, item_id: str) -> None:
    conn = await get_connection()
    try:
        await conn.execute(
            "INSERT INTO shared_content (user_id, kind, item_id, shared_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(user_id, kind, item_id) DO NOTHING",
            (user_id, kind, item_id, time.time()),
        )
        await conn.commit()
    finally:
        await conn.close()


async def shared_count(user_id: int, kind: str) -> int:
    """How many of this kind she's already told the user (for logging/UX)."""
    return len(await _shared_ids(user_id, kind))
