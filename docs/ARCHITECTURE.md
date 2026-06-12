# Victoria AI — Response Formatting & Memory Architecture

This document explains **where every piece of information comes from**, **how
Victoria's replies are formatted** in each mode, and **how long-term memory
(LTM) works**.

---

## 1. The LLM providers (who does what)

Configured in `server/app.py` and `bot/config.py`:

| Role | Provider | Default model | Used for |
|------|----------|---------------|----------|
| **SFW** | Anthropic (Claude) | `claude-sonnet-4-20250514` | Sexting replies at intimacy stage 1-2, or any SFW message |
| **NSFW** | xAI (Grok) | `grok-3` | Sexting replies at stage 3 + NSFW, **all Story mode**, image analysis |
| **Classifier** | Google (Gemini) | `gemini-2.0-flash` | SFW/NSFW routing, summarization, intimacy scoring, story scoring |
| **Embeddings** | OpenAI | `text-embedding-3-small` | LTM vector embeddings only |

All model names are overridable via environment variables.

---

## 2. Where the prompt info comes from

Every reply is built by `bot/prompt_builder.py:build_prompt()`. The **system
prompt** is assembled from these sources, in order:

| # | Section | Source |
|---|---------|--------|
| 1 | Persona identity, voice, style, background, character memories, boundaries | **Persona bible** YAML (`personas/victoria.yaml` or `personas/victoria_nsfw.yaml`) via `Persona.to_system_prompt()` |
| 2 | User's name line | `user_facts` table (key `name`) |
| 3 | Time-of-day mood + activity + live weather | `bot/time_context.py` (Miami timezone + Open-Meteo weather API) |
| 4 | Story chapter context (Story mode only) | `stories/victoria_story.yaml` via `_get_story_context()` |
| 5 | Texting-style directive (Sexting mode only) | Hardcoded in `prompt_builder.py` |
| 6 | Intimacy stage instructions (Sexting mode only) | Persona YAML `stage_instructions` |
| 7 | Known facts | `user_facts` table via `format_facts_for_prompt()` |
| 8 | Relevant long-term memories | `memories` table via `retrieve_relevant()` |
| 9 | Soft-push hint (Sexting only, optional) | `bot/engagement.py` |

After the system prompt, the **recent conversation** (STM) is appended as
`user`/`assistant` turns.

### 2a. The persona bible (`personas/victoria.yaml`)

`Persona.to_system_prompt()` (`bot/persona.py`) pulls these YAML sections:

- `general` → name, age, tagline, `physical_description`, `voice`, `scent`
- `instructions` → `communication_style`, `key_linguistic_markers`, `pet_names`
- `context` → `background`
- `memories` → `sexual` / `non_sexual` **character memories** (her backstory facts)
- `boundaries` → hard rules that are never violated

There are **two persona bibles**:
- `personas/victoria.yaml` — SFW persona (used for Claude + all Story mode)
- `personas/victoria_nsfw.yaml` — explicit persona (used for Grok at stage 3 NSFW)

---

## 3. How her replies are formatted

### 3a. Shared final step — `_split_response`

Both modes pass the raw model output through
`ChatEngine._split_response()` (`bot/chat_engine.py`):

1. Em/en dashes (`—`, `–`) are replaced with a plain hyphen `-`.
2. The text is split on **every newline**; each non-empty line becomes a
   **separate chat bubble**.

The bubbles are then delivered by `_send_response_with_typing()`
(`server/app.py`) with a typing indicator, a delay scaled to message length,
and a 0.5-1.5s pause between bubbles — to feel like real typing.

### 3b. Sexting mode

1. **Batching** — `process_sexting_batched()` collects rapid-fire messages
   over a short window (random `MIN..MAX_RESPONSE_DELAY` × time-of-day
   multiplier, capped at 15s), de-duplicates them, and joins them with `\n`.
   *(User messages are persisted to the DB immediately on arrival, before the
   batch flushes, so history is never lost on mode switch.)*
2. **`_process_sexting()`** — classify SFW/NSFW (Gemini) → evaluate intimacy
   stage → pick provider + persona → retrieve LTM (if the gate allows) →
   inject facts → build prompt → generate.
3. **Style** — the Sexting-only directive in `prompt_builder.py` enforces a
   real-chat feel: **no trailing periods**, short punchy lines, 1-3 messages
   each on its own line. The model itself emits the newlines that
   `_split_response` turns into separate bubbles.

**Provider routing:** stage 3 **and** NSFW classification → Grok + NSFW
persona. Everything else → Claude + SFW persona.

### 3c. Story mode

1. **Direct, one-at-a-time** processing (no batching) via `_process_story()`.
2. Always uses **Grok** + the **SFW persona** + **story context**
   (`_get_story_context()`): the current chapter's `setting`, `mood`,
   `summary`, and `narrative_beats` from `stories/victoria_story.yaml`, plus
   instructions to use `*italic actions*` and let scenes breathe.
3. The Sexting texting-style directive is **NOT** applied here — Story stays in
   narrative prose (full sentences, periods, `*actions*`).
4. After generating: save → score progression → `_split_response`.

> **Note:** because `_split_response` splits on every newline, a Story reply
> like `*She smiles*` + blank line + `"Sit down"` becomes **two** bubbles.
> This can fragment narration. (Known trade-off, not yet changed.)

### 3d. Story progression (chapter pacing)

`bot/story_progression.py` mirrors the intimacy system. Each exchange is scored
0-10 for "advancement" by Gemini. A chapter advances only when
**≥6 exchanges AND accumulated score ≥22**, or when the goal is clearly met
after ≥3 exchanges. This prevents chapters from flying by after one message.

---

## 4. Long-term memory (LTM)

### 4a. Storage

Memories live in the `memories` table with: OpenAI **embedding vector**,
`category`, `importance` (1-10), `created_at`, `last_accessed`.

### 4b. Creation — `maybe_summarize()` (`bot/memory/summarizer.py`)

- **Trigger:** total user turns ≥ `STM_MAX_TURNS = 18`.
- **Shared across modes:** counts and summarizes across **both** Sexting and
  Story (`mode=None`), so memory is unified.
- Takes the oldest `STM_SUMMARIZE_BATCH = 10` (×2 = 20 messages), Gemini
  extracts JSON of `memories` + `facts`.
- **De-duplication:** if cosine similarity with an existing memory > 0.85 →
  update it; otherwise store a new one.
- The summarized messages are then **deleted** from STM (they now live in LTM).

### 4c. Retrieval

- **Gate** (`should_retrieve`) avoids an embedding call for trivial messages.
  It fires on: callback cues ("remember", "you said"...), long messages
  (>30 chars), a return after a >1h gap, or every 5th turn. It skips pure
  greetings/emoji.
- **Scoring** (`retrieve_relevant`, weights in `bot/config.py`):

  ```
  score = similarity × 0.5  +  importance × 0.3  +  recency × 0.2
  ```

  Returns the top `LTM_TOP_K = 5` memories and updates their `last_accessed`.

### 4d. Facts (separate, deterministic)

The `user_facts` table is a structured key-value store (name, location, age,
job, etc.). Unlike memories, facts are injected **every single turn**
deterministically — they don't depend on similarity search.

### 4e. Compaction — `maybe_compact()`

When memory count ≥ `LTM_COMPACTION_THRESHOLD = 500`, Gemini merges and
de-duplicates the whole set into a clean list.

### 4f. Sharing across modes

Memories and facts were **never** mode-scoped — they have always been shared.
The only mode-blind bug was in the summarizer (it deleted the wrong mode's
history); after the fix, LTM is **fully shared** between Sexting and Story:
whatever she learns in one mode, she remembers in the other.

---

## 5. Quick reference — data sources at a glance

```
Persona bible (YAML)      → identity, voice, style, backstory, boundaries
stage_instructions (YAML) → intimacy stage behavior (Sexting)
victoria_story.yaml       → chapter setting/mood/beats + progression goals (Story)
time_context.py           → time-of-day mood + live weather
user_facts (DB)           → hard facts injected every turn
memories (DB)             → embedded long-term memories, retrieved by relevance
STM (messages DB)         → recent conversation, per-mode, fed as chat turns
prompt_builder.py         → assembles all of the above into the system prompt
```
