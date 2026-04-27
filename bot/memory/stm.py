import time
from bot.memory.db import get_connection


async def add_message(user_id: int, role: str, content: str) -> None:
    conn = await get_connection()
    try:
        await conn.execute(
            "INSERT INTO messages (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, role, content, time.time()),
        )
        await conn.commit()
    finally:
        await conn.close()


async def get_recent_messages(user_id: int, limit: int) -> list[dict]:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT role, content, timestamp FROM messages "
            "WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit * 2),
        )
        rows = await cursor.fetchall()
        return [
            {"role": row["role"], "content": row["content"], "timestamp": row["timestamp"]}
            for row in reversed(rows)
        ]
    finally:
        await conn.close()


async def count_turns(user_id: int) -> int:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE user_id = ? AND role = 'user'",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0
    finally:
        await conn.close()


async def get_oldest_messages(user_id: int, limit: int) -> list[dict]:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT id, role, content, timestamp FROM messages "
            "WHERE user_id = ? ORDER BY timestamp ASC LIMIT ?",
            (user_id, limit * 2),
        )
        rows = await cursor.fetchall()
        return [
            {"id": row["id"], "role": row["role"], "content": row["content"], "timestamp": row["timestamp"]}
            for row in rows
        ]
    finally:
        await conn.close()


async def delete_messages_by_ids(message_ids: list[int]) -> None:
    if not message_ids:
        return
    conn = await get_connection()
    try:
        placeholders = ",".join("?" for _ in message_ids)
        await conn.execute(
            f"DELETE FROM messages WHERE id IN ({placeholders})",
            message_ids,
        )
        await conn.commit()
    finally:
        await conn.close()
