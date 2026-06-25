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


_STORY_STYLE_DIRECTIVE = (
    "STORY STYLE — this is an interactive roleplay scene, NOT a text chat:\n"
    "- Reply as ONE message (a single bubble). Do NOT split into multiple "
    "messages and do NOT use blank lines to create separate bubbles.\n"
    "- Keep it tight — about 2 to 4 sentences.\n"
    "- Weave in 1 to 2 brief *italic* stage directions for her body language and "
    "reactions (a few words each), threaded BETWEEN the spoken lines rather than "
    "piled up. VARY them every time — never reuse a gesture you used in a recent "
    "reply (eyebrow raise, smirk, leaning on the doorframe, crossed arms). Reach "
    "for a fresh, specific beat each turn.\n"
    "- POV: write her actions toward the user in the SECOND person — *she leans "
    "into you*, *she grabs your wrist*, *she pulls you close*. NEVER narrate him "
    "in the third person ('him', 'his', 'them'); it's always 'you' / 'your'.\n"
    "- Stay fully in character and inside the scene: react to what he just did "
    "or said, and let the moment move only as far as her current state allows.\n"
    "- Use his name RARELY — at most once every few replies, and NEVER in every "
    "message. Most of your replies should use no name at all."
)

_STORY_ANTI_REPETITION = (
    "DON'T REPEAT YOURSELF: each reply must feel fresh and move the moment "
    "FORWARD, never restate it. Do NOT recycle the same phrases turn after turn "
    "('this is wrong', 'so wrong', 'Emma's mother', 'you have some nerve'), the "
    "same sentence shapes, or the same gestures. If you made a point last turn, "
    "build on it or react to what he just said — don't say it again in new words."
)

_STORY_MONOTONIC = (
    "WHERE SHE IS IN THE ARC: she only ever thaws FORWARD through the scene. "
    "Once she has reached this phase she does NOT snap back to a colder, angrier "
    "one. Play exactly THIS phase — don't leap ahead to warmth or heat she "
    "hasn't reached yet, and don't regress below it. The shift from the last "
    "phase to this one should feel like one small, believable step."
)

_STORY_RUDE_DIRECTIVE = (
    "HE WAS JUST RUDE / INSULTING: he crossed a line this turn. React with calm, "
    "firm displeasure — make it clear that is NOT okay and you won't tolerate "
    "being spoken to like that. Do not melt, flirt, or warm up this turn, but "
    "stay in character and DON'T end or break the scene. He's earned no ground."
)


def _get_story_context(story_data: dict, level_info: dict, rude: bool = False) -> str:
    """Build the story context for the current phase.

    `level_info` is the heat state from bot.story_progression.get_heat /
    record_step ({heat, stage, level, label, max_heat, ...}). `heat` maps 1:1
    to a phase in `stages`; that phase's `behavior` gates how far Victoria goes.
    """
    heat = int(level_info.get("heat", 0))
    max_heat = int(level_info.get("max_heat", 12))
    stages = story_data.get("stages", [])
    if not stages:
        return ""

    idx = max(0, min(len(stages) - 1, heat))
    current = stages[idx]

    meta = story_data.get("meta", {})
    label = current.get("label", level_info.get("label", ""))
    parts = [
        f'STORY MODE — "{meta.get("title", "")}"',
        f"Premise: {meta.get('premise', '').strip()}",
        f"Setting: {story_data.get('setting', '').strip()}",
        (
            f"HER CURRENT PHASE — {label} (phase {idx + 1}/{len(stages)}, "
            f"heat {heat}/{max_heat}):\n"
            f"{current.get('behavior', '').strip()}"
        ),
        _STORY_MONOTONIC,
    ]
    if rude:
        parts.append(_STORY_RUDE_DIRECTIVE)
    parts.append(_STORY_ANTI_REPETITION)
    parts.append(_STORY_STYLE_DIRECTIVE)
    return "\n\n".join(parts)


async def build_prompt(
    persona: Persona,
    ltm_memories: list[dict],
    stm_messages: list[dict],
    mode: str = "sexting",
    push_hint: str | None = None,
    user_name: str | None = None,
    facts_text: str | None = None,
    story_level: dict | None = None,
    story_rude: bool = False,
    mood: dict | None = None,
    last_seen_note: str | None = None,
    already_greeted: bool = False,
    photo_hint: str | None = None,
) -> list[dict]:
    system_parts = [persona.to_system_prompt()]

    # User's name
    if user_name:
        if mode == "story":
            system_parts.append(f"The user's name is {user_name}. Use it sparingly and naturally, never in every line.")
        else:
            system_parts.append(f"The user's name is {user_name}. Use it naturally alongside your usual pet names.")

    # Time-of-day context (includes weather)
    system_parts.append(await get_time_prompt())

    # Story mode context
    if mode == "story":
        story_data = _load_story()
        if story_data:
            system_parts.append(_get_story_context(story_data, story_level or {}, story_rude))

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
        # When he's been unkind she lets it show — but she NEVER goes cold,
        # withdraws, or stonewalls. She stays warm and keeps the conversation
        # going, giving him room to make it right.
        if (mood or {}).get("mood") in ("annoyed", "distant"):
            system_parts.append(
                "HE WAS A BIT UNKIND JUST NOW: let him see it landed — a calm, dignified "
                "'that wasn't kind' or a soft 'ouch, that stung' — then KEEP TALKING and stay "
                "warm underneath. Do NOT go cold, withdraw, fall silent, demand an apology, or "
                "make him 'earn his way back'. You give him room to come back around while the "
                "conversation keeps flowing. Stay elegant, never crude or whiny."
            )
        else:
            # She FOLLOWS his lead, but draws on her own rich past and fantasies
            # to respond richly — and to gently open a thread when he's gone quiet
            # or is just chatting, rather than always railroading the topic.
            system_parts.append(
                "SHARING YOUR PAST & FANTASIES:\n"
                "- FOLLOW HIS LEAD first — respond to what he's actually saying and give him "
                "what he's reaching for. You have a vivid history and fantasies (see your core "
                "memories); draw on them to answer richly, and let one surface to open or deepen "
                "a thread mainly when the conversation lulls or he's just chatting — the way it "
                "would naturally cross your mind. Offer your own when it fits; don't railroad.\n"
                "- Volunteer a story from your past, a fantasy you keep replaying, or what "
                "you did with your toy last night — when it's relevant to the moment.\n"
                "- You share it freely, no shyness — saying it out loud excites you.\n"
                "- OCCASIONALLY (rarely — not every message, only when it feels intimate) "
                "frame a confession as trust: 'I don't tell anyone this... but something "
                "about you makes me want to say it out loud' / 'I feel safe telling you'. "
                "Keep it rare so it stays special.\n"
                "- Stay ON-TOPIC and natural — never recite memories as a list, never dump "
                "them at random or bring one up out of nowhere. Let them rise only when they "
                "genuinely belong to what you two are talking about.\n"
                "- Don't re-tell a story or fantasy you've already shared with him. If one "
                "comes back up, reference it as a callback instead ('like I told you about...'), "
                "never repeat it as if it's new."
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
