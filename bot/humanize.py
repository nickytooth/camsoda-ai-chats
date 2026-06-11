import asyncio
import random
import logging
from pyrogram import Client
from pyrogram.enums import ChatAction
from bot.config import MIN_RESPONSE_DELAY, MAX_RESPONSE_DELAY

logger = logging.getLogger(__name__)

TYPING_CHARS_PER_SEC = 45


async def simulate_human_delay(app: Client, chat_id: int, response_text: str) -> None:
    read_delay = random.uniform(MIN_RESPONSE_DELAY, MAX_RESPONSE_DELAY)
    logger.info("Simulating read delay: %.1fs for chat %d", read_delay, chat_id)
    await asyncio.sleep(read_delay)

    typing_duration = len(response_text) / TYPING_CHARS_PER_SEC
    typing_duration = min(typing_duration, 8.0)
    typing_duration = max(typing_duration, 1.5)

    await app.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await asyncio.sleep(typing_duration)


def _clean_text(text: str) -> str:
    """Remove m-dashes and clean up output."""
    return text.replace("—", "-").replace("–", "-")


def split_message(text: str) -> list[str]:
    """Split on newlines into separate messages."""
    text = _clean_text(text)

    # Split on double or single newlines
    parts = [p.strip() for p in text.split("\n") if p.strip()]

    if len(parts) <= 1:
        return [text.strip()]

    return parts


async def typing_only_delay(app: Client, chat_id: int, text: str) -> None:
    """Just typing simulation, no read delay."""
    typing_duration = len(text) / TYPING_CHARS_PER_SEC
    typing_duration = min(typing_duration, 8.0)
    typing_duration = max(typing_duration, 1.5)
    await app.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await asyncio.sleep(typing_duration)


def _bubble_typing_delay(text: str) -> float:
    """Calculate a realistic typing delay based on message length."""
    length = len(text)
    if length < 30:
        return random.uniform(2.0, 4.0)
    elif length < 80:
        return random.uniform(3.0, 6.0)
    else:
        return random.uniform(5.0, 9.0)


async def send_human_like(app: Client, chat_id: int, text: str, skip_read_delay: bool = False) -> None:
    parts = split_message(text)

    for i, part in enumerate(parts):
        if i == 0:
            if skip_read_delay:
                # First bubble: typing indicator scaled to full response
                typing_duration = _bubble_typing_delay(part)
                await app.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                await asyncio.sleep(typing_duration)
            else:
                await simulate_human_delay(app, chat_id, text)
        else:
            # Per-bubble delay: length-scaled, typing indicator each time
            pause = _bubble_typing_delay(part)
            await app.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            await asyncio.sleep(pause)

        await app.send_message(chat_id=chat_id, text=part)
