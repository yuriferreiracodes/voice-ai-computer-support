"""Thin HTTP client for OpenRouter: auth, timeouts, retries and error mapping. No model logic here."""

import asyncio
import json
import logging
from typing import Any

import httpx

from app.core.config import Settings

log = logging.getLogger(__name__)


class AIServiceError(RuntimeError):
    """The model provider failed. The message is safe to show to the user."""


class OpenRouterClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.s = settings
        self.http = httpx.AsyncClient(
            base_url=settings.openrouter_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            timeout=httpx.Timeout(settings.ai_timeout_s, connect=10.0),
            transport=transport,
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return (await self._post(path, payload)).json()

    async def post_bytes(self, path: str, payload: dict[str, Any]) -> bytes:
        return (await self._post(path, payload)).content

    async def get_json(self, path: str, timeout_s: float = 5.0) -> dict[str, Any]:
        r = await self.http.get(path, timeout=timeout_s)
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        if not self.s.openrouter_api_key:
            raise AIServiceError("OPENROUTER_API_KEY is not set on the backend")
        model = payload.get("model", "?")
        last: AIServiceError | None = None
        for attempt in range(self.s.ai_retries + 1):
            retry = attempt < self.s.ai_retries
            try:
                r = await self.http.post(path, json=payload)
            except httpx.TimeoutException:
                log.warning("%s %s timed out (attempt %d)", path, model, attempt + 1)
                last = AIServiceError("The AI model took too long to answer")
            except httpx.HTTPError as e:
                log.warning("%s %s unreachable: %s (attempt %d)", path, model, e, attempt + 1)
                last = AIServiceError("Cannot reach the AI provider")
            else:
                if r.status_code < 400:
                    return r
                detail = _error_detail(r)
                log.warning("%s %s -> HTTP %d: %s", path, model, r.status_code, detail)
                last = AIServiceError(f"AI provider error ({r.status_code}): {detail}")
                if r.status_code != 429 and r.status_code < 500:
                    raise last  # bad request / auth / unknown model: retrying won't help
            if retry:
                await asyncio.sleep(0.5 * (attempt + 1))
        raise last or AIServiceError("AI provider failed")


def _error_detail(r: httpx.Response) -> str:
    """OpenRouter wraps upstream failures as "Provider returned error" with the real reason
    in error.metadata.raw (a JSON string from the provider). Surface that reason."""
    try:
        err = r.json().get("error", {})
    except ValueError:
        return (r.text or r.reason_phrase)[:300]
    if not isinstance(err, dict):
        return str(err)[:300]
    msg = err.get("message") or r.reason_phrase
    raw = (err.get("metadata") or {}).get("raw")
    if raw:
        try:
            inner = json.loads(raw).get("error", {})
            raw = inner.get("message", raw) if isinstance(inner, dict) else raw
        except (ValueError, AttributeError):
            pass
        msg = f"{msg}: {raw}"
    return str(msg)[:300]
