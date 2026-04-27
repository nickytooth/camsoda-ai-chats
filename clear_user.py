import asyncio
from bot.memory.db import get_connection


async def main():
    conn = await get_connection()
    await conn.execute("DELETE FROM messages WHERE user_id = 6019177604")
    await conn.execute("DELETE FROM memories WHERE user_id = 6019177604")
    await conn.execute("DELETE FROM sent_content WHERE user_id = 6019177604")
    await conn.execute("DELETE FROM pending_unlocks WHERE user_id = 6019177604")
    await conn.commit()
    print("Cleared all memory for user 6019177604")
    await conn.close()


asyncio.run(main())
