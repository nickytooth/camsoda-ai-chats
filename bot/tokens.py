"""Token balance for the pay-to-see photo economy.

Each user has a token balance (starting at STARTING_TOKENS). Unlocking one of
Victoria's blurred selfies costs PHOTO_UNLOCK_COST. A demo "Get more" grant adds
TOPUP_AMOUNT. Balances live in the `user_tokens` table.
"""

import logging

from bot.config import STARTING_TOKENS, TOPUP_AMOUNT
from bot.memory.db import get_connection

logger = logging.getLogger(__name__)


async def ensure_account(user_id: int) -> None:
    """Create the user's token row (seeded with STARTING_TOKENS) if missing."""
    conn = await get_connection()
    try:
        await conn.execute(
            "INSERT INTO user_tokens (user_id, balance) VALUES (?, ?) "
            "ON CONFLICT (user_id) DO NOTHING",
            (user_id, STARTING_TOKENS),
        )
        await conn.commit()
    finally:
        await conn.close()


async def get_balance(user_id: int) -> int:
    """Return the user's current balance, creating the account if needed."""
    await ensure_account(user_id)
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "SELECT balance FROM user_tokens WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return int(row["balance"]) if row else 0
    finally:
        await conn.close()


async def spend(user_id: int, amount: int) -> int | None:
    """Atomically deduct `amount` if the balance covers it.

    Returns the new balance on success, or None if there aren't enough tokens.
    """
    await ensure_account(user_id)
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "UPDATE user_tokens SET balance = balance - ? "
            "WHERE user_id = ? AND balance >= ? RETURNING balance",
            (amount, user_id, amount),
        )
        row = await cursor.fetchone()
        await conn.commit()
        return int(row["balance"]) if row else None
    finally:
        await conn.close()


async def top_up(user_id: int, amount: int = TOPUP_AMOUNT) -> int:
    """Grant `amount` tokens (demo 'Get more'). Returns the new balance."""
    await ensure_account(user_id)
    conn = await get_connection()
    try:
        cursor = await conn.execute(
            "UPDATE user_tokens SET balance = balance + ? WHERE user_id = ? RETURNING balance",
            (amount, user_id),
        )
        row = await cursor.fetchone()
        await conn.commit()
        return int(row["balance"]) if row else amount
    finally:
        await conn.close()
