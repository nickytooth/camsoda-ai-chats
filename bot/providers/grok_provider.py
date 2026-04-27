from openai import AsyncOpenAI
from bot.providers.base import LLMProvider
from bot.config import XAI_API_KEY, XAI_MODEL

_client = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")
    return _client


class GrokProvider(LLMProvider):
    async def generate(self, messages: list[dict]) -> str:
        client = _get_client()
        response = await client.chat.completions.create(
            model=XAI_MODEL,
            messages=messages,
            max_tokens=256,
        )
        return response.choices[0].message.content

    async def generate_simple(self, prompt: str) -> str:
        client = _get_client()
        response = await client.chat.completions.create(
            model=XAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        return response.choices[0].message.content
