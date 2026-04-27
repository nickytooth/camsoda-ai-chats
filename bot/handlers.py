import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from bot.persona import Persona
from bot.memory.stm import add_message, get_recent_messages, count_turns
from bot.memory.ltm import retrieve_relevant
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
_sfw_provider: LLMProvider | None = None
_nsfw_provider: LLMProvider | None = None
_classifier_provider: LLMProvider | None = None
_storage: StorageBackend | None = None

# Track active response tasks so we don't double-respond
_active_tasks: dict[int, asyncio.Task] = {}

def setup(
    persona: Persona,
    sfw_provider: LLMProvider,
    nsfw_provider: LLMProvider,
    classifier_provider: LLMProvider,
    storage: StorageBackend,
) -> None:
    global _persona, _sfw_provider, _nsfw_provider, _classifier_provider, _storage
    _persona = persona
    _sfw_provider = sfw_provider
    _nsfw_provider = nsfw_provider
    _classifier_provider = classifier_provider
    _storage = storage


async def _process_message(app: Client, message: Message) -> None:
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text or ""

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

    # Handle content intent
    if intent == "suggest" and _storage:
        # User seems interested but vague — Aishha asks what they want
        await add_message(user_id, "assistant", "[asking what content they want]")
        await send_human_like(
            app, chat_id,
            "u want a cute selfie or something more… naughty? 😏🔥"
        )
        return

    if intent != "none" and _storage:
        # Specific category detected
        from bot.content_manager import load_content_config, get_star_price
        config = load_content_config()
        price = get_star_price(intent, config)

        if price == 0:
            # Free content (selfies)
            sent = await send_free_content(app, chat_id, user_id, intent, _storage)
            if sent:
                await add_message(user_id, "assistant", f"[sent free {intent}]")
                return
        else:
            # Paid content — send teaser + invoice
            sent = await send_teaser(app, chat_id, user_id, intent, _storage)
            if sent:
                await add_message(user_id, "assistant", f"[sent {intent} teaser]")
                return

    # Classify SFW/NSFW
    classification = await classify(text, _classifier_provider.generate_simple)

    # Track engagement for soft-push logic
    await track_message(user_id, classification)

    # Pick provider
    provider = _nsfw_provider if classification == "nsfw" else _sfw_provider

    # Retrieve LTM memories
    ltm_memories = await retrieve_relevant(user_id, text)

    # Check if we should soft-push content
    push_hint = None
    if await should_soft_push(user_id):
        push_hint = "Naturally mention that you have exclusive content/pics/vids that you don't post anywhere else. Be subtle and flirty about it, like dropping a hint — not a hard sell."
        await record_push(user_id)

    # Build prompt and generate
    prompt_messages = build_prompt(_persona, ltm_memories, stm_messages, push_hint=push_hint)
    response_text = await provider.generate(prompt_messages)

    # Store bot response
    await add_message(user_id, "assistant", response_text)

    # Send with human-like delay
    await send_human_like(app, chat_id, response_text)


def register_handlers(app: Client) -> None:

    @app.on_message(filters.private & filters.text & filters.incoming)
    async def handle_message(client: Client, message: Message) -> None:
        logger.info("Message from %d: %s", message.from_user.id, (message.text or "")[:50])
        user_id = message.from_user.id

        # Cancel previous pending response if user sends another message
        if user_id in _active_tasks and not _active_tasks[user_id].done():
            _active_tasks[user_id].cancel()
            logger.info("Cancelled previous response task for user %d", user_id)

        task = asyncio.create_task(_process_message(client, message))
        _active_tasks[user_id] = task

        try:
            await task
        except asyncio.CancelledError:
            logger.info("Response task cancelled for user %d", user_id)
        except Exception as e:
            logger.error("Error processing message from user %d: %s", user_id, e, exc_info=True)
        finally:
            if _active_tasks.get(user_id) is task:
                del _active_tasks[user_id]
