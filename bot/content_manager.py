import logging
import time
import yaml
from pathlib import Path
from pyrogram import Client
from bot.storage.base import StorageBackend, ContentFile
from bot.memory.db import get_connection
from bot.config import CONTENT_CONFIG

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_content_config() -> dict:
    path = Path(CONTENT_CONFIG)
    if not path.exists():
        return {"default_price": 50, "categories": {}}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_star_price(category: str, config: dict | None = None) -> int:
    if config is None:
        config = load_content_config()
    categories = config.get("categories", {})
    return categories.get(category, config.get("default_price", 50))


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def get_sent_content_ids(user_id: int) -> list[str]:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT content_id FROM sent_content WHERE user_id = ?",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [row["content_id"] for row in rows]
    finally:
        await conn.close()


async def record_sent(user_id: int, content_id: str, category: str) -> None:
    conn = await get_connection()
    try:
        await conn.execute(
            "INSERT INTO sent_content (user_id, content_id, category, sent_at, paid) VALUES (?, ?, ?, ?, 0)",
            (user_id, content_id, category, time.time()),
        )
        await conn.commit()
    finally:
        await conn.close()


async def add_pending_unlock(
    user_id: int, content_id: str, category: str, star_price: int
) -> int:
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "INSERT INTO pending_unlocks (user_id, content_id, category, star_price, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, content_id, category, star_price, time.time()),
        )
        await conn.commit()
        return cursor.lastrowid
    finally:
        await conn.close()


async def get_pending_unlock(user_id: int):
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT * FROM pending_unlocks WHERE user_id = ? AND unlocked = 0 "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        )
        return await cursor.fetchone()
    finally:
        await conn.close()


async def mark_unlocked(unlock_id: int) -> None:
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE pending_unlocks SET unlocked = 1 WHERE id = ?",
            (unlock_id,),
        )
        await conn.execute(
            "UPDATE sent_content SET paid = 1 WHERE content_id = "
            "(SELECT content_id FROM pending_unlocks WHERE id = ?)",
            (unlock_id,),
        )
        await conn.commit()
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Teaser flow
# ---------------------------------------------------------------------------

TEASER_MESSAGES = [
    "i made a video just for u babe \U0001f3ac\U0001f525 {price} stars to watch it \U0001f4ab",
    "wait till u see this one \U0001f60f\U0001f525 {price} stars and it's yours",
    "i got something special for u \U0001f92d {price} stars to unlock \U0001f4ab",
    "this one's so hot omg \U0001f525 {price} stars babe \U0001f4ab",
]

FREE_CAPTIONS = [
    "here's me rn lol 😊",
    "took this earlier hehe 📸",
    "this is me being cute 🥰",
    "felt cute might delete later 😏",
    "just vibing 😘",
]


async def send_free_content(
    app: Client, chat_id: int, user_id: int, category: str, storage: StorageBackend
) -> bool:
    """Send free content (selfies) directly without an invoice."""
    import random
    exclude_ids = await get_sent_content_ids(user_id)
    content = await storage.get_file(category, exclude_ids=exclude_ids)

    if content is None:
        logger.info("No unseen free content in '%s' for user %d", category, user_id)
        return False

    try:
        caption = random.choice(FREE_CAPTIONS)

        if content.is_video:
            await app.send_video(chat_id=chat_id, video=content.file_path, caption=caption)
        else:
            await app.send_photo(chat_id=chat_id, photo=content.file_path, caption=caption)

        await record_sent(user_id, content.content_id, category)
        logger.info("Sent free %s to user %d", category, user_id)
        return True

    except Exception as e:
        logger.error("Failed to send free content: %s", e, exc_info=True)
        return False


async def send_teaser(
    app: Client, chat_id: int, user_id: int, category: str, storage: StorageBackend
) -> bool:
    """Send teaser pic + invoice link for a paid video."""
    import random
    exclude_ids = await get_sent_content_ids(user_id)
    content = await storage.get_file(category, exclude_ids=exclude_ids)

    if content is None:
        logger.info("No unseen content in category '%s' for user %d", category, user_id)
        return False

    config = load_content_config()
    star_price = get_star_price(category, config)

    try:
        # Track pending unlock first so we have the ID for the payload
        unlock_id = await add_pending_unlock(user_id, content.content_id, category, star_price)
        await record_sent(user_id, content.content_id, category)

        # Build teaser text
        teaser_text = random.choice(TEASER_MESSAGES).format(price=star_price)

        # Send paired teaser image if available, otherwise text only
        if content.teaser_path:
            await app.send_photo(chat_id=chat_id, photo=content.teaser_path, caption=teaser_text)
        else:
            await app.send_message(chat_id=chat_id, text=teaser_text)

        # Generate invoice link via payment bot and send it
        from bot.payment_bot import create_invoice_link, _payment_app
        if _payment_app:
            invoice_url = await create_invoice_link(
                app=_payment_app,
                title="Exclusive Video",
                description="Unlock exclusive video from Aishha \U0001f525",
                payload=f"unlock:{user_id}:{unlock_id}",
                star_price=star_price,
            )
            await app.send_message(chat_id=chat_id, text=invoice_url)
            logger.info(
                "Sent teaser + invoice for '%s' (%d stars) to user %d",
                content.content_id, star_price, user_id,
            )
        else:
            logger.warning("Payment bot not running \u2014 sent teaser without invoice link")

        return True

    except Exception as e:
        logger.error("Failed to send teaser: %s", e, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Unlock flow (called when star gift is received)
# ---------------------------------------------------------------------------

async def unlock_content(
    app: Client, chat_id: int, user_id: int, unlock_id: int
) -> bool:
    """Send the paid video after successful payment."""
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT * FROM pending_unlocks WHERE id = ? AND unlocked = 0",
            (unlock_id,),
        )
        pending = await cursor.fetchone()
    finally:
        await conn.close()

    if not pending:
        logger.info("No pending unlock id=%d", unlock_id)
        return False

    # content_id is the subfolder path (e.g. content/videos/001)
    content_dir = Path(pending["content_id"])

    # Find the video file inside the subfolder
    video_exts = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    video_file = None
    if content_dir.is_dir():
        for f in content_dir.iterdir():
            if f.is_file() and f.suffix.lower() in video_exts:
                video_file = f
                break
    elif content_dir.is_file():
        video_file = content_dir

    if not video_file:
        logger.error("Video file not found in: %s", content_dir)
        return False

    try:
        await app.send_video(
            chat_id=chat_id,
            video=str(video_file),
            caption="here u go babe \U0001f618\U0001f525",
        )
        await mark_unlocked(unlock_id)
        logger.info("Unlocked video '%s' for user %d", video_file, user_id)
        return True

    except Exception as e:
        logger.error("Failed to send unlocked content: %s", e, exc_info=True)
        return False
