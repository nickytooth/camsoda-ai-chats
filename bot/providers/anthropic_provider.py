from anthropic import AsyncAnthropic
from bot.providers.base import LLMProvider
from bot.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

_client = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _client


class AnthropicProvider(LLMProvider):
    async def generate(self, messages: list[dict]) -> str:
        client = _get_client()

        system_msg = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                chat_messages.append({"role": msg["role"], "content": msg["content"]})

        response = await client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=256,
            system=system_msg,
            messages=chat_messages,
        )
        return response.content[0].text

    async def generate_simple(self, prompt: str) -> str:
        client = _get_client()
        response = await client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
