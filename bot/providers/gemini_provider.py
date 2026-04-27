from google import genai
from bot.providers.base import LLMProvider
from bot.config import GOOGLE_API_KEY, GOOGLE_MODEL

_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=GOOGLE_API_KEY)
    return _client


class GeminiProvider(LLMProvider):
    async def generate(self, messages: list[dict]) -> str:
        client = _get_client()

        system_msg = ""
        contents = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                role = "user" if msg["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        config = genai.types.GenerateContentConfig(
            system_instruction=system_msg if system_msg else None,
            max_output_tokens=1024,
        )

        response = await client.aio.models.generate_content(
            model=GOOGLE_MODEL,
            contents=contents,
            config=config,
        )
        return response.text

    async def generate_simple(self, prompt: str) -> str:
        client = _get_client()
        response = await client.aio.models.generate_content(
            model=GOOGLE_MODEL,
            contents=prompt,
        )
        return response.text
