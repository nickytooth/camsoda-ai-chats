# Telegram AI Chat Bot

A Telegram **userbot** that runs as a real Telegram account, holds conversations using AI, and sells exclusive content via Telegram Stars. It routes messages through different LLM providers based on content classification, maintains two-tier memory (short-term + long-term with vector search), and mimics human typing behavior.

---

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Telegram MTProto | pyrofork | 2.3.69 |
| Telegram Bot API (payments) | python-telegram-bot | 21.10 |
| Crypto (MTProto) | tgcrypto | 1.2.5 |
| SFW LLM | Anthropic Claude | anthropic 0.42.0 |
| NSFW LLM | xAI Grok | openai 1.58.0 (compatible API) |
| Classifier / Summarizer LLM | Google Gemini Flash | google-genai 1.14.0 |
| Embeddings | OpenAI text-embedding-3-small | openai 1.58.0 |
| Database | SQLite (async) | aiosqlite 0.20.0 |
| Vector math | numpy | 2.2.2 |
| Image processing | Pillow | 11.1.0 |
| Config | python-dotenv, PyYAML | 1.0.1, 6.0.2 |
| Cloud storage (optional) | dropbox | 12.0.2 |
| Language | Python | 3.13+ |

---

## Project Structure

```
bot/
├── main.py                # Entry point - starts userbot + payment bot + reconnect loop
├── handlers.py            # Core message processing pipeline
├── config.py              # All env vars and tunable constants
├── persona.py             # Character Bible YAML loader → system prompt
├── prompt_builder.py      # Assembles system prompt (persona + LTM + push hints + STM)
├── router.py              # SFW/NSFW classification (keyword fast-path + LLM fallback)
├── humanize.py            # Read delay, typing indicator, message splitting
├── intent.py              # LLM-based content request detection
├── content_manager.py     # Content selling: free sends, teasers, invoices, unlocks
├── payment_bot.py         # Companion bot for Telegram Star invoices
├── engagement.py          # Tracks NSFW message count, triggers soft-push hints
├── reengagement.py        # Background loop: DMs users silent for 24h+
│
├── memory/
│   ├── db.py              # SQLite schema + async connection factory
│   ├── stm.py             # Short-term memory CRUD (recent messages)
│   ├── ltm.py             # Long-term memory: store, retrieve (vector search), compact
│   ├── embeddings.py      # OpenAI embedding calls + cosine similarity
│   └── summarizer.py      # Summarizes STM batches → LTM entries via Gemini
│
├── providers/
│   ├── base.py            # Abstract LLMProvider interface
│   ├── anthropic_provider.py  # Claude (SFW conversations)
│   ├── grok_provider.py       # Grok via xAI (NSFW conversations)
│   └── gemini_provider.py     # Gemini Flash (classification, summarization, intent)
│
└── storage/
    ├── base.py            # Abstract StorageBackend + ContentFile dataclass
    ├── local.py           # Local filesystem (selfies flat, videos as subfolders)
    ├── telegram_storage.py    # Telegram channel via JSON index
    └── dropbox_storage.py     # Dropbox cloud storage

personas/
├── aishha.yaml            # Active persona: Character Bible with full identity
└── viv.yaml               # Alternative persona

content/                   # Media files (gitignored)
├── selfies/               # Free images (flat folder)
└── videos/                # Paid video bundles (numbered subfolders)

scripts/
└── index_channel.py       # One-time: indexes a Telegram channel → content_index.json

data/                      # Runtime data (gitignored)
├── bot.db                 # SQLite database
└── aishha.session         # Telegram auth session

content_config.yaml        # Storage backend selection + Star prices
.env                       # API keys and config (gitignored)
.env.example               # Template with all required variables

dump_memory.py             # Debug: prints STM + LTM to console
clear_user.py              # Debug: wipes all data for a specific user
test_recv.py               # Debug: minimal Pyrogram client to test message receipt
```

---

## Setup & Installation

### 1. Clone and install

```bash
git clone https://github.com/nickytooth/telegram-bot.git
cd telegram-bot
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your actual values:

| Variable | Description |
|----------|-------------|
| `TELEGRAM_API_ID` | Telegram app ID from [my.telegram.org](https://my.telegram.org) |
| `TELEGRAM_API_HASH` | Telegram app hash from [my.telegram.org](https://my.telegram.org) |
| `TELEGRAM_PHONE` | Phone number for the userbot account (e.g. `+1234567890`) |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude (SFW conversations) |
| `ANTHROPIC_MODEL` | Claude model name (default: `claude-sonnet-4-20250514`) |
| `XAI_API_KEY` | xAI API key for Grok (NSFW conversations) |
| `XAI_MODEL` | Grok model name (default: `grok-3`) |
| `GOOGLE_API_KEY` | Google AI API key for Gemini (classifier + summarizer) |
| `GOOGLE_MODEL` | Gemini model name (default: `gemini-2.0-flash`) |
| `OPENAI_API_KEY` | OpenAI API key (embeddings only) |
| `OPENAI_EMBEDDING_MODEL` | Embedding model (default: `text-embedding-3-small`) |
| `PERSONA_FILE` | Path to persona YAML (default: `personas/aishha.yaml`) |
| `CONTENT_CONFIG` | Path to content config (default: `content_config.yaml`) |
| `DATABASE_PATH` | SQLite DB path (default: `data/bot.db`) |
| `PAYMENT_BOT_TOKEN` | Telegram bot token from @BotFather (for Star invoices) |
| `MIN_RESPONSE_DELAY` | Minimum reply delay in seconds (default: `60`) |
| `MAX_RESPONSE_DELAY` | Maximum reply delay in seconds (default: `180`) |

### 3. Add content files

```
content/
├── selfies/
│   ├── img1.jpg
│   ├── img2.jpg
│   └── ...
└── videos/
    ├── 001/
    │   ├── teaser.jpg    # Any image file works as the teaser
    │   └── video.mp4
    ├── 002/
    │   ├── preview.png   # Filename doesn't matter, any image = teaser
    │   └── clip.mov
    └── ...
```

- **selfies/** — flat folder of images, sent for free when requested
- **videos/** — numbered subfolders, each containing one image (teaser) + one video (paid content)

### 4. First run

```bash
python -m bot.main
```

On first run, Telegram will prompt for a phone verification code in the terminal. After that, the session is saved to `data/aishha.session` and won't ask again.

### 5. Configure Star prices

Edit `content_config.yaml`:

```yaml
storage_backend: local
local_content_path: "./content"

default_price: 150
categories:
  selfies: 0      # Free
  videos: 150     # 150 Telegram Stars
```

---

## Available Commands

| Command | Description |
|---------|-------------|
| `python -m bot.main` | Start the bot (userbot + payment bot + re-engagement loop) |
| `python dump_memory.py` | Print STM and LTM contents for the test user |
| `python clear_user.py` | Wipe all memory/content/unlocks for a specific user |
| `python test_recv.py` | Minimal Pyrogram test client to verify messages arrive |
| `python scripts/index_channel.py --channel-id ID --bot-token TOKEN` | Index a Telegram channel for the channel storage backend |

---

## Architecture & Data Flow

### Message Processing Pipeline

```
User sends message
       │
       ▼
   Add to STM ──► Maybe summarize STM → LTM (every 18 user turns)
       │          Maybe compact LTM (at 500+ entries)
       ▼
   Fetch STM messages
       │
       ▼
   Intent Detection (Gemini Flash)
       │
       ├── "selfies" ──► Send free photo from content/selfies/
       ├── "videos"  ──► Send teaser image + Star invoice link
       ├── "suggest"  ──► Ask user what they want (selfie or video)
       │
       └── "none" ──► Continue to conversation
                          │
                          ▼
                   SFW/NSFW Classification
                   (keyword fast-path + Gemini fallback)
                          │
                          ├── SFW  ──► Claude (Anthropic)
                          └── NSFW ──► Grok (xAI)
                                        │
                                        ▼
                                  Build prompt:
                                  [System: persona + LTM memories + push hint]
                                  [STM: recent conversation turns]
                                        │
                                        ▼
                                  Generate response
                                        │
                                        ▼
                                  Clean text (strip m-dashes)
                                  Split into multiple messages (on newlines)
                                        │
                                        ▼
                                  Simulate read delay (60-180s)
                                  Show typing indicator
                                  Send messages (0.5-1.5s apart)
```

### Payment Flow

```
Intent = "videos"
       │
       ▼
Pick random unseen video subfolder
       │
       ▼
Send teaser image + caption with price
       │
       ▼
Generate Star invoice link (via payment companion bot)
Send invoice URL (renders as Pay button)
       │
       ▼
User taps Pay → pre_checkout_query → auto-approve
       │
       ▼
successful_payment → mark_unlocked in DB
       │
       ▼
Send actual video file via userbot
```

### Memory System

```
                    STM (SQLite: messages table)
                    ┌────────────────────────┐
                    │ Last 18 turns verbatim  │
                    │ (user + assistant msgs) │
                    └──────────┬─────────────┘
                               │ Every 18 user turns
                               │ Gemini summarizes oldest 10 msgs
                               ▼
                    LTM (SQLite: memories table)
                    ┌────────────────────────┐
                    │ Structured entries:     │
                    │ - category (fact/pref/  │
                    │   relationship/event/   │
                    │   thread)               │
                    │ - content (1-2 sentences)│
                    │ - importance (1-10)     │
                    │ - embedding (vector)    │
                    └──────────┬─────────────┘
                               │ At 500+ entries
                               │ Gemini deduplicates & merges
                               ▼
                    Compacted LTM

    Retrieval: cosine similarity (0.5) + importance (0.3) + recency (0.2)
    Top 5 memories injected into system prompt
```

### Engagement System

```
Track every NSFW message per user
       │
       ▼
After 8 NSFW messages → inject soft-push hint into system prompt
("Naturally mention you have exclusive content")
       │
       ▼
Reset counter after push

Background loop (every 1 hour):
  Find users silent for 24h+ with 5+ total messages
       │
       ▼
  Send casual re-engagement DM
  ("heyyy where'd u go 😭", "bored. entertain me 😏", etc.)
  48h cooldown between re-engagements
```

---

## Key Decisions & Patterns

- **Multi-model routing**: SFW → Claude (best at persona consistency), NSFW → Grok (uncensored), Classification → Gemini Flash (fast + cheap). Each model only handles what it's best at.
- **Userbot, not bot**: Runs as a real Telegram account via MTProto (pyrofork), not the Bot API. This means no `/commands`, the persona appears as a normal user.
- **Companion payment bot**: Since userbots can't create invoices, a separate invisible bot (python-telegram-bot) handles Star invoice creation and payment processing. The userbot sends the invoice link in chat.
- **Two-part response style**: The persona is instructed to reply in two-part messages (observation + follow-up question). The humanizer splits on newlines and sends them as separate messages 0.5-1.5s apart, mimicking real texting.
- **Response cancellation**: If a user sends a new message while a response is still being generated, the old task is cancelled and only the latest message gets a reply.
- **Dedup via sent_content table**: The bot tracks every piece of content sent to each user, ensuring no repeats.
- **Modular storage backends**: Content can live on the local filesystem, in a private Telegram channel, or on Dropbox. Swappable via `content_config.yaml`.
- **Character Bible system**: Personas are defined in YAML files with identity, communication style, linguistic markers, memories, and hard boundaries. Converted to a system prompt at runtime.

---

## Database Schema

All tables live in a single SQLite file (`data/bot.db`).

| Table | Purpose |
|-------|---------|
| `messages` | STM — stores all user/assistant messages per user |
| `memories` | LTM — structured memories with embeddings and importance scores |
| `sent_content` | Tracks which content has been sent to which user (dedup) |
| `pending_unlocks` | Tracks content awaiting Star payment |
| `engagement_state` | Per-user engagement counters (NSFW count, last push, last re-engage) |

<details>
<summary>Full schema</summary>

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,            -- 'user' or 'assistant'
    content TEXT NOT NULL,
    timestamp REAL NOT NULL
);

CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    category TEXT NOT NULL,        -- 'fact', 'preference', 'relationship', 'event', 'thread'
    content TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 5,  -- 1-10
    embedding BLOB,               -- float32 numpy array
    created_at REAL NOT NULL,
    last_accessed REAL
);

CREATE TABLE sent_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    content_id TEXT NOT NULL,
    category TEXT NOT NULL,
    sent_at REAL NOT NULL,
    paid INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE pending_unlocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    content_id TEXT NOT NULL,
    category TEXT NOT NULL,
    star_price INTEGER NOT NULL,
    created_at REAL NOT NULL,
    unlocked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE engagement_state (
    user_id INTEGER PRIMARY KEY,
    nsfw_count INTEGER NOT NULL DEFAULT 0,
    total_messages INTEGER NOT NULL DEFAULT 0,
    last_push_at REAL DEFAULT 0,
    last_selfie_at REAL DEFAULT 0,
    last_message_at REAL DEFAULT 0,
    last_reengage_at REAL DEFAULT 0
);
```

</details>

---

## Deployment

### Requirements
- Python 3.13+
- No inbound ports needed (outbound HTTPS only)
- Outbound access to: `api.telegram.org`, `api.anthropic.com`, `api.x.ai`, `generativelanguage.googleapis.com`, `api.openai.com`

### Files to transfer
1. The project directory (excluding `.venv/`, `data/`, `content/`)
2. `.env` file with all API keys
3. `data/aishha.session` — Telegram auth session from dev machine
4. `content/` folder with media files

### systemd service (Linux)

Create `/etc/systemd/system/aishha.service`:

```ini
[Unit]
Description=Aishha Telegram Bot
After=network.target

[Service]
Type=simple
User=bot
WorkingDirectory=/opt/bot
Environment=PATH=/opt/bot/.venv/bin
ExecStart=/opt/bot/.venv/bin/python -m bot.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable aishha
sudo systemctl start aishha
journalctl -u aishha -f  # view logs
```

### Auto-reconnect
The bot has built-in auto-reconnect. If the Telegram connection drops, it waits 10 seconds and reconnects automatically. Combined with `Restart=always` in systemd, it handles both network blips and process crashes.

---

## Tunable Constants

| Constant | File | Default | Description |
|----------|------|---------|-------------|
| `STM_MAX_TURNS` | `config.py` | 18 | User turns before STM→LTM summarization triggers |
| `STM_SUMMARIZE_BATCH` | `config.py` | 10 | Messages summarized per batch |
| `LTM_TOP_K` | `config.py` | 5 | Memories retrieved per message |
| `LTM_COMPACTION_THRESHOLD` | `config.py` | 500 | Memory count before compaction |
| `LTM_SIMILARITY_WEIGHT` | `config.py` | 0.5 | Vector similarity weight in retrieval scoring |
| `LTM_IMPORTANCE_WEIGHT` | `config.py` | 0.3 | Importance score weight |
| `LTM_RECENCY_WEIGHT` | `config.py` | 0.2 | Recency weight |
| `SOFT_PUSH_THRESHOLD` | `engagement.py` | 8 | NSFW messages before content hint |
| `REENGAGE_AFTER_SECONDS` | `reengagement.py` | 86400 | Silence before re-engagement DM (24h) |
| `REENGAGE_COOLDOWN_SECONDS` | `reengagement.py` | 172800 | Cooldown between re-engagements (48h) |
| `MIN_MESSAGES_FOR_REENGAGE` | `reengagement.py` | 5 | Min messages before eligible for re-engagement |
| `TYPING_CHARS_PER_SEC` | `humanize.py` | 45 | Simulated typing speed |

---

## Known Issues / TODOs

- `scripts/index_channel.py` — The Telegram Bot API cannot iterate channel history. The script provides the output format but needs Pyrogram/Telethon for full indexing. Currently serves as a template.
- `clear_user.py` — Hardcoded user ID (`6019177604`). Needs to accept user ID as a CLI argument.
- `dump_memory.py` — Also has hardcoded assumptions about table structure. Useful for debugging only.
- The `engagement_state` table is created lazily (first call to `_ensure_table()`), unlike the other tables which are created in `db.py` schema. Needs clarification on whether to unify.
