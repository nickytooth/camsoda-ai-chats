from bot.persona import Persona
from bot.time_context import get_time_prompt


async def build_prompt(
    persona: Persona,
    ltm_memories: list[dict],
    stm_messages: list[dict],
    push_hint: str | None = None,
    user_name: str | None = None,
    facts_text: str | None = None,
) -> list[dict]:
    system_parts = [persona.to_system_prompt()]

    # User's Telegram name
    if user_name:
        system_parts.append(f"The user's Telegram name is {user_name}. Use it naturally sometimes.")

    # Time-of-day context (includes weather)
    system_parts.append(await get_time_prompt())

    # Structured facts (always injected, deterministic)
    if facts_text:
        system_parts.append(facts_text)

    # LTM memories
    if ltm_memories:
        mem_lines = ["What you remember about this person:"]
        for mem in ltm_memories:
            mem_lines.append(f"- {mem['content']}")
        system_parts.append("\n".join(mem_lines))
    else:
        system_parts.append("You don't know anything about this person yet. Get to know them naturally.")

    # Soft-push hint (injected by engagement system)
    if push_hint:
        system_parts.append(f"IMPORTANT FOR THIS REPLY: {push_hint}")

    system_text = "\n\n".join(system_parts)

    messages = [{"role": "system", "content": system_text}]
    for msg in stm_messages:
        messages.append({"role": msg["role"], "content": msg["content"]})

    return messages
