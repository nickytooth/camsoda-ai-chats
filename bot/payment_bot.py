"""
Companion bot for handling Telegram Star payments.

This bot is invisible to users — it only generates invoice links and
processes payments. The userbot sends the invoice link in Aishha's chat,
the user pays inline, and this bot confirms the payment and signals
the userbot to send content.
"""

import asyncio
import logging
from pathlib import Path
from telegram import Update, LabeledPrice
from telegram.ext import (
    Application,
    PreCheckoutQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from bot.config import PAYMENT_BOT_TOKEN

logger = logging.getLogger(__name__)

# Global reference so content_manager can create invoice links
_payment_app: Application | None = None

# Callback for delivering content after payment — set by main.py
_on_payment_callback = None


def set_payment_callback(callback):
    """Register a callback: async fn(user_id, chat_id, content_id, is_video)"""
    global _on_payment_callback
    _on_payment_callback = callback


async def create_invoice_link(
    app: Application,
    title: str,
    description: str,
    payload: str,
    star_price: int,
) -> str:
    """Create a Telegram Stars invoice link via the Bot API."""
    prices = [LabeledPrice(label="Unlock content", amount=star_price)]
    link = await app.bot.create_invoice_link(
        title=title,
        description=description,
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=prices,
    )
    return link


async def handle_pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Always approve pre-checkout queries."""
    query = update.pre_checkout_query
    logger.info("Pre-checkout from user %d, payload=%s, amount=%d",
                query.from_user.id, query.invoice_payload, query.total_amount)
    await query.answer(ok=True)


async def handle_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process successful payment — unlock content and deliver it."""
    payment = update.message.successful_payment
    user_id = update.message.from_user.id
    chat_id = update.message.chat.id
    payload = payment.invoice_payload
    amount = payment.total_amount

    logger.info("Payment received: user=%d, amount=%d stars, payload=%s",
                user_id, amount, payload)

    # Parse payload: "unlock:<user_id>:<unlock_id>"
    try:
        parts = payload.split(":")
        if parts[0] == "unlock" and len(parts) == 3:
            orig_user_id = int(parts[1])
            unlock_id = int(parts[2])

            from bot.content_manager import mark_unlocked
            await mark_unlocked(unlock_id)
            logger.info("Marked unlock_id=%d as paid for user %d", unlock_id, orig_user_id)

            if _on_payment_callback:
                await _on_payment_callback(orig_user_id, unlock_id)
            else:
                logger.warning("No payment callback registered — content won't be delivered")
        else:
            logger.error("Unknown payload format: %s", payload)
    except Exception as e:
        logger.error("Error processing payment: %s", e, exc_info=True)


def create_payment_bot() -> Application:
    """Create and configure the payment bot application."""
    global _payment_app

    if not PAYMENT_BOT_TOKEN:
        raise ValueError("PAYMENT_BOT_TOKEN not set in .env")

    app = Application.builder().token(PAYMENT_BOT_TOKEN).build()

    app.add_handler(PreCheckoutQueryHandler(handle_pre_checkout))
    app.add_handler(MessageHandler(
        filters.SUCCESSFUL_PAYMENT,
        handle_successful_payment,
    ))

    _payment_app = app
    logger.info("Payment bot configured")
    return app
