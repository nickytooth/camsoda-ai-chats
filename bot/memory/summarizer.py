import json
import logging
from bot.memory.embeddings import embed_texts
from bot.memory.ltm import store_memory, count_memories, get_all_memories, delete_memories_by_ids, find_similar_memory, update_memory
from bot.memory.stm import get_oldest_messages, delete_messages_by_ids, count_turns
from bot.config import STM_MAX_TURNS, STM_SUMMARIZE_BATCH, LTM_COMPACTION_THRESHOLD

logger = logging.getLogger(__name__)

SUMMARIZE_PROMPT = """Analyze the following conversation and extract TWO things:

1. "memories": structured memory entries, each with:
   - category: one of "fact", "preference", "relationship", "event", "thread"
   - content: a concise statement (1-2 sentences max)
   - importance: integer 1-10 (10 = critical identity info like name, 1 = trivial)

2. "facts": key-value pairs for specific known facts about the user. Use ONLY these keys when applicable:
   name, location, age, job, gender, boundaries, agreed_prices, relationship_status
   Also include any other notable preferences or details as custom keys (e.g. "favorite_color", "pet_name", "kinks").

Return ONLY a JSON object with both keys. No other text.

Example:
{
  "memories": [
    {"category": "fact", "content": "User's name is Alex and he lives in London", "importance": 10},
    {"category": "preference", "content": "User likes being called 'good boy'", "importance": 7}
  ],
  "facts": [
    {"key": "name", "value": "Alex"},
    {"key": "location", "value": "London"},
    {"key": "kinks", "value": "likes being called good boy"}
  ]
}

Conversation:
"""

COMPACTION_PROMPT = """You have the following memory entries about a user. Some may be duplicates or overlapping.
Merge them into a clean, deduplicated list. Keep the most important and up-to-date information.
Return ONLY a JSON array with the same format.

Entries:
"""


def _format_messages_for_summary(messages: list[dict]) -> str:
    lines = []
    for msg in messages:
        prefix = "User" if msg["role"] == "user" else "Bot"
        lines.append(f"{prefix}: {msg['content']}")
    return "\n".join(lines)


async def maybe_summarize(user_id: int, llm_call) -> bool:
    turns = await count_turns(user_id)
    if turns < STM_MAX_TURNS:
        return False

    oldest = await get_oldest_messages(user_id, STM_SUMMARIZE_BATCH)
    if not oldest:
        return False

    conversation_text = _format_messages_for_summary(oldest)
    prompt = SUMMARIZE_PROMPT + conversation_text

    try:
        raw_response = await llm_call(prompt)
        parsed = json.loads(raw_response)
    except (json.JSONDecodeError, Exception) as e:
        logger.error("Summarization failed: %s", e)
        return False

    # Handle both old format (plain array) and new format (object with memories+facts)
    if isinstance(parsed, list):
        entries = parsed
        facts = []
    else:
        entries = parsed.get("memories", [])
        facts = parsed.get("facts", [])

    # Store memories as embeddings in LTM
    if entries:
        texts = [entry["content"] for entry in entries]
        embeddings = await embed_texts(texts)

        new_count = 0
        updated_count = 0
        for entry, embedding in zip(entries, embeddings):
            existing = await find_similar_memory(user_id, embedding, threshold=0.85)
            if existing:
                new_imp = max(existing["importance"], entry.get("importance", 5))
                await update_memory(existing["id"], entry["content"], new_imp, embedding)
                updated_count += 1
            else:
                await store_memory(
                    user_id=user_id,
                    category=entry.get("category", "fact"),
                    content=entry["content"],
                    importance=entry.get("importance", 5),
                    embedding=embedding,
                )
                new_count += 1

        logger.info("Summarized %d messages for user %d: %d new, %d updated memories", len(oldest), user_id, new_count, updated_count)

    # Store structured facts
    if facts:
        from bot.memory.facts import upsert_fact
        fact_count = 0
        for fact in facts:
            key = fact.get("key", "").strip().lower()
            value = fact.get("value", "").strip()
            if key and value:
                await upsert_fact(user_id, key, value)
                fact_count += 1
        if fact_count:
            logger.info("Extracted %d facts for user %d", fact_count, user_id)

    message_ids = [msg["id"] for msg in oldest]
    await delete_messages_by_ids(message_ids)

    return True


async def maybe_compact(user_id: int, llm_call) -> bool:
    mem_count = await count_memories(user_id)
    if mem_count < LTM_COMPACTION_THRESHOLD:
        return False

    memories = await get_all_memories(user_id)
    entries_text = json.dumps(
        [{"category": m["category"], "content": m["content"], "importance": m["importance"]} for m in memories],
        indent=2,
    )
    prompt = COMPACTION_PROMPT + entries_text

    try:
        raw_response = await llm_call(prompt)
        new_entries = json.loads(raw_response)
    except (json.JSONDecodeError, Exception) as e:
        logger.error("Compaction failed: %s", e)
        return False

    old_ids = [m["id"] for m in memories]
    await delete_memories_by_ids(old_ids)

    texts = [entry["content"] for entry in new_entries]
    embeddings = await embed_texts(texts)

    for entry, embedding in zip(new_entries, embeddings):
        await store_memory(
            user_id=user_id,
            category=entry.get("category", "fact"),
            content=entry["content"],
            importance=entry.get("importance", 5),
            embedding=embedding,
        )

    logger.info("Compacted %d memories into %d for user %d", len(old_ids), len(new_entries), user_id)
    return True
