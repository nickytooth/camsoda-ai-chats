import yaml
from pathlib import Path
from bot.persona import Persona
from bot.time_context import get_time_prompt
from bot.mood import format_mood_for_prompt
from bot.config import STORY_FILE


def _load_story() -> dict | None:
    """Load story chapters from YAML file."""
    path = Path(STORY_FILE)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_story_context(story_data: dict, chapter: int) -> str:
    """Build story context for the current chapter."""
    chapters = story_data.get("chapters", [])
    current = None
    for ch in chapters:
        if ch.get("id") == chapter:
            current = ch
            break
    if not current:
        current = chapters[0] if chapters else None
    if not current:
        return ""

    beats = "\n".join(f"- {b}" for b in current.get("narrative_beats", []))
    return (
        f"STORY MODE — Chapter {current['id']}: {current['title']}\n"
        f"Setting: {current.get('setting', '')}\n"
        f"Mood: {current.get('mood', '')}\n"
        f"Summary: {current.get('summary', '').strip()}\n"
        f"Key narrative beats to weave in naturally:\n{beats}\n\n"
        f"Stay in character. Use *italic actions* for physical descriptions and actions. "
        f"Drive the story forward while responding to the user's choices. "
        f"Don't rush — let scenes breathe. Build tension."
    )


async def build_prompt(
    persona: Persona,
    ltm_memories: list[dict],
    stm_messages: list[dict],
    mode: str = "sexting",
    push_hint: str | None = None,
    user_name: str | None = None,
    facts_text: str | None = None,
    story_chapter: int = 1,
    intimacy_stage: int = 1,
    mood: dict | None = None,
    last_seen_note: str | None = None,
    already_greeted: bool = False,
) -> list[dict]:
    system_parts = [persona.to_system_prompt()]

    # User's name
    if user_name:
        system_parts.append(f"The user's name is {user_name}. Use it naturally alongside your usual pet names.")

    # Time-of-day context (includes weather)
    system_parts.append(await get_time_prompt())

    # Story mode context
    if mode == "story":
        story_data = _load_story()
        if story_data:
            system_parts.append(_get_story_context(story_data, story_chapter))

    # Texting style — sexting mode must read like a real chat, not prose
    if mode == "sexting":
        system_parts.append(
            "TEXTING STYLE — THIS IS A REAL CHAT, NOT AN ESSAY:\n"
            "- Write like a real person texting on her phone.\n"
            "- NEVER end a message or sentence with a period. Drop the trailing period entirely.\n"
            "- Question marks and ellipses (...) are fine. Exclamation points sparingly.\n"
            "- Keep messages short and punchy — often just one line.\n"
            "- Send 1-3 short messages, each on its own line (separated by a newline) "
            "so they arrive as separate bubbles.\n"
            "- Stay elegant and witty — she's sophisticated — but casual, the way people actually text.\n"
            "- No slang ('u', 'lol'), no emojis unless rare and deliberate."
        )

    # Conversation continuity — she opened first, so she must NOT re-greet
    if mode == "sexting" and already_greeted:
        system_parts.append(
            "CONVERSATION CONTINUITY:\n"
            "- You ALREADY started this conversation with your own opening messages. "
            "Do NOT greet him again ('hello', 'hey there', 'hi darling') as if you just met.\n"
            "- React to what he just said and pick up naturally from your last messages.\n"
            "- A woman who messaged first doesn't reintroduce herself — she keeps the thread going."
        )

    # Intimacy stage instructions (sexting mode only)
    if mode == "sexting":
        stage_instructions = persona.get_stage_instructions(intimacy_stage)
        if stage_instructions:
            system_parts.append(f"=== INTIMACY STAGE {intimacy_stage}/3 ===\n{stage_instructions}")

    # Short-term mood (sexting mode only) — fast, volatile emotional colour
    if mode == "sexting":
        mood_line = format_mood_for_prompt(mood)
        if mood_line:
            system_parts.append(mood_line)

    # Time since you last spoke — lets her greet like a real person
    if last_seen_note:
        system_parts.append(last_seen_note)

    # Structured facts (always injected, deterministic)
    if facts_text:
        system_parts.append(facts_text)

    # LTM memories
    if ltm_memories:
        mem_lines = ["What you remember about this person:"]
        for mem in ltm_memories:
            mem_lines.append(f"- {mem['content']}")
        mem_lines.append(
            "If it fits the moment, bring one of these up naturally as a callback - "
            "the way a real person remembers little details. Never recite them like a list."
        )
        system_parts.append("\n".join(mem_lines))
    else:
        system_parts.append("You don't know anything about this person yet. Get to know them naturally.")

    # Soft-push hint (injected by engagement system)
    if push_hint:
        system_parts.append(f"IMPORTANT FOR THIS REPLY: {push_hint}")

    system_text = "\n\n".join(system_parts)

    messages = [{"role": "system", "content": system_text}]
    for msg in stm_messages:
        if msg["role"] in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})

    return messages
