"""
Mode-aware chat engine — replaces Telegram handlers.
Processes messages for both Sexting and Story modes.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

from bot.persona import Persona, load_persona
from bot.memory.stm import add_message, get_recent_messages, count_turns
from bot.memory.ltm import retrieve_relevant, should_retrieve
from bot.memory.summarizer import maybe_summarize, maybe_compact
from bot.memory.facts import get_facts, format_facts_for_prompt
from bot.prompt_builder import build_prompt
from bot.router import classify
from bot.engagement import track_message, should_soft_push, record_push, get_engagement_state
from bot.intimacy import evaluate_message, get_stage
from bot.mood import update_mood, get_mood
from bot.time_context import get_time_period
from bot.providers.base import LLMProvider
from bot.config import STM_MAX_TURNS, NSFW_PERSONA_FILE, STORY_FILE
from bot.memory.db import get_connection

logger = logging.getLogger(__name__)


@dataclass
class ChatResponse:
    """Response from the chat engine."""
    messages: list[str] = field(default_factory=list)
    content_urls: list[str] = field(default_factory=list)


def _format_last_seen(gap_seconds: float) -> str | None:
    """Human-friendly note about how long since the user last messaged."""
    if gap_seconds < 1800:  # under 30 min — same conversation, say nothing
        return None
    if gap_seconds < 7200:
        when = "about an hour"
    elif gap_seconds < 21600:
        when = "a few hours"
    elif gap_seconds < 86400:
        when = "most of the day"
    elif gap_seconds < 172800:
        when = "since yesterday"
    else:
        days = int(gap_seconds // 86400)
        when = f"about {days} days"
    return (
        f"It's been {when} since you two last talked. "
        "React to the gap naturally if it feels right — a little missed-him, "
        "a little curious where he's been — but don't make it heavy."
    )


class ChatEngine:
    """Unified chat engine for both Story and Sexting modes."""

    def __init__(
        self,
        persona: Persona,
        nsfw_persona: Persona | None,
        sfw_provider: LLMProvider,
        nsfw_provider: LLMProvider,
        classifier_provider: LLMProvider,
        vision_provider=None,
        force_stage: int | None = None,
    ):
        self.persona = persona
        self.nsfw_persona = nsfw_persona
        self.sfw_provider = sfw_provider
        self.nsfw_provider = nsfw_provider
        self.classifier_provider = classifier_provider
        self.vision_provider = vision_provider
        # When set (e.g. 3), skip the staged progression and treat every
        # sexting message at this intimacy stage, routed through the NSFW provider.
        self.force_stage = force_stage

        # Sexting mode batching
        self._pending: dict[int, list[str]] = {}
        self._batch_tasks: dict[int, asyncio.Task] = {}
        self._batch_events: dict[int, asyncio.Event] = {}
        self._processing_lock: dict[int, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process_message(
        self,
        user_id: int,
        text: str,
        mode: str = "sexting",
        image_bytes: bytes | None = None,
    ) -> ChatResponse:
        """Process a user message. Routes to correct mode pipeline."""
        # If user sent a photo, analyze it first
        if image_bytes and self.vision_provider:
            try:
                description = await self.vision_provider.analyze_image(image_bytes)
                text = f"{text}\n[User sent a photo: {description}]" if text else f"[User sent a photo: {description}]"
            except Exception as e:
                logger.error("Vision analysis failed: %s", e)

        if mode == "story":
            return await self._process_story(user_id, text)
        else:
            await add_message(user_id, "user", text, mode="sexting")
            return await self._process_sexting(user_id, text)

    async def process_sexting_batched(
        self,
        user_id: int,
        text: str,
        image_bytes: bytes | None = None,
        on_response=None,
    ) -> None:
        """
        Add message to batch buffer. After the collect window, all
        accumulated messages are processed together.
        on_response: async callback(ChatResponse) called when batch is ready.
        """
        if image_bytes and self.vision_provider:
            try:
                description = await self.vision_provider.analyze_image(image_bytes)
                text = f"{text}\n[User sent a photo: {description}]" if text else f"[User sent a photo: {description}]"
            except Exception as e:
                logger.error("Vision analysis failed: %s", e)

        # Persist immediately so history survives mode switches / disconnects,
        # even before the batch window flushes.
        await add_message(user_id, "user", text, mode="sexting")

        if user_id not in self._pending:
            self._pending[user_id] = []
        self._pending[user_id].append(text)

        # Start batch task if none running
        if user_id not in self._batch_tasks or self._batch_tasks[user_id].done():
            self._batch_tasks[user_id] = asyncio.create_task(
                self._batch_collect(user_id, on_response)
            )

    async def suggest_reply(self, user_id: int, mode: str = "sexting") -> str:
        """
        AI Help: write a suggested NEXT message for the USER to send — a reply
        TO Victoria, in his voice. Used by the 'generate reply' button. The
        suggestion is not stored; the user approves/edits it before sending.
        """
        stm = await get_recent_messages(user_id, STM_MAX_TURNS, mode=mode)
        if not stm:
            return ""

        user_facts = await get_facts(user_id)
        user_name = None
        for f in (user_facts or []):
            if f["key"] == "name":
                user_name = f["value"]
                break
        him = user_name or "the man"

        transcript_lines = []
        for m in stm:
            if m["role"] == "user":
                transcript_lines.append(f"{him}: {m['content']}")
            elif m["role"] == "assistant":
                transcript_lines.append(f"Victoria: {m['content']}")
        transcript = "\n".join(transcript_lines[-20:])

        system = (
            f"You are a flirting wingman helping a young man ({him}) who is sexting "
            "with Victoria — an older, elegant, seductive woman who is his girlfriend's "
            "mother. It is a consensual adult fantasy roleplay.\n\n"
            "Write the SINGLE next message HE should send to her. Rules:\n"
            "- First person, written TO Victoria, in his voice\n"
            "- Short and natural, like a real text — one or two lines, no period at the end\n"
            "- Confident, warm, playful; match her tone and gently escalate the flirtation\n"
            "- React to what she JUST said — don't ignore it\n"
            "- No quotation marks, no name labels, no emojis — output only the message text\n\n"
            "Conversation so far:\n" + transcript
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "Write his next message now. Output only the message text."},
        ]

        provider = self.nsfw_provider or self.sfw_provider
        try:
            text = await provider.generate(messages)
        except Exception as e:
            logger.warning("Suggest-reply generation failed: %s", e)
            return ""
        return (text or "").strip().strip('"').strip()

    async def generate_reengagement(self, user_id: int) -> ChatResponse:
        """
        Generate a spontaneous follow-up ("double-text") for a user who is
        still online but has gone quiet. Sexting mode only. Returns an empty
        ChatResponse if there's nothing to react to.
        """
        mode = "sexting"
        stm = await get_recent_messages(user_id, STM_MAX_TURNS, mode=mode)
        if not stm or not any(m["role"] == "user" for m in stm):
            return ChatResponse()

        stage = self.force_stage or await get_stage(user_id)
        mood = await get_mood(user_id)
        active_persona = (self.nsfw_persona or self.persona) if self.force_stage else self.persona
        nudge_provider = self.nsfw_provider if self.force_stage else self.sfw_provider

        user_facts = await get_facts(user_id)
        facts_text = format_facts_for_prompt(user_facts)
        user_name = None
        for f in (user_facts or []):
            if f["key"] == "name":
                user_name = f["value"]
                break

        hint = (
            "He's gone quiet for a little while and hasn't replied yet. "
            "Send a short, natural follow-up to re-engage him — the way a real woman "
            "double-texts: a playful nudge, a teasing line, a thought that just crossed "
            "your mind, or a callback to what you were just talking about. Keep it light, "
            "one or two short lines, fully in character. Do NOT ask 'are you there' like a "
            "bot, and do NOT complain about waiting or being ignored."
        )

        prompt_messages = await build_prompt(
            active_persona, [], stm,
            mode=mode,
            push_hint=hint,
            user_name=user_name,
            facts_text=facts_text,
            intimacy_stage=stage,
            mood=mood,
            already_greeted=True,
        )

        # Reassemble so the message list starts AND ends with a user turn
        # (Anthropic requires the first turn to be 'user'; ending on a user
        # turn makes the model produce the follow-up).
        system_msg = prompt_messages[0]
        turns = [m for m in prompt_messages[1:] if m["role"] in ("user", "assistant")]
        while turns and turns[0]["role"] == "assistant":
            turns.pop(0)
        turns.append({"role": "user", "content": "[He's been quiet for a bit.]"})
        final_messages = [system_msg] + turns

        try:
            response_text = await nudge_provider.generate(final_messages)
        except Exception as e:
            logger.warning("Re-engagement generation failed: %s", e)
            return ChatResponse()

        if not response_text or not response_text.strip():
            return ChatResponse()

        await add_message(user_id, "assistant", response_text, mode=mode)
        parts = self._split_response(response_text)
        return ChatResponse(messages=parts)

    async def get_story_chapter(self, user_id: int) -> int:
        """Get current story chapter for user."""
        conn = await get_connection()
        try:
            cursor = await conn.execute(
                "SELECT chapter FROM story_progress WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
            return row["chapter"] if row else 1
        finally:
            await conn.close()

    async def advance_story(self, user_id: int) -> int:
        """Advance to next chapter, return new chapter number."""
        import time
        current = await self.get_story_chapter(user_id)
        new_chapter = current + 1
        conn = await get_connection()
        try:
            await conn.execute(
                "INSERT INTO story_progress (user_id, chapter, scene, completed_at, chapter_score, chapter_messages) "
                "VALUES (?, ?, 0, ?, 0, 0) "
                "ON CONFLICT(user_id) DO UPDATE SET chapter = ?, completed_at = ?, "
                "chapter_score = 0, chapter_messages = 0",
                (user_id, new_chapter, time.time(), new_chapter, time.time()),
            )
            await conn.commit()
        finally:
            await conn.close()
        return new_chapter

    # ------------------------------------------------------------------
    # Story mode — single message, Grok only
    # ------------------------------------------------------------------

    async def _process_story(self, user_id: int, text: str) -> ChatResponse:
        mode = "story"
        await add_message(user_id, "user", text, mode=mode)

        # Summarize if needed
        async def _llm_call(prompt: str) -> str:
            return await self.classifier_provider.generate_simple(prompt)

        await maybe_summarize(user_id, _llm_call)
        await maybe_compact(user_id, _llm_call)

        stm = await get_recent_messages(user_id, STM_MAX_TURNS, mode=mode)
        if not stm or not any(m["role"] == "user" for m in stm):
            stm = [{"role": "user", "content": text}]

        # LTM
        ltm = []
        if should_retrieve(user_id, text):
            ltm = await retrieve_relevant(user_id, text)

        # Facts
        user_facts = await get_facts(user_id)
        facts_text = format_facts_for_prompt(user_facts)

        # Extract user name from facts
        user_name = None
        for f in (user_facts or []):
            if f["key"] == "name":
                user_name = f["value"]
                break

        # Story chapter
        chapter = await self.get_story_chapter(user_id)

        # Build prompt — story mode always uses Grok (nsfw_provider) and SFW persona with story context
        prompt_messages = await build_prompt(
            self.persona, ltm, stm,
            mode=mode,
            user_name=user_name,
            facts_text=facts_text,
            story_chapter=chapter,
        )

        try:
            response_text = await self.nsfw_provider.generate(prompt_messages)
        except Exception as e:
            logger.error("Story mode LLM failed: %s", e)
            return ChatResponse(messages=["*She pauses, lost in thought for a moment...*"])

        if not response_text or not response_text.strip():
            return ChatResponse(messages=["*She looks at you, searching for the right words...*"])

        await add_message(user_id, "assistant", response_text, mode=mode)

        # Score this exchange and maybe advance the chapter
        await self._maybe_advance_chapter(user_id, chapter, text, response_text, _llm_call)

        # Split into multiple messages
        parts = self._split_response(response_text)
        return ChatResponse(messages=parts)

    async def _maybe_advance_chapter(self, user_id: int, chapter: int, user_text: str, last_response: str, llm_call) -> None:
        """Score the exchange and advance the chapter once enough progress accrues."""
        import yaml
        from pathlib import Path
        from bot.config import STORY_FILE
        from bot.story_progression import record_turn

        path = Path(STORY_FILE)
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            story_data = yaml.safe_load(f)

        chapters = story_data.get("chapters", [])
        total = story_data.get("meta", {}).get("total_chapters", len(chapters))

        # Already at last chapter
        if chapter >= total:
            return

        current = None
        for ch in chapters:
            if ch.get("id") == chapter:
                current = ch
                break
        if not current:
            return

        try:
            should_advance = await record_turn(
                user_id, chapter, user_text, last_response, current, llm_call
            )
            if should_advance:
                new_ch = await self.advance_story(user_id)
                logger.info("Story advanced to chapter %d for user %d", new_ch, user_id)
        except Exception as e:
            logger.warning("Chapter progression check failed: %s", e)

    # ------------------------------------------------------------------
    # Sexting mode — batched, SFW/NSFW switch
    # ------------------------------------------------------------------

    async def _process_sexting(self, user_id: int, text: str) -> ChatResponse:
        # NOTE: the user message is persisted at ingestion time
        # (process_sexting_batched / process_message), not here, so that
        # history is never lost while a batch is still pending.
        mode = "sexting"

        async def _llm_call(prompt: str) -> str:
            return await self.classifier_provider.generate_simple(prompt)

        await maybe_summarize(user_id, _llm_call)
        await maybe_compact(user_id, _llm_call)

        # Capture how long since the user last messaged (before track_message
        # overwrites last_message_at) so she can greet like a real person.
        prev_state = await get_engagement_state(user_id)
        last_seen_note = None
        if prev_state and prev_state["last_message_at"]:
            gap = time.time() - prev_state["last_message_at"]
            last_seen_note = _format_last_seen(gap)

        stm = await get_recent_messages(user_id, STM_MAX_TURNS, mode=mode)
        # She opens the conversation first, so if there's already an assistant
        # turn she must continue the thread, not greet again.
        already_greeted = any(m["role"] == "assistant" for m in stm)
        if not stm or not any(m["role"] == "user" for m in stm):
            stm = [{"role": "user", "content": text}]

        # Classify SFW/NSFW
        classification = await classify(text, self.classifier_provider.generate_simple)
        await track_message(user_id, classification)

        # Evaluate intimacy progression (returns stage + per-dimension signals)
        intimacy_stage, signals = await evaluate_message(user_id, text, _llm_call)

        # Single-persona "always open" mode: ignore the staged progression.
        if self.force_stage:
            intimacy_stage = self.force_stage

        # Update short-term mood from the same signals (no extra LLM call)
        await update_mood(user_id, signals, classification, intimacy_stage, get_time_period())
        mood = await get_mood(user_id)

        # Pick provider and persona based on stage
        if self.force_stage:
            # Fully open from the start — everything runs through the NSFW
            # provider with the single open persona.
            provider = self.nsfw_provider
            active_persona = self.nsfw_persona or self.persona
        elif intimacy_stage >= 3 and classification == "nsfw":
            # Stage 3: explicit content routes to the NSFW provider
            provider = self.nsfw_provider
            active_persona = self.nsfw_persona or self.persona
        else:
            # Stage 1-2: SFW provider (Victoria deflects, doesn't reciprocate)
            provider = self.sfw_provider
            active_persona = self.persona

        # LTM
        ltm = []
        if should_retrieve(user_id, text):
            ltm = await retrieve_relevant(user_id, text)

        # Soft push hint
        push_hint = None
        if await should_soft_push(user_id):
            push_hint = (
                "Naturally hint that you have private photos you could share — "
                "be subtle, seductive, like it's a secret between you two."
            )
            await record_push(user_id)

        # Facts
        user_facts = await get_facts(user_id)
        facts_text = format_facts_for_prompt(user_facts)

        user_name = None
        for f in (user_facts or []):
            if f["key"] == "name":
                user_name = f["value"]
                break

        # Build and generate
        prompt_messages = await build_prompt(
            active_persona, ltm, stm,
            mode=mode,
            push_hint=push_hint,
            user_name=user_name,
            facts_text=facts_text,
            intimacy_stage=intimacy_stage,
            mood=mood,
            last_seen_note=last_seen_note,
            already_greeted=already_greeted,
        )

        try:
            response_text = await provider.generate(prompt_messages)
        except Exception as e:
            logger.warning("Primary provider failed: %s — falling back", e)
            fallback = self.nsfw_provider if provider is self.sfw_provider else self.sfw_provider
            try:
                response_text = await fallback.generate(prompt_messages)
            except Exception as e2:
                logger.error("Fallback also failed: %s", e2)
                return ChatResponse(messages=["..."])

        if not response_text or not response_text.strip():
            return ChatResponse()

        await add_message(user_id, "assistant", response_text, mode=mode)

        parts = self._split_response(response_text)
        return ChatResponse(messages=parts)

    # ------------------------------------------------------------------
    # Batching for sexting mode
    # ------------------------------------------------------------------

    async def _batch_collect(self, user_id: int, on_response=None) -> None:
        """Wait for collect window, then process all accumulated messages."""
        import random
        from bot.config import MIN_RESPONSE_DELAY, MAX_RESPONSE_DELAY
        from bot.time_context import get_response_delay_multiplier

        multiplier = get_response_delay_multiplier()
        delay = random.uniform(MIN_RESPONSE_DELAY, MAX_RESPONSE_DELAY) * multiplier
        delay = min(delay, 15.0)  # Cap at 15s for web
        logger.info("Batch collect: %.1fs for user %d", delay, user_id)
        await asyncio.sleep(delay)

        texts = self._pending.pop(user_id, [])
        if not texts:
            return

        # Deduplicate consecutive identical messages
        deduped = []
        i = 0
        while i < len(texts):
            msg = texts[i]
            count = 1
            while i + count < len(texts) and texts[i + count] == msg:
                count += 1
            if count > 1:
                deduped.append(f'[User sent the same message {count} times: "{msg[:100]}"]')
            else:
                deduped.append(msg)
            i += count

        combined = "\n".join(deduped)

        if user_id not in self._processing_lock:
            self._processing_lock[user_id] = asyncio.Lock()

        async with self._processing_lock[user_id]:
            try:
                response = await self._process_sexting(user_id, combined)
                if on_response:
                    await on_response(response)
            except Exception as e:
                logger.error("Batch processing failed for user %d: %s", user_id, e, exc_info=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_response(text: str) -> list[str]:
        """Split response into multiple message bubbles."""
        text = text.replace("\u2014", "-").replace("\u2013", "-")
        parts = [p.strip() for p in text.split("\n") if p.strip()]
        return parts if parts else [text.strip()]
