import time
import numpy as np
from bot.memory.db import get_connection
from bot.memory.embeddings import embed_text, cosine_similarity
from bot.config import (
    LTM_TOP_K,
    LTM_SIMILARITY_WEIGHT,
    LTM_IMPORTANCE_WEIGHT,
    LTM_RECENCY_WEIGHT,
)


async def store_memory(
    user_id: int, category: str, content: str, importance: int, embedding: np.ndarray
) -> None:
    conn = await get_connection()
    try:
        await conn.execute(
            "INSERT INTO memories (user_id, category, content, importance, embedding, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, category, content, importance, embedding.tobytes(), time.time()),
        )
        await conn.commit()
    finally:
        await conn.close()


async def get_all_memories(user_id: int) -> list[dict]:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT id, category, content, importance, embedding, created_at, last_accessed "
            "FROM memories WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            emb = np.frombuffer(row["embedding"], dtype=np.float32) if row["embedding"] else None
            results.append({
                "id": row["id"],
                "category": row["category"],
                "content": row["content"],
                "importance": row["importance"],
                "embedding": emb,
                "created_at": row["created_at"],
                "last_accessed": row["last_accessed"],
            })
        return results
    finally:
        await conn.close()


async def retrieve_relevant(user_id: int, message: str, top_k: int = LTM_TOP_K) -> list[dict]:
    memories = await get_all_memories(user_id)
    if not memories:
        return []

    query_embedding = await embed_text(message)
    now = time.time()
    max_age = max((now - m["created_at"]) for m in memories) or 1.0

    scored = []
    for mem in memories:
        if mem["embedding"] is None:
            continue

        sim = cosine_similarity(query_embedding, mem["embedding"])
        imp = mem["importance"] / 10.0
        recency = 1.0 - ((now - mem["created_at"]) / max_age)

        score = (
            sim * LTM_SIMILARITY_WEIGHT
            + imp * LTM_IMPORTANCE_WEIGHT
            + recency * LTM_RECENCY_WEIGHT
        )
        scored.append({"memory": mem, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:top_k]

    # Update last_accessed for retrieved memories
    if top:
        conn = await get_connection()
        try:
            for item in top:
                await conn.execute(
                    "UPDATE memories SET last_accessed = ? WHERE id = ?",
                    (now, item["memory"]["id"]),
                )
            await conn.commit()
        finally:
            await conn.close()

    return [item["memory"] for item in top]


async def find_similar_memory(
    user_id: int, embedding: np.ndarray, threshold: float = 0.85
) -> dict | None:
    """Find an existing memory with cosine similarity above threshold."""
    memories = await get_all_memories(user_id)
    best_match = None
    best_sim = 0.0
    for mem in memories:
        if mem["embedding"] is None:
            continue
        sim = cosine_similarity(embedding, mem["embedding"])
        if sim > best_sim:
            best_sim = sim
            best_match = mem
    if best_sim >= threshold and best_match:
        return best_match
    return None


async def update_memory(
    memory_id: int, content: str, importance: int, embedding: np.ndarray
) -> None:
    """Update an existing memory entry."""
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE memories SET content = ?, importance = ?, embedding = ? WHERE id = ?",
            (content, importance, embedding.tobytes(), memory_id),
        )
        await conn.commit()
    finally:
        await conn.close()


async def count_memories(user_id: int) -> int:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM memories WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0
    finally:
        await conn.close()


async def delete_memories_by_ids(memory_ids: list[int]) -> None:
    if not memory_ids:
        return
    conn = await get_connection()
    try:
        placeholders = ",".join("?" for _ in memory_ids)
        await conn.execute(
            f"DELETE FROM memories WHERE id IN ({placeholders})",
            memory_ids,
        )
        await conn.commit()
    finally:
        await conn.close()
