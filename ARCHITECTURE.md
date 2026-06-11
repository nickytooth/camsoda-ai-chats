# Aishha — Agentic AI Companion Bot

A context-aware conversational AI that simulates a real person (content creator) on Telegram, with memory, environment awareness, content monetization, and multi-provider LLM routing.

---

## System Overview

```
User (Telegram) → Pyrogram Userbot → Message Pipeline → LLM Response → Humanized Delivery
                                         ↓
                    [Intent Detection] [Classification] [Memory] [Content Engine]
```

**Two Telegram bots work in tandem:**
- **Userbot** (Pyrogram) — acts as the persona, sends messages/media as a real user account
- **Payment Bot** (python-telegram-bot) — handles Telegram Stars invoices and payment confirmations

---

## Backend Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.13, asyncio |
| Telegram client | Pyrogram (userbot) + python-telegram-bot (payments) |
| LLM providers | Claude (SFW chat), Grok/xAI (NSFW chat + vision), Gemini (classification + summarization) |
| Embeddings | OpenAI text-embedding-3-small |
| Database | SQLite (aiosqlite) — STM, LTM, engagement, content tracking |
| Storage | Local filesystem (pluggable: Telegram channels, Dropbox) |
| Weather | OpenWeatherMap API (cached 30min) |
| Deployment | Docker / Ansible → EC2 (or Railway) |

---

## Agentic Capabilities

### 1. Multi-Provider LLM Routing
- **SFW messages** → Claude (Anthropic) — safety-conscious, quality writing
- **NSFW messages** → Grok (xAI) — no safety filters, explicit content
- **Classification & summarization** → Gemini Flash — fast, cheap
- **Image analysis** → Grok Vision — describes photos for context-aware captions
- **Fallback chain**: if primary fails (safety filter, timeout), automatically routes to alternate provider

### 2. Message Classification Pipeline
```
User message → Fast keyword check (regex) → LLM classification (Gemini) → SFW/NSFW label
```
- Keyword set catches obvious NSFW instantly (no LLM cost)
- LLM handles ambiguous cases
- Classification determines: provider selection, persona selection, engagement tracking

### 3. Dual Persona System
- **SFW persona** (`aishha.yaml`) — flirty but within bounds, personality + examples + boundaries
- **NSFW persona** (`aishha_nsfw.yaml`) — explicit, escalation patterns, sexual communication style
- Persona selected per-message based on classification
- Both loaded at startup, zero latency to switch

### 4. Memory Architecture

**Short-Term Memory (STM)**
- Rolling conversation window (18 turns)
- Auto-summarizes older messages into LTM when window fills
- Per-user isolation

**Long-Term Memory (LTM)**
- Embedding-based retrieval (cosine similarity + importance + recency scoring)
- Stores facts, preferences, relationship history
- Compaction when entries exceed threshold
- Used to personalize responses ("you told me you like X")

### 5. Environment Awareness (Time Context)
- Real-time Miami timezone (US/Eastern)
- Correct day, date, and time injected into every prompt
- **6 time periods** with distinct moods, activities, and energy levels
- Affects: response tone, selfie selection, response delay
- **Live weather** from OpenWeatherMap — she can reference real conditions naturally

### 6. Content Distribution Engine

**Content types:**
- Free selfies (tagged by context: `bed_001.jpg`, `pool_001.jpg`)
- Paid videos (teaser + invoice + unlock flow via Telegram Stars)

**Context-aware selection:**
1. LLM picks best selfie tag from conversation context
2. Falls back to time-of-day preferred tags
3. Falls back to any unseen content

**Monetization flow:**
```
User requests video → Teaser photo + Star invoice → Payment → Video delivered
```

**Safeguards:**
- Never sends same content twice (DB tracking)
- 4-hour cooldown between free selfies per user
- Deduplication across all content types

### 7. Engagement & Proactive Behavior
- Tracks NSFW message count per user
- After threshold (8 NSFW messages) → injects "soft push" hint into LLM prompt to naturally mention exclusive content
- Unprompted selfies (20% probability gate after rapport threshold)
- Re-engagement messages for inactive users

### 8. Humanization Layer
- Variable response delays (60-180s base × time-of-day multiplier)
- Typing simulation before sending
- Read receipt simulation
- Multi-message splitting for natural delivery

---

## Intent Detection

LLM-based intent classification for content requests:
```
User message → Gemini → none | suggest | selfies | videos
```
- `none` → normal chat
- `suggest` → prompt LLM to ask what kind of content
- `selfies` → send free content
- `videos` → send paid teaser + invoice

---

## What Could Be Added

| Feature | Complexity | Impact |
|---------|-----------|--------|
| Proactive messaging (she texts first based on time/mood) | Medium | High |
| Voice notes (pre-recorded, tagged like selfies) | Low | High |
| Life storylines (exam week, new tattoo — evolve over days) | Medium | High |
| User timezone detection (acknowledge time difference) | Low | Medium |
| Sentiment tracking (detect when user is upset/losing interest) | Medium | Medium |
| A/B testing on personas/prompts | Medium | High |
| Multi-user analytics dashboard | Medium | Medium |
| Full PostgreSQL migration (for Railway/scale) | Medium | Medium |
| Autonomous scheduling (decides when to initiate based on user patterns) | High | Very High |
| Tool use (browse socials, reference real posts) | High | High |

---

## File Structure

```
bot/
├── main.py              # Entrypoint — starts both bots
├── config.py            # Environment variables & settings
├── handlers.py          # Message processing pipeline
├── router.py            # SFW/NSFW classification
├── intent.py            # Content intent detection
├── prompt_builder.py    # Assembles system prompt (persona + memory + context)
├── time_context.py      # Time/date/weather awareness
├── engagement.py        # Engagement tracking & soft-push logic
├── reengagement.py      # Inactive user re-engagement
├── humanize.py          # Typing delays, message splitting
├── persona.py           # Persona YAML loader
├── content_manager.py   # Content selection, captioning, delivery
├── payment_bot.py       # Telegram Stars payment handling
├── memory/
│   ├── db.py            # SQLite connection
│   ├── stm.py           # Short-term memory
│   ├── ltm.py           # Long-term memory (embeddings)
│   └── summarizer.py    # Conversation summarization
├── providers/
│   ├── anthropic_provider.py  # Claude
│   ├── grok_provider.py       # Grok (chat + vision)
│   └── gemini_provider.py     # Gemini Flash
└── storage/
    ├── base.py           # Abstract storage interface
    ├── local.py          # Local filesystem storage
    ├── telegram_storage.py
    └── dropbox_storage.py
```
