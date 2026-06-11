import asyncio
import logging
import yaml
from pathlib import Path
from pyrogram import Client
from bot.config import (
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    TELEGRAM_PHONE,
    PAYMENT_BOT_TOKEN,
    CONTENT_CONFIG,
    NSFW_PERSONA_FILE,
)
from bot.memory.db import init_db
from bot.persona import load_persona
from bot.providers.anthropic_provider import AnthropicProvider
from bot.providers.gemini_provider import GeminiProvider
from bot.providers.grok_provider import GrokProvider
from bot.handlers import register_handlers, setup
from bot.storage.base import StorageBackend

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Keep references for the payment callback
_userbot: Client | None = None
_storage: StorageBackend | None = None


def _create_storage() -> StorageBackend:
    config_path = Path(CONTENT_CONFIG)
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    backend = config.get("storage_backend", "local")

    if backend == "telegram":
        from bot.storage.telegram_storage import TelegramStorage
        index_path = config.get("telegram_index_path", "content_index.json")
        return TelegramStorage(index_path=index_path)

    elif backend == "dropbox":
        from bot.storage.dropbox_storage import DropboxStorage
        return DropboxStorage(
            app_key=config.get("dropbox_app_key", ""),
            app_secret=config.get("dropbox_app_secret", ""),
            refresh_token=config.get("dropbox_refresh_token", ""),
            root_folder=config.get("dropbox_root_folder", "/bot_content"),
        )

    else:
        from bot.storage.local import LocalStorage
        content_path = config.get("local_content_path", "./content")
        return LocalStorage(root_path=content_path)


async def _on_payment(user_id: int, unlock_id: int) -> None:
    """Called by payment bot when a Star payment is confirmed."""
    if not _userbot:
        logger.error("Userbot not available for content delivery")
        return

    from bot.content_manager import unlock_content
    await unlock_content(_userbot, user_id, user_id, unlock_id)


def create_userbot(storage: StorageBackend) -> Client:
    logger.info("Loading persona...")
    persona = load_persona()
    logger.info("Persona loaded: %s", persona.name)

    nsfw_persona = None
    if Path(NSFW_PERSONA_FILE).exists():
        nsfw_persona = load_persona(NSFW_PERSONA_FILE)
        logger.info("NSFW persona loaded from %s", NSFW_PERSONA_FILE)

    logger.info("Initializing LLM providers...")
    sfw_provider = AnthropicProvider()
    nsfw_provider = GeminiProvider("gemini-2.5-flash")
    classifier_provider = GeminiProvider()
    vision_provider = GrokProvider()

    setup(
        persona=persona,
        sfw_provider=sfw_provider,
        nsfw_provider=nsfw_provider,
        classifier_provider=classifier_provider,
        storage=storage,
        vision_provider=vision_provider,
        nsfw_persona=nsfw_persona,
    )

    app = Client(
        name="aishha",
        api_id=TELEGRAM_API_ID,
        api_hash=TELEGRAM_API_HASH,
        phone_number=TELEGRAM_PHONE,
        workdir="data",
    )

    register_handlers(app)
    logger.info("Userbot handlers registered")
    return app


async def main():
    global _userbot, _storage

    logger.info("Initializing database...")
    await init_db()

    logger.info("Initializing storage backend...")
    _storage = _create_storage()

    # --- Userbot ---
    _userbot = create_userbot(_storage)

    # --- Payment bot ---
    payment_task = None
    if PAYMENT_BOT_TOKEN:
        from bot.payment_bot import create_payment_bot, set_payment_callback
        payment_app = create_payment_bot()
        set_payment_callback(_on_payment)
        logger.info("Starting payment bot...")
        await payment_app.initialize()
        await payment_app.start()
        payment_task = asyncio.create_task(
            payment_app.updater.start_polling(drop_pending_updates=True)
        )
        logger.info("Payment bot polling started")
    else:
        logger.warning("PAYMENT_BOT_TOKEN not set — running without payment support")

    # --- Start userbot with auto-reconnect ---
    from bot.reengagement import reengage_loop

    reengage_task = None
    while True:
        try:
            logger.info("Starting userbot...")
            await _userbot.start()
            logger.info("Userbot started. Waiting for messages...")

            reengage_task = asyncio.create_task(reengage_loop(_userbot))
            logger.info("Re-engagement loop started")

            await asyncio.Event().wait()

        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down (user requested)...")
            break

        except Exception as e:
            logger.error("Connection lost: %s", e, exc_info=True)
            logger.info("Reconnecting in 10 seconds...")

            if reengage_task:
                reengage_task.cancel()
                reengage_task = None

            try:
                await _userbot.stop()
            except Exception:
                pass

            await asyncio.sleep(10)
            continue

    # --- Cleanup ---
    if reengage_task:
        reengage_task.cancel()
    try:
        await _userbot.stop()
    except Exception:
        pass
    if payment_task and PAYMENT_BOT_TOKEN:
        payment_app.updater.stop()
        await payment_app.stop()
        await payment_app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
