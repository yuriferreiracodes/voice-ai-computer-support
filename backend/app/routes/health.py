import httpx
from fastapi import APIRouter, Request

from app.core.config import get_settings
from app.schemas.health import AIHealthOut, HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health(request: Request) -> HealthOut:
    return HealthOut(status="ok", active_sessions=len(request.app.state.sessions))


@router.get("/health/ai", response_model=AIHealthOut)
async def health_ai(request: Request) -> AIHealthOut:
    """Checks that the OpenRouter key is set and accepted (does not spend credits)."""
    s = get_settings()
    out = AIHealthOut(status="ok", llm_model=s.llm_model, tts_model=s.tts_model or "(browser)")
    if not s.openrouter_api_key:
        out.status, out.detail = "missing_key", "Set OPENROUTER_API_KEY in .env"
        return out
    try:
        await request.app.state.openrouter.get_json("/key")
    except httpx.HTTPStatusError as e:
        out.status, out.detail = "error", f"OpenRouter rejected the key (HTTP {e.response.status_code})"
    except httpx.HTTPError as e:
        out.status, out.detail = "unreachable", str(e) or type(e).__name__
    return out
