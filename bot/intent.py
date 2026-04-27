"""
LLM-based intent detection for content requests.

Uses Gemini Flash to understand whether a user message is asking for
content — even when phrased vaguely like "show me something naughty".
"""

import logging

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"selfies", "videos"}

INTENT_PROMPT = """You are analyzing a chat message to determine if the user is requesting to see content from a content creator.

User's message: "{message}"

Recent conversation context:
{context}

Available content:
- selfies — free casual pics/selfies
- videos — paid exclusive videos (naughty/explicit)

Reply with ONLY one of these (no explanation, no punctuation):
- none — the user is NOT requesting content, just chatting normally
- suggest — the user seems interested in content but didn't specify what kind
- selfies — user wants to see a pic/selfie of the creator
- videos — user wants to see a video (any explicit/naughty/spicy request = videos)

Examples:
- "hey what's up" → none
- "show me something naughty" → videos
- "send me a video" → videos
- "i wanna see your ass" → videos
- "got any pics?" → suggest
- "you're so hot" → none
- "can i see more of you" → suggest
- "send me a selfie" → selfies
- "show me your tits" → videos
- "i want to see everything" → videos
- "send me a pic of you" → selfies
- "show me what you got" → suggest
"""


async def detect_content_intent(
    message: str,
    recent_messages: list[dict],
    llm_call,
) -> str:
    """Detect if a message is a content request.

    Returns: "none", "suggest", or a category name.
    """
    context_lines = []
    for msg in recent_messages[-6:]:
        prefix = "User" if msg["role"] == "user" else "Aishha"
        context_lines.append(f"{prefix}: {msg['content'][:100]}")
    context = "\n".join(context_lines) if context_lines else "(new conversation)"

    prompt = INTENT_PROMPT.format(message=message, context=context)

    try:
        raw = await llm_call(prompt)
        result = raw.strip().lower().replace('"', "").replace("'", "")

        if result in VALID_CATEGORIES:
            logger.info("Intent detected: category=%s", result)
            return result
        if result == "suggest":
            logger.info("Intent detected: suggest")
            return "suggest"

        logger.debug("Intent: none (raw=%s)", result[:30])
        return "none"
    except Exception as e:
        logger.error("Intent detection failed: %s", e)
        return "none"
