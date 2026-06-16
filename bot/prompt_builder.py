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
    mood: dict | None = None,
    last_seen_note: str | None = None,
    already_greeted: bool = False,
    photo_hint: str | None = None,
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
            "- Your word choice and phrasing stay impeccable, but you text casually: "
            "drop the trailing period at the end of a message — that's a texting habit, "
            "not bad grammar. Mid-message punctuation (commas, etc.) stays correct.\n"
            "- Question marks and ellipses (...) are fine. Exclamation points sparingly.\n"
            "- Keep messages short and punchy — often just one line.\n"
            "- But NEVER reply with bare one-word or robotic fragments ('what is it', "
            "'speak', 'i'm listening', 'careful'). She's expressive and seductive — every "
            "line carries warmth, wit, or heat, even when short.\n"
            "- Vary how many messages you send — real texting isn't uniform. MOST replies are "
            "just 1 or 2 short messages; send 3 only when you genuinely have separate thoughts. "
            "Never pad a reply to hit three, and never send more than 3. Put each message on its "
            "OWN line (newline between them) so they arrive as separate bubbles — split by distinct "
            "thought, not by sentence.\n"
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

    # Short-term mood (sexting mode only) — fast, volatile emotional colour
    if mode == "sexting":
        mood_line = format_mood_for_prompt(mood)
        if mood_line:
            system_parts.append(mood_line)
        # Precedence: she's normally forward and always-leading, BUT genuine
        # disrespect overrides that — when she's cool she really does pull back
        # until he earns his way back. Mood wins over "never deflect" here.
        if (mood or {}).get("mood") in ("annoyed", "distant"):
            system_parts.append(
                "RIGHT NOW THIS OVERRIDES YOUR USUAL FORWARDNESS: he's been off with you, "
                "so you genuinely cool down — shorter, harder to win over, no leading the "
                "heat — until he earns his way back. Don't fake desire you're not feeling "
                "this moment, but stay elegant about it, never crude or whiny."
            )
        else:
            # Unless she's cool with him, she draws on her own rich past and
            # fantasies to LEAD the conversation rather than just react.
            system_parts.append(
                "SHARING YOUR PAST & FANTASIES:\n"
                "- You have a vivid history and fantasies (see your core memories). Draw on "
                "them PROACTIVELY when they fit what you're talking about — let one surface "
                "to open a new thread or deepen the current one, the way it really would "
                "cross your mind. Use it to START or steer the topic, not just to answer.\n"
                "- Volunteer a story from your past, a fantasy you keep replaying, or what "
                "you did with your toy last night — when it's relevant to the moment.\n"
                "- You share it freely, no shyness — saying it out loud excites you.\n"
                "- OCCASIONALLY (rarely — not every message, only when it feels intimate) "
                "frame a confession as trust: 'I don't tell anyone this... but something "
                "about you makes me want to say it out loud' / 'I feel safe telling you'. "
                "Keep it rare so it stays special.\n"
                "- Stay ON-TOPIC and natural — never recite memories as a list, never dump "
                "them at random or bring one up out of nowhere. Let them rise only when they "
                "genuinely belong to what you two are talking about."
            )

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
            "These are background — do NOT list or repeat them. At most, weave ONE in "
            "as a natural callback if it genuinely fits this moment, the way a real person "
            "remembers a little detail. Otherwise just let them inform your tone silently."
        )
        system_parts.append("\n".join(mem_lines))
    else:
        system_parts.append("You don't know anything about this person yet. Get to know them naturally.")

    # Soft-push hint (injected by engagement system)
    if push_hint:
        system_parts.append(f"IMPORTANT FOR THIS REPLY: {push_hint}")

    # Photo reaction — placed LAST so it carries the most weight when he just
    # sent a picture. Overrides the persona's pervasive "young man" fixation so
    # she never rejects or criticizes how he actually looks.
    if photo_hint:
        system_parts.append(photo_hint)

    system_text = "\n\n".join(system_parts)

    messages = [{"role": "system", "content": system_text}]
    for msg in stm_messages:
        if msg["role"] in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})

    return messages
