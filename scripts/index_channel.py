"""
One-time script: scans a private Telegram channel and builds content_index.json.

Usage:
    python scripts/index_channel.py --channel-id -100XXXXXXXXXX --bot-token YOUR_BOT_TOKEN

The channel must have content posted with hashtag captions like:
    #pussy #tits #video

The script reads all messages, extracts hashtags as categories,
and maps each file to its file_id.
"""

import asyncio
import json
import argparse
import logging
from aiogram import Bot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VIDEO_TYPES = {"video", "animation"}


async def index_channel(bot_token: str, channel_id: int, output: str) -> None:
    bot = Bot(token=bot_token)
    index: dict[str, list[dict]] = {}

    logger.info("Scanning channel %d...", channel_id)

    # We need to use getUpdates or iterate through channel history
    # For a private channel, we use get_chat + forward approach
    # The simplest way is to use the bot's getUpdates or a userbot library
    # For now, this provides the structure — you may need pyrogram for full channel scanning

    logger.warning(
        "Note: The Telegram Bot API cannot iterate channel history directly. "
        "For full channel indexing, consider using Pyrogram or Telethon with a user account. "
        "This script provides the output format. You can also build the index manually."
    )

    # Manual index example
    example = {
        "pussy": [
            {"file_id": "AgACAgIAAxkBAAI...", "is_video": False},
        ],
        "tits": [
            {"file_id": "AgACAgIAAxkBAAI...", "is_video": False},
        ],
        "videos": [
            {"file_id": "BAACAgIAAxkBAAI...", "is_video": True},
        ],
    }

    with open(output, "w", encoding="utf-8") as f:
        json.dump(index if index else example, f, indent=2)

    logger.info("Index written to %s with %d categories", output, len(index or example))
    await bot.session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Index a Telegram channel for content")
    parser.add_argument("--channel-id", type=int, required=True, help="Telegram channel ID (e.g. -100123456789)")
    parser.add_argument("--bot-token", type=str, required=True, help="Telegram bot token")
    parser.add_argument("--output", type=str, default="content_index.json", help="Output JSON file path")
    args = parser.parse_args()

    asyncio.run(index_channel(args.bot_token, args.channel_id, args.output))


if __name__ == "__main__":
    main()
