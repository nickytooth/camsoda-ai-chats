import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent

# PostgreSQL connection string. Railway injects DATABASE_URL automatically when a
# Postgres service is attached; locally it defaults to a dev container.
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/victoria"
)
# Victoria is a single, always-open persona for all sexting.
# The legacy SFW/NSFW persona files now live in personas/archive/ and are not loaded.
PERSONA_FILE_SEXTING = BASE_DIR / os.getenv("SINGLE_PERSONA_FILE", "personas/victoria1.yaml")
STORY_FILE = BASE_DIR / os.getenv("STORY_FILE", "stories/victoria_story.yaml")

# Authored libraries the "Hear a fantasy" / "Hear a story" cards draw from
# (same for everyone, tracked-as-shared per user in the DB). In library/ so they
# ship in git (unlike the gitignored content/).
FANTASIES_FILE = BASE_DIR / os.getenv("FANTASIES_FILE", "library/fantasies.yaml")
STORIES_FILE = BASE_DIR / os.getenv("STORIES_FILE", "library/stories.yaml")

CONTENT_DIR = BASE_DIR / os.getenv("CONTENT_DIR", "content")

# Token economy (pay-to-see photos). New users start with STARTING_TOKENS and
# pay PHOTO_UNLOCK_COST to reveal each of Victoria's blurred selfies. TOPUP_AMOUNT
# is the demo "Get more" grant.
STARTING_TOKENS = int(os.getenv("STARTING_TOKENS", "1000"))
PHOTO_UNLOCK_COST = int(os.getenv("PHOTO_UNLOCK_COST", "10"))
TOPUP_AMOUNT = int(os.getenv("TOPUP_AMOUNT", "1000"))

# Probability (0..1) that an idle re-engagement double-text also attaches a
# blurred selfie, instead of being text-only. Gated by the same proactive-photo
# cooldown as the soft push (see bot/engagement.can_push_photo).
IDLE_PHOTO_CHANCE = float(os.getenv("IDLE_PHOTO_CHANCE", "0.5"))

# Where photos the USER uploads are stored on disk and served from (so they
# survive a page reload / history refresh). Lives under data/ (gitignored).
UPLOADS_DIR = BASE_DIR / os.getenv("UPLOADS_DIR", "data/uploads")

# Anthropic (SFW)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

# xAI / Grok (NSFW + Story mode)
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-3")

# Google / Gemini (classification + summarization)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-2.0-flash")
# Used only as the sexting generator fallback when Grok fails — Gemini has its
# safety filters disabled, so it can carry the explicit prompt that the SFW
# (Anthropic) model would refuse.
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")

# OpenAI (embeddings only)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

# Server
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

# Humanize timing (seconds)
# Sexting batching is a debounce: she replies this many seconds after the
# user's LAST message; every new message resets the countdown.
SEXTING_DEBOUNCE_SECONDS = float(os.getenv("SEXTING_DEBOUNCE_SECONDS", "5"))

# Memory settings
# STM_MAX_TURNS counts USER turns (one user message = one turn). Once a user has
# this many turns, the oldest messages are summarised into LTM. Note that
# get_recent_messages fetches up to STM_MAX_TURNS * 2 rows (user + assistant).
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
