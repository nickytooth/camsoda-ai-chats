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

TEASER_CAPTION_PROMPT = """You are Aishha. You're about to send a teaser photo for a paid video.
The teaser photo shows: {image_description}
Write a short, flirty caption (1 sentence max) that matches the photo and teases what they'll get.
Mention that it costs {price} stars to unlock.
Match your usual texting style — lowercase, casual, maybe one emoji max.
Do NOT sound like a sales pitch. Sound like a girl teasing someone she's flirting with.
Return ONLY the caption text, nothing else."""

FREE_CAPTION_PROMPT = """You are Aishha. You're about to send a free selfie.
The photo shows: {image_description}
Write a short, casual caption (1 sentence max) that matches what's in the photo.
Match your usual texting style — lowercase, casual, maybe one emoji max.
Keep it natural and low-effort, not try-hard.
Return ONLY the caption text, nothing else."""

TAG_SELECTION_PROMPT = """Given this conversation, which selfie setting fits best?

Recent messages:
{context}

Available tags: {tags}

Reply with ONLY the single best tag from the list above. No explanation."""


SELFIE_COOLDOWN_SECONDS = 14400  # 4 hours between free selfies per user


async def send_free_content(
    app: Client, chat_id: int, user_id: int, category: str, storage: StorageBackend,
    llm_call=None, image_describe=None, recent_messages: list[dict] | None = None,
    classifier_call=None,
) -> bool:
    """Send free content (selfies) directly without an invoice."""
    from bot.humanize import typing_only_delay
    from bot.time_context import get_preferred_tags

    # Enforce cooldown: max 1 free selfie per 4 hours per user
    if category == "selfies":
        conn = await get_connection()
        try:
            cursor = await conn.execute(
                "SELECT MAX(sent_at) as last_sent FROM sent_content "
                "WHERE user_id = ? AND category = 'selfies' AND paid = 0",
                (user_id,),
            )
            row = await cursor.fetchone()
            if row and row["last_sent"] and (time.time() - row["last_sent"]) < SELFIE_COOLDOWN_SECONDS:
                logger.info("Selfie cooldown active for user %d (%.0f min remaining)",
                            user_id, (SELFIE_COOLDOWN_SECONDS - (time.time() - row["last_sent"])) / 60)
                return False
        finally:
            await conn.close()

    exclude_ids = await get_sent_content_ids(user_id)

    # Pick the best tag based on conversation context + time of day
    chosen_tag = None
    if category == "selfies":
        available_tags = await storage.get_available_tags(category)
        if available_tags and classifier_call and recent_messages:
            try:
                context_lines = []
                for msg in (recent_messages or [])[-6:]:
                    prefix = "User" if msg["role"] == "user" else "Aishha"
                    context_lines.append(f"{prefix}: {msg['content'][:100]}")
                context = "\n".join(context_lines) if context_lines else "(new conversation)"

                prompt = TAG_SELECTION_PROMPT.format(
                    context=context, tags=", ".join(available_tags)
                )
                raw = (await classifier_call(prompt)).strip().lower()
                if raw in available_tags:
                    chosen_tag = raw
                    logger.info("Tag selected by LLM: %s", chosen_tag)
            except Exception as e:
                logger.warning("Tag selection failed: %s", e)

        # Fallback to time-based preference if no LLM match
        if not chosen_tag and available_tags:
            for pref in get_preferred_tags():
                if pref in available_tags:
                    chosen_tag = pref
                    logger.info("Tag selected by time preference: %s", chosen_tag)
                    break

    content = await storage.get_file(category, exclude_ids=exclude_ids, tag=chosen_tag)

    if content is None:
        logger.info("No unseen free content in '%s' for user %d", category, user_id)
        return False

    try:
        # Analyze the image to get a description for context-aware captioning
        image_description = "a selfie"
        if image_describe and content.file_path:
            try:
                with open(content.file_path, "rb") as f:
                    image_bytes = f.read()
                image_description = await image_describe(image_bytes)
                logger.info("Content image description: %s", image_description[:80])
            except Exception as e:
                logger.warning("Image analysis for caption failed: %s", e)

        # Generate caption with LLM or fall back
        caption = "here u go"
        if llm_call:
            try:
                prompt = FREE_CAPTION_PROMPT.format(image_description=image_description)
                caption = (await llm_call(prompt)).strip().strip('"')
            except Exception as e:
                logger.warning("Caption generation failed, using fallback: %s", e)

        # Typing delay only (read delay already handled by batch system)
        await typing_only_delay(app, chat_id, caption)

        if content.is_video:
            await app.send_video(chat_id=chat_id, video=content.file_path, caption=caption)
        else:
            await app.send_photo(chat_id=chat_id, photo=content.file_path, caption=caption)

        await record_sent(user_id, content.content_id, category)
        # Return details for STM logging
        from pathlib import Path
        fname = Path(content.content_id).name if content.content_id else "unknown"
        tag = fname.split("_")[0] if "_" in fname else "general"
        logger.info("Sent free %s to user %d: %s (tag=%s)", category, user_id, fname, tag)
        return f"{fname}|{tag}|free|{caption[:60]}"

    except Exception as e:
        logger.error("Failed to send free content: %s", e, exc_info=True)
        return False


async def send_teaser(
    app: Client, chat_id: int, user_id: int, category: str, storage: StorageBackend,
    llm_call=None, image_describe=None,
) -> bool:
    """Send teaser pic + invoice link for a paid video."""
    from bot.humanize import typing_only_delay
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

        # Analyze teaser image for context-aware captioning
        image_description = "a teaser preview"
        teaser_image = content.teaser_path or content.file_path
        if image_describe and teaser_image:
            try:
                with open(teaser_image, "rb") as f:
                    image_bytes = f.read()
                image_description = await image_describe(image_bytes)
                logger.info("Teaser image description: %s", image_description[:80])
            except Exception as e:
                logger.warning("Teaser image analysis failed: %s", e)

        # Generate teaser caption with LLM or fall back
        teaser_text = f"this one's for u {star_price} stars to unlock"
        if llm_call:
            try:
                prompt = TEASER_CAPTION_PROMPT.format(price=star_price, image_description=image_description)
                teaser_text = (await llm_call(prompt)).strip().strip('"')
            except Exception as e:
                logger.warning("Teaser caption generation failed, using fallback: %s", e)

        # Typing delay only (read delay already handled by batch system)
        await typing_only_delay(app, chat_id, teaser_text)

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

        from pathlib import Path
        fname = Path(content.content_id).name if content.content_id else "unknown"
        return f"{fname}|teaser|{star_price} stars"

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

        # Record in STM so Aishha knows she sent the video
        from bot.memory.stm import add_message
        await add_message(user_id, "assistant", "[sent unlocked video after payment]")

        logger.info("Unlocked video '%s' for user %d", video_file, user_id)
        return True

    except Exception as e:
        logger.error("Failed to send unlocked content: %s", e, exc_info=True)
        return False
