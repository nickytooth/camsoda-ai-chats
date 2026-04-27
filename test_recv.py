"""Minimal Pyrogram test — does the client receive ANY updates?"""
import logging, sys
from dotenv import load_dotenv
load_dotenv()

import os
from pyrogram import Client, filters
from pyrogram.types import Message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s",
                    stream=sys.stdout)
logger = logging.getLogger("TEST")

app = Client(
    name="aishha",
    api_id=int(os.getenv("TELEGRAM_API_ID", "0")),
    api_hash=os.getenv("TELEGRAM_API_HASH", ""),
    phone_number=os.getenv("TELEGRAM_PHONE", ""),
    workdir="data",
)

@app.on_message()
async def catch_all(client, message):
    try:
        logger.info("MESSAGE >>> chat=%s from=%s text=%s",
                    message.chat.id,
                    message.from_user.id if message.from_user else "?",
                    message.text)
        await message.reply("got it!")
    except Exception as e:
        logger.error("HANDLER ERROR: %s", e, exc_info=True)

logger.info("Starting test client... send a message to Aishha")
app.run()
