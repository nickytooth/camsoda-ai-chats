import aiosqlite
from pathlib import Path
from bot.config import DATABASE_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp REAL NOT NULL,
    mode TEXT NOT NULL DEFAULT 'sexting'
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 5,
    embedding BLOB,
    created_at REAL NOT NULL,
    last_accessed REAL
);

CREATE TABLE IF NOT EXISTS sent_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    content_id TEXT NOT NULL,
    category TEXT NOT NULL,
    sent_at REAL NOT NULL,
    paid INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pending_unlocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    content_id TEXT NOT NULL,
    category TEXT NOT NULL,
    star_price INTEGER NOT NULL,
    created_at REAL NOT NULL,
    unlocked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.8,
    first_seen REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS story_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chapter INTEGER NOT NULL DEFAULT 1,
    scene INTEGER NOT NULL DEFAULT 0,
    completed_at REAL,
    chapter_score INTEGER NOT NULL DEFAULT 0,
    chapter_messages INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS engagement_state (
    user_id INTEGER PRIMARY KEY,
    nsfw_count INTEGER NOT NULL DEFAULT 0,
    total_messages INTEGER NOT NULL DEFAULT 0,
    last_push_at REAL DEFAULT 0,
    last_selfie_at REAL DEFAULT 0,
    last_message_at REAL DEFAULT 0,
    last_reengage_at REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS intimacy_state (
    user_id INTEGER PRIMARY KEY,
    stage INTEGER NOT NULL DEFAULT 1,
    flirt_score INTEGER NOT NULL DEFAULT 0,
    message_count INTEGER NOT NULL DEFAULT 0,
    last_evaluated_at REAL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_user_mode ON messages(user_id, mode);
CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
CREATE INDEX IF NOT EXISTS idx_sent_content_user ON sent_content(user_id);
CREATE INDEX IF NOT EXISTS idx_sent_content_paid ON sent_content(user_id, content_id, paid);
CREATE INDEX IF NOT EXISTS idx_pending_unlocks_user ON pending_unlocks(user_id, unlocked);
CREATE INDEX IF NOT EXISTS idx_user_facts ON user_facts(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_facts_key ON user_facts(user_id, key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_story_progress_user ON story_progress(user_id);
"""


async def get_connection() -> aiosqlite.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(DATABASE_PATH))
    conn.row_factory = aiosqlite.Row
    return conn


async def init_db() -> None:
    conn = await get_connection()
    try:
        await conn.executescript(SCHEMA)
        await conn.commit()
    finally:
        await conn.close()
