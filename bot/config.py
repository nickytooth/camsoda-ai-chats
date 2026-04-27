import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = BASE_DIR / os.getenv("DATABASE_PATH", "data/bot.db")
PERSONA_FILE = BASE_DIR / os.getenv("PERSONA_FILE", "personas/viv.yaml")
CONTENT_CONFIG = BASE_DIR / os.getenv("CONTENT_CONFIG", "content_config.yaml")

# Telegram (userbot)
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "")

# Anthropic (SFW)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

# xAI / Grok (NSFW)
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-3")

# Google / Gemini (classification + summarization)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-2.0-flash")

# OpenAI (embeddings only)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

# Payment bot
PAYMENT_BOT_TOKEN = os.getenv("PAYMENT_BOT_TOKEN", "")

# Humanize timing
MIN_RESPONSE_DELAY = int(os.getenv("MIN_RESPONSE_DELAY", "5"))
MAX_RESPONSE_DELAY = int(os.getenv("MAX_RESPONSE_DELAY", "5"))

# Memory settings
STM_MAX_TURNS = 18
STM_SUMMARIZE_BATCH = 10
LTM_TOP_K = 5
LTM_COMPACTION_THRESHOLD = 500

# Scoring weights for LTM retrieval
LTM_SIMILARITY_WEIGHT = 0.5
LTM_IMPORTANCE_WEIGHT = 0.3
LTM_RECENCY_WEIGHT = 0.2
