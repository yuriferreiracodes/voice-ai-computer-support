import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.routes import call, health
from app.services.llm import LLMService
from app.services.openrouter import OpenRouterClient
from app.services.session import SessionStore
from app.services.tts import TTSService

settings = get_settings()
setup_logging(settings.log_level)
log = logging.getLogger("backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = OpenRouterClient(settings)
    app.state.openrouter = client
    app.state.llm = LLMService(client, settings)
    app.state.tts = TTSService(client, settings)
    app.state.sessions = SessionStore(settings.session_ttl_s)
    if not settings.openrouter_api_key:
        log.warning("OPENROUTER_API_KEY is empty: every AI call will fail")
    log.info("Backend up. LLM: %s | TTS: %s", settings.llm_model, settings.tts_model or "(browser)")
    yield
    await client.close()


app = FastAPI(title="AI Computer Support", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(health.router)
app.include_router(call.router)
