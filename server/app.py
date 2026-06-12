"""
FastAPI server — entrypoint for the AI girlfriend chat demo.
Replaces the Telegram bot with HTTP + WebSocket endpoints.
"""

import asyncio
import json
import logging
import time
import base64
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from bot.config import (
    SERVER_HOST, SERVER_PORT, CONTENT_DIR, PERSONA_FILE, NSFW_PERSONA_FILE,
    DEFAULT_USER_ID,
)
from bot.memory.db import init_db, get_connection
from bot.memory.stm import get_all_messages
from bot.persona import load_persona
from bot.providers.anthropic_provider import AnthropicProvider
from bot.providers.gemini_provider import GeminiProvider
from bot.providers.grok_provider import GrokProvider
from bot.chat_engine import ChatEngine, ChatResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Global chat engine
engine: ChatEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB and providers on startup."""
    global engine

    logger.info("Initializing database...")
    await init_db()

    logger.info("Loading personas...")
    persona = load_persona()
    nsfw_persona = load_persona(NSFW_PERSONA_FILE) if Path(NSFW_PERSONA_FILE).exists() else None
    logger.info("Persona loaded: %s", persona.name)

    logger.info("Initializing LLM providers...")
    sfw_provider = AnthropicProvider()
    nsfw_provider = GrokProvider()
    classifier_provider = GeminiProvider()
    vision_provider = GrokProvider()

    engine = ChatEngine(
        persona=persona,
        nsfw_persona=nsfw_persona,
        sfw_provider=sfw_provider,
        nsfw_provider=nsfw_provider,
        classifier_provider=classifier_provider,
        vision_provider=vision_provider,
    )
    logger.info("Chat engine ready")

    yield

    logger.info("Shutting down")


app = FastAPI(title="AI Girlfriend Chat", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve content files if directory exists
if Path(CONTENT_DIR).exists():
    app.mount("/content", StaticFiles(directory=str(CONTENT_DIR)), name="content")


# ------------------------------------------------------------------
# REST endpoints
# ------------------------------------------------------------------

@app.get("/api/profile")
async def get_profile():
    """Return persona profile data for the sidebar."""
    persona = engine.persona if engine else None
    if not persona:
        return JSONResponse({"error": "Engine not ready"}, status_code=503)

    general = persona.general
    profile_data = general.get("profile", {})

    return {
        "name": general.get("name", "Victoria"),
        "tagline": general.get("tagline", ""),
        "physical_description": general.get("physical_description", ""),
        "profile": profile_data,
        "opening_lines": persona.opening_lines,
    }


@app.get("/api/history/{mode}")
async def get_history(mode: str, user_id: int = Query(default=None)):
    """Return chat history for a specific mode. Seeds opening message for new sexting users."""
    user_id = user_id or DEFAULT_USER_ID
    if mode not in ("sexting", "story"):
        return JSONResponse({"error": "Invalid mode"}, status_code=400)

    messages = await get_all_messages(user_id, mode=mode)

    # Seed opening message for new sexting users (Victoria initiates).
    # The opening may contain multiple lines — each becomes its own bubble.
    if mode == "sexting" and not messages and engine:
        from bot.memory.stm import add_message as stm_add
        opening = engine.persona.get_random_opening()
        parts = [p.strip() for p in opening.split("\n") if p.strip()]
        for part in parts:
            await stm_add(user_id, "assistant", part, mode="sexting")
        messages = await get_all_messages(user_id, mode=mode)

    # Seed opening narration for new story users (chapter 1 scene-setter)
    if mode == "story" and not messages and engine:
        from bot.memory.stm import add_message as stm_add
        from bot.config import STORY_FILE
        try:
            with open(str(STORY_FILE), "r", encoding="utf-8") as f:
                story_data = yaml.safe_load(f)
            ch1 = story_data.get("chapters", [{}])[0]
            setting = ch1.get("setting", "")
            first_beat = ch1.get("narrative_beats", [""])[0]
            opening = (
                f"*{setting}*\n\n"
                f"*You push the door open without thinking. And there she is.*\n\n"
                f"{first_beat}"
            )
            await stm_add(user_id, "assistant", opening, mode="story")
            messages = await get_all_messages(user_id, mode=mode)
        except Exception:
            pass

    return {
        "mode": mode,
        "messages": [
            {
                "role": m["role"],
                "content": m["content"],
                "timestamp": m["timestamp"],
            }
            for m in messages
            if m["role"] in ("user", "assistant")
        ],
    }


@app.get("/api/story/chapter")
async def get_story_chapter(user_id: int = Query(default=None)):
    """Get current story chapter."""
    if not engine:
        return JSONResponse({"error": "Engine not ready"}, status_code=503)
    uid = user_id or DEFAULT_USER_ID
    chapter = await engine.get_story_chapter(uid)
    return {"chapter": chapter}


@app.post("/api/reset")
async def reset_user(user_id: int = Query(default=None)):
    """Wipe all data for a user — messages, memories, intimacy, story progress, facts, engagement."""
    uid = user_id or DEFAULT_USER_ID
    conn = await get_connection()
    try:
        for table in ("messages", "memories", "user_facts", "sent_content",
                      "story_progress", "engagement_state", "intimacy_state"):
            try:
                await conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (uid,))
            except Exception:
                pass  # table may not exist yet
        await conn.commit()
        logger.info("Reset all data for user %d", uid)
    finally:
        await conn.close()
    return {"status": "ok", "user_id": uid}


# ------------------------------------------------------------------
# WebSocket chat
# ------------------------------------------------------------------

class ConnectionManager:
    """Track active WebSocket connections."""

    def __init__(self):
        self.active: dict[int, WebSocket] = {}

    async def connect(self, user_id: int, ws: WebSocket):
        await ws.accept()
        self.active[user_id] = ws
        logger.info("WebSocket connected: user %d", user_id)

    def disconnect(self, user_id: int):
        self.active.pop(user_id, None)
        logger.info("WebSocket disconnected: user %d", user_id)

    async def send_json(self, user_id: int, data: dict):
        ws = self.active.get(user_id)
        if ws:
            await ws.send_json(data)


manager = ConnectionManager()


async def _send_response_with_typing(user_id: int, response: ChatResponse, mode: str):
    """Send response messages with typing simulation delays."""
    import random

    ws = manager.active.get(user_id)
    if not ws:
        return

    for i, msg in enumerate(response.messages):
        # Typing indicator
        await manager.send_json(user_id, {"type": "typing_start"})

        # Typing delay scaled to message length
        length = len(msg)
        if length < 50:
            delay = random.uniform(1.0, 2.5)
        elif length < 150:
            delay = random.uniform(2.0, 4.0)
        else:
            delay = random.uniform(3.0, 6.0)

        await asyncio.sleep(delay)
        await manager.send_json(user_id, {"type": "typing_end"})

        # Send the message
        await manager.send_json(user_id, {
            "type": "message",
            "role": "assistant",
            "content": msg,
            "timestamp": time.time(),
            "mode": mode,
        })

        # Brief pause between multi-bubble messages
        if i < len(response.messages) - 1:
            await asyncio.sleep(random.uniform(0.5, 1.5))

    # Send content URLs if any
    for url in response.content_urls:
        await manager.send_json(user_id, {
            "type": "image",
            "url": url,
            "timestamp": time.time(),
            "mode": mode,
        })


@app.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket, user_id: int = Query(default=None), user_name: str = Query(default=None)):
    user_id = user_id or DEFAULT_USER_ID
    await manager.connect(user_id, ws)

    # Save user name as a fact (so Victoria knows who she's talking to)
    if user_name:
        from bot.memory.facts import upsert_fact
        await upsert_fact(user_id, "name", user_name)

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)

            msg_type = data.get("type", "message")
            mode = data.get("mode", "sexting")
            text = data.get("content", "").strip()

            # Handle image uploads via WebSocket (base64)
            image_bytes = None
            if data.get("image"):
                try:
                    image_bytes = base64.b64decode(data["image"])
                except Exception:
                    pass

            if not text and not image_bytes:
                continue

            logger.info("WS message from user %d [%s]: %s", user_id, mode, (text or "[image]")[:80])

            if mode == "story":
                # Story mode: direct processing, one at a time
                response = await engine.process_message(user_id, text, mode="story", image_bytes=image_bytes)
                await _send_response_with_typing(user_id, response, mode="story")
            else:
                # Sexting mode: batched processing
                async def on_response(resp: ChatResponse):
                    await _send_response_with_typing(user_id, resp, mode="sexting")

                await engine.process_sexting_batched(
                    user_id, text, image_bytes=image_bytes, on_response=on_response
                )

    except WebSocketDisconnect:
        manager.disconnect(user_id)
    except Exception as e:
        logger.error("WebSocket error: %s", e, exc_info=True)
        manager.disconnect(user_id)


# ------------------------------------------------------------------
# Run
# ------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.app:app", host=SERVER_HOST, port=SERVER_PORT, reload=True)
