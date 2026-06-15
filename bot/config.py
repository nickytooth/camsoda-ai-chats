import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = BASE_DIR / os.getenv("DATABASE_PATH", "data/bot.db")
PERSONA_FILE = BASE_DIR / os.getenv("PERSONA_FILE", "personas/victoria.yaml")
NSFW_PERSONA_FILE = BASE_DIR / os.getenv("NSFW_PERSONA_FILE", "personas/victoria_nsfw.yaml")

# Victoria is a single, always-open persona for all sexting.
PERSONA_FILE_SEXTING = BASE_DIR / os.getenv("SINGLE_PERSONA_FILE", "personas/victoria1.yaml")
STORY_FILE = BASE_DIR / os.getenv("STORY_FILE", "stories/victoria_story.yaml")
CONTENT_CONFIG = BASE_DIR / os.getenv("CONTENT_CONFIG", "content_config.yaml")
CONTENT_DIR = BASE_DIR / os.getenv("CONTENT_DIR", "content")

# Anthropic (SFW)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

# xAI / Grok (NSFW + Story mode)
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-3")

# Google / Gemini (classification + summarization)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-2.0-flash")

# OpenAI (embeddings only)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

# Server
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

# Humanize timing (seconds)
MIN_RESPONSE_DELAY = int(os.getenv("MIN_RESPONSE_DELAY", "3"))
MAX_RESPONSE_DELAY = int(os.getenv("MAX_RESPONSE_DELAY", "10"))

# Memory settings
STM_MAX_TURNS = 18
STM_SUMMARIZE_BATCH = 10
LTM_TOP_K = 5
LTM_COMPACTION_THRESHOLD = 500

# Scoring weights for LTM retrieval
LTM_SIMILARITY_WEIGHT = 0.5
LTM_IMPORTANCE_WEIGHT = 0.3
LTM_RECENCY_WEIGHT = 0.2

# Default user ID for single-user demo
DEFAULT_USER_ID = int(os.getenv("DEFAULT_USER_ID", "1"))
