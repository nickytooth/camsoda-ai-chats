import asyncio
import logging
import re
import time as _time
from pyrogram import Client, filters
from pyrogram.types import Message
from bot.persona import Persona
from bot.memory.stm import add_message, get_recent_messages, count_turns
from bot.memory.ltm import retrieve_relevant, should_retrieve
from bot.memory.summarizer import maybe_summarize, maybe_compact
from bot.prompt_builder import build_prompt
from bot.router import classify
from bot.humanize import send_human_like
from bot.content_manager import send_teaser, send_free_content
from bot.intent import detect_content_intent
from bot.engagement import track_message, should_soft_push, record_push, should_send_selfie
from bot.storage.base import StorageBackend
from bot.providers.base import LLMProvider
from bot.config import STM_MAX_TURNS

logger = logging.getLogger(__name__)

# These get injected at startup
_persona: Persona | None = None
_nsfw_persona: Persona | None = None
_sfw_provider: LLMProvider | None = None
_nsfw_provider: LLMProvider | None = None
_classifier_provider: LLMProvider | None = None
_vision_provider = None  # GrokProvider for image analysis
_storage: StorageBackend | None = None

# Message batching: collect all messages during the read delay before processing
_pending_messages: dict[int, list[str]] = {}
_active_tasks: dict[int, asyncio.Task] = {}
_processing_lock: dict[int, asyncio.Lock] = {}

# Track which users we've already stored the Telegram name for
_name_injected: set[int] = {}


def _relative_time(timestamp: int) -> str:
    """Convert a Unix timestamp to a human-friendly relative string."""
    diff = _time.time() - timestamp
    if diff < 60:
        return "just now"
    if diff < 3600:
        mins = int(diff / 60)
        return f"~{mins} min ago"
    if diff < 86400:
        hours = int(diff / 3600)
        return f"~{hours}h ago"
    days = int(diff / 86400)
    return f"~{days}d ago" if days < 7 else "a while ago"

def setup(
    persona: Persona,
    sfw_provider: LLMProvider,
    nsfw_provider: LLMProvider,
    classifier_provider: LLMProvider,
    storage: StorageBackend,
    vision_provider=None,
    nsfw_persona: Persona | None = None,
) -> None:
    global _persona, _nsfw_persona, _sfw_provider, _nsfw_provider, _classifier_provider, _vision_provider, _storage
    _persona = persona
    _nsfw_persona = nsfw_persona
    _sfw_provider = sfw_provider
    _nsfw_provider = nsfw_provider
    _classifier_provider = classifier_provider
    _vision_provider = vision_provider
    _storage = storage


async def _process_message(app: Client, chat_id: int, user_id: int, text: str) -> None:
    await add_message(user_id, "user", text)

    # Check if summarization is needed
    async def _summarize_call(prompt: str) -> str:
        return await _classifier_provider.generate_simple(prompt)

    await maybe_summarize(user_id, _summarize_call)
    await maybe_compact(user_id, _summarize_call)

    # Get recent messages for context (re-fetch after summarization may have cleared old ones)
    stm_messages = await get_recent_messages(user_id, STM_MAX_TURNS)

    # Safety: ensure at least the current user message is present
    if not stm_messages or not any(m["role"] == "user" for m in stm_messages):
        stm_messages = [{"role": "user", "content": text}]

    # LLM-based intent detection
    intent = await detect_content_intent(
        message=text,
        recent_messages=stm_messages,
        llm_call=_classifier_provider.generate_simple,
    )

    # LLM call helper for content captions (uses NSFW provider — no refusals)
    async def _caption_call(prompt: str) -> str:
        return await _nsfw_provider.generate_simple(prompt)

    # Save content intent for later — don't send yet, chat response first
    content_intent = intent if intent != "none" and _storage else None

    # Classify SFW/NSFW
    classification = await classify(text, _classifier_provider.generate_simple)

    # Track engagement for soft-push logic
    await track_message(user_id, classification)

    # Pick provider and persona based on classification
    provider = _nsfw_provider if classification == "nsfw" else _sfw_provider
    active_persona = (_nsfw_persona or _persona) if classification == "nsfw" else _persona

    # Retrieve LTM memories (gated to save embed API costs)
    if should_retrieve(user_id, text):
        ltm_memories = await retrieve_relevant(user_id, text)
    else:
        ltm_memories = []

    # Check if we should soft-push content
    push_hint = None
    if await should_soft_push(user_id):
        push_hint = "Naturally mention that you have exclusive content/pics/vids that you don't post anywhere else. Be subtle and flirty about it, like dropping a hint — not a hard sell."
        await record_push(user_id)

    # If content was requested, hint the LLM so she can acknowledge it naturally
    if content_intent == "suggest":
        push_hint = "The user hinted they want to see content but didn't specify. Ask them casually if they want a selfie or something naughtier. Keep it flirty and natural."
    elif content_intent:
        push_hint = f"The user asked for content. You're about to send them something — respond to their messages naturally first. Don't mention sending anything, just chat."

    # Math backstop: detect obvious calculations and force deflection
    if re.search(r'\d+\s*[\+\-\*\/\^]\s*\d+', text) or re.search(r'what(?:\s+is|\s*\'s)\s+\d+', text, re.IGNORECASE):
        if push_hint:
            push_hint += " ALSO: The user is asking a math question. You are TERRIBLE at math. Do NOT give an exact answer. Deflect or guess wrong."
        else:
            push_hint = "The user is asking a math question. You are TERRIBLE at math. Do NOT give an exact answer. Deflect, refuse, or guess hilariously wrong."

    # Extract user's Telegram name from STM if available
    user_name = None
    for m in stm_messages:
        if m["role"] == "system" and m["content"].startswith("[User's Telegram name:"):
            user_name = m["content"].split(":", 1)[1].strip().rstrip("]")
            break

    # Fetch structured facts (always injected, tiny payload)
    from bot.memory.facts import get_facts, format_facts_for_prompt
    user_facts = await get_facts(user_id)
    facts_text = format_facts_for_prompt(user_facts)

    # Build prompt and generate
    prompt_messages = await build_prompt(active_persona, ltm_memories, stm_messages, push_hint=push_hint, user_name=user_name, facts_text=facts_text)
    try:
        response_text = await provider.generate(prompt_messages)
    except Exception as e:
        logger.warning("Primary provider failed: %s — falling back", e)
        # NSFW fails → try Grok (no safety filters); SFW fails → try Gemini
        if provider is _nsfw_provider and _vision_provider:
            fallback = _vision_provider
        else:
            fallback = _nsfw_provider if provider is _sfw_provider else _sfw_provider
        try:
            response_text = await fallback.generate(prompt_messages)
        except Exception as e2:
            logger.error("Fallback provider also failed: %s", e2)
            return

    if not response_text or not response_text.strip():
        logger.warning("Empty response from LLM for user %d, skipping", user_id)
        return

    # Store bot response
    await add_message(user_id, "assistant", response_text)

    # Send with typing only (read delay already handled by batch system)
    await send_human_like(app, chat_id, response_text, skip_read_delay=True)

    # NOW send content after the chat response
    if content_intent and content_intent != "suggest":
        from bot.content_manager import load_content_config, get_star_price
        config = load_content_config()
        price = get_star_price(content_intent, config)

        if price == 0:
            result = await send_free_content(app, chat_id, user_id, content_intent, _storage, llm_call=_caption_call, image_describe=_vision_provider.analyze_image if _vision_provider else None, recent_messages=stm_messages, classifier_call=_classifier_provider.generate_simple)
            if result:
                # result is "filename|tag|free|caption" or False
                parts = result.split("|") if isinstance(result, str) else []
                fname = parts[0] if parts else "unknown"
                tag = parts[1] if len(parts) > 1 else ""
                caption = parts[3] if len(parts) > 3 else ""
                await add_message(user_id, "assistant", f"[sent free {content_intent}: {fname} ({tag}), caption: \"{caption}\"]")
        else:
            result = await send_teaser(app, chat_id, user_id, content_intent, _storage, llm_call=_caption_call, image_describe=_vision_provider.analyze_image if _vision_provider else None)
            if result:
                # result is "filename|teaser|price" or False
                parts = result.split("|") if isinstance(result, str) else []
                fname = parts[0] if parts else "unknown"
                price_str = parts[2] if len(parts) > 2 else ""
                await add_message(user_id, "assistant", f"[sent {content_intent} teaser: {fname}, {price_str}]")


async def _delayed_process(app: Client, chat_id: int, user_id: int) -> None:
    """Wait for read delay, then grab ALL accumulated messages and process."""
    import random
    from bot.config import MIN_RESPONSE_DELAY, MAX_RESPONSE_DELAY
    from bot.time_context import get_response_delay_multiplier

    # Wait the full read delay — messages keep accumulating in the buffer
    multiplier = get_response_delay_multiplier()
    read_delay = random.uniform(MIN_RESPONSE_DELAY, MAX_RESPONSE_DELAY) * multiplier
    logger.info("Read delay: %.1fs (x%.1f) for user %d — collecting messages...", read_delay, multiplier, user_id)
    await asyncio.sleep(read_delay)

    # Mark messages as read (blue ticks) after the delay
    try:
        await app.read_chat_history(chat_id)
    except Exception as e:
        logger.debug("Could not mark chat as read: %s", e)

    # Beat between read and typing — nobody reads and replies in the same half-second
    await asyncio.sleep(random.uniform(1.0, 2.5))

    # After delay, grab everything that accumulated
    texts = _pending_messages.pop(user_id, [])
    _active_tasks.pop(user_id, None)

    if not texts:
        return

    # Collapse identical consecutive messages to save tokens
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
    logger.info("Processing batch of %d message(s) (%d deduped) from user %d: %s", len(texts), len(deduped), user_id, combined[:80])

    # Ensure only one response at a time per user
    if user_id not in _processing_lock:
        _processing_lock[user_id] = asyncio.Lock()

    async with _processing_lock[user_id]:
        try:
            await _process_message(app, chat_id, user_id, combined)
        except Exception as e:
            logger.error("Error processing message from user %d: %s", user_id, e, exc_info=True)


def _add_to_buffer(user_id: int, chat_id: int, text: str, client: Client) -> None:
    """Add text to user's message buffer and start processing if needed."""
    if user_id not in _pending_messages:
        _pending_messages[user_id] = []
    _pending_messages[user_id].append(text)

    # Only start a processing task if none is running for this user
    if user_id not in _active_tasks or _active_tasks[user_id].done():
        _active_tasks[user_id] = asyncio.create_task(_delayed_process(client, chat_id, user_id))


def register_handlers(app: Client) -> None:

    @app.on_message(filters.private & filters.text & filters.incoming)
    async def handle_message(client: Client, message: Message) -> None:
        logger.info("Message from %d: %s", message.from_user.id, (message.text or "")[:50])
        user_id = message.from_user.id
        chat_id = message.chat.id
        text = message.text or ""

        # Inject user's Telegram name on first contact
        if user_id not in _name_injected:
            first_name = (message.from_user.first_name or "").strip()
            if first_name:
                await add_message(user_id, "system", f"[User's Telegram name: {first_name}]")
                _name_injected.add(user_id)
                logger.info("Stored Telegram name '%s' for user %d", first_name, user_id)

        # Handle reply/quote context
        reply = message.reply_to_message
        if reply and (reply.text or reply.caption):
            quoted = (reply.text or reply.caption or "")[:150]
            rel = _relative_time(reply.date.timestamp()) if reply.date else ""
            # Check if quoted text is already in STM (skip annotation if so)
            stm = await get_recent_messages(user_id, STM_MAX_TURNS)
            already_in_stm = any(quoted[:60] in m["content"] for m in stm)
            if not already_in_stm:
                time_part = f" from {rel}" if rel else ""
                text = f'[Replying to your message "{quoted}"{time_part}]\n{text}'

        _add_to_buffer(user_id, chat_id, text, client)

    @app.on_message(filters.private & filters.photo & filters.incoming)
    async def handle_photo(client: Client, message: Message) -> None:
        logger.info("Photo from %d (caption: %s)", message.from_user.id, (message.caption or "")[:50])
        user_id = message.from_user.id
        chat_id = message.chat.id

        # Download the photo
        try:
            photo_data = await client.download_media(message, in_memory=True)
            image_bytes = bytes(photo_data.getbuffer())

            # Analyze with Grok vision
            description = await _vision_provider.analyze_image(image_bytes)
            text = f"[User sent a photo: {description}]"

            # Include caption if present
            if message.caption:
                text = f"{message.caption}\n{text}"

            logger.info("Photo analyzed for user %d: %s", user_id, description[:80])
        except Exception as e:
            logger.error("Failed to analyze photo from user %d: %s", user_id, e, exc_info=True)
            text = "[User sent a photo that could not be analyzed]"

        _add_to_buffer(user_id, chat_id, text, client)
