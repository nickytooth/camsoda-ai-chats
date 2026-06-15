"""
Per-message signal scoring for Sexting mode.

Victoria is always fully open — there is no staged progression. This module
only extracts lightweight emotional signals (charm, respect, humor, vulgarity,
pushing) from each user message so the mood system can colour her tone.
"""

import logging
import json
from bot.memory.db import get_connection

logger = logging.getLogger(__name__)

# Evaluation prompt for Gemini
EVAL_PROMPT = """You are reading a single message a man just sent to Victoria, an
elegant, confident, sexually open older woman in a consensual adult chat.
Score how he is treating her RIGHT NOW so we can colour her emotional tone.

User's message: "{message}"

Return ONLY a JSON object:
{{
  "nsfw": <true if the message is sexual/explicit, else false>,
  "charm": <int -2 to 5>,
  "respect": <int -5 to 3>,
  "humor": <int -1 to 4>,
  "vulgarity": <int -10 to 0>,
  "pushing": <int -5 to 0>,
  "reasoning": "<brief 1-sentence explanation>"
}}

Rules:
- "nsfw": true if the message is sexual, flirtatious-explicit, or about bodies/desire in an adult way. Plain chit-chat = false.
- "charm": wit, compliments, playful banter, genuine interest = positive. Boring/generic = 0 or -1.
- "respect": warm, decent tone = positive. Genuinely degrading, insulting, or treating her like an object = negative.
- "humor": making her laugh, clever wordplay = positive. Trying too hard = 0.
- "vulgarity": she is OPEN to sex and dirty talk, so consensual explicit/flirty language is fine (0). Only penalize genuinely crude, gross, or hostile language (slurs, insults). Mild = 0, never punish normal sexual interest.
- "pushing": only negative if he's aggressive, entitled, or ignoring her — not for simply wanting her.
"""


async def evaluate_message(user_id: int, text: str, llm_call) -> dict:
    """
    Score a single user message for emotional signals (no persistence, no stages).

    Args:
        user_id: User ID (for logging only)
        text: The user's message text
        llm_call: async function(prompt: str) -> str (Gemini)

    Returns:
        signals: dict with charm/respect/humor/vulgarity/pushing ints.
        Empty dict on failure so callers can fall back gracefully.
    """
    prompt = EVAL_PROMPT.format(message=text[:500])

    try:
        response = (await llm_call(prompt)).strip()
        if response.startswith("```"):
            response = response.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(response)
        signals = {
            "nsfw": bool(data.get("nsfw", False)),
            "charm": data.get("charm", 0),
            "respect": data.get("respect", 0),
            "humor": data.get("humor", 0),
            "vulgarity": data.get("vulgarity", 0),
            "pushing": data.get("pushing", 0),
        }
        logger.info(
            "Signal eval user %d: charm=%d respect=%d humor=%d vulgar=%d push=%d | %s",
            user_id,
            signals["charm"], signals["respect"], signals["humor"],
            signals["vulgarity"], signals["pushing"],
            data.get("reasoning", ""),
        )
        return signals
    except Exception as e:
        logger.warning("Signal evaluation failed for user %d: %s", user_id, e)
        return {}
