Hey,

I wanted to share what I've been building - it's an AI companion bot on Telegram that simulates a real content creator (think OnlyFans model personality). It's more of an agentic system than a simple chatbot. Here's a breakdown:

---

**What it is:**

A Telegram bot that acts as a real person - she has memory, knows what time and day it is, knows the weather in her city, remembers past conversations, and sells exclusive content (selfies/videos) via Telegram Stars payments. The goal is to make interactions feel indistinguishable from talking to a real girl.

---

**How the backend works:**

The system runs two Telegram bots in parallel:
- A Pyrogram userbot (acts as the persona - sends messages as a real user account)
- A payment bot (handles Telegram Stars invoices and payment confirmations)

For LLMs, we route between three providers depending on context:
- Claude (Anthropic) for safe-for-work conversations
- Grok (xAI) for NSFW conversations - no safety filters, plus vision capability for image analysis
- Gemini Flash (Google) for fast classification and summarization tasks

Every incoming message goes through a classification pipeline: first a regex keyword check (instant, zero cost), then an LLM call for ambiguous cases. Based on the result, the system picks the right provider and persona (we have separate SFW and NSFW persona configs loaded at startup).

The personas are defined in YAML files - they contain the character's name, age, backstory, personality traits, communication style, example messages, and behavioral boundaries. The NSFW version has additional escalation patterns and explicit communication guidelines. This makes the persona fully configurable without touching code - you can swap personalities by just editing a YAML file.

---

**Memory system:**

Two layers, inspired by how human memory works:

*Short-term memory (STM):*
- Keeps the last 18 turns (user + assistant messages) per user in SQLite
- When the window fills up, the oldest 10 messages get summarized by Gemini Flash into a compact paragraph and stored in LTM
- This means she always has immediate conversational context without blowing up the token window
- Each user has their own isolated STM - conversations don't bleed between users

*Long-term memory (LTM):*
- Every summarized conversation batch + important facts get embedded using OpenAI text-embedding-3-small (1536 dimensions)
- Stored in SQLite with the embedding vector, an importance score (1-10, assigned by the summarizer), and a timestamp
- At retrieval time, we compute a weighted score: 50% cosine similarity to current message + 30% importance + 20% recency decay
- Top 5 memories are injected into the system prompt as "What you remember about this person"
- Compaction runs when entries exceed 500 per user - merges similar/low-importance memories to keep retrieval fast
- This lets her say things like "didn't you say you're from London?" weeks later without us storing the full conversation history

*What flows between memory layers:*
```
User sends message → stored in STM → STM fills up → batch summarized → embedded → stored in LTM
                                                                                         ↓
Next conversation → current message embedded → cosine search against LTM → top-K injected into prompt
```

---

**Environment awareness:**

She's "based in Miami" so the system uses US/Eastern timezone to inject real time, day, and date into every prompt. We also pull live weather from OpenWeatherMap (cached every 30 min). There are 6 time periods throughout the day that shift her mood, activity, energy level, and response timing. At 2am she's "just got home, in bed, can't sleep" - at 5pm she's "doing makeup, getting ready to go out."

---

**Content engine:**

Selfies are tagged by filename (bed_001.jpg, pool_001.jpg, etc.). When she sends a selfie, the system:
1. Uses the LLM to pick the best tag based on conversation context
2. Falls back to time-of-day preferences (morning → bed selfies, afternoon → pool)
3. Analyzes the image with Grok Vision to get a description
4. Generates a context-aware caption

For paid content (videos): she sends a teaser photo + a Telegram Stars invoice. After payment, the system delivers the full video automatically.

Deduplication ensures no user ever sees the same content twice. There's also a 4-hour cooldown between free selfies.

---

**Other agentic behaviors:**

- Engagement tracking: after X NSFW messages, she naturally hints at exclusive content (injected into the prompt, not hard-coded)
- Re-engagement: messages inactive users after a cooldown
- Unprompted selfies: probability-gated, sends selfies without being asked to build rapport
- Humanization: variable response delays (60-180s × time-of-day multiplier), typing simulation, read receipts
- Provider fallback: if one LLM fails (safety filter, timeout), automatically routes to another

---

**What could be added next:**

- Proactive messaging (she decides to text first based on patterns/mood)
- Voice notes (pre-recorded, tagged like selfies)
- Life storylines that evolve over days (exam week, new tattoo, roommate drama)
- Sentiment tracking to detect disengagement
- Full PostgreSQL migration for cloud hosting
- Autonomous scheduling based on user activity patterns

---

**Tech stack:** Python 3.13, asyncio, Pyrogram, python-telegram-bot, Claude/Grok/Gemini, OpenAI embeddings, SQLite (aiosqlite), httpx, Docker/Ansible for deployment.

Let me know if you have questions or want to dig deeper into any part.
