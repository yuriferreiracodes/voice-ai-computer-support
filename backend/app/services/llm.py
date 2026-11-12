"""The omni model (Qwen3.8 Omni Flash by default): transcribes the user and writes the reply."""

import base64
from typing import Any

from app.core.config import Settings
from app.core.prompts import TRANSCRIBE_PROMPT
from app.schemas.ai import HistoryItem, UserTurn
from app.services.openrouter import AIServiceError, OpenRouterClient


class LLMService:
    def __init__(self, client: OpenRouterClient, settings: Settings):
        self.client = client
        self.s = settings

    async def transcribe(self, wav: bytes) -> str:
        payload = self._payload(
            [{"role": "user", "content": _user_content(UserTurn(text=TRANSCRIBE_PROMPT, audio_wav=wav))}],
            max_tokens=300,
            temperature=0.0,
        )
        return _completion_text(await self.client.post_json("/chat/completions", payload))

    async def reply(self, system: str, history: list[HistoryItem], turn: UserTurn) -> str:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        messages += [{"role": h.role, "content": h.text} for h in history]
        messages.append({"role": "user", "content": _user_content(turn)})
        payload = self._payload(messages, max_tokens=self.s.llm_max_tokens, temperature=self.s.llm_temperature)
        text = _completion_text(await self.client.post_json("/chat/completions", payload))
        if not text:
            raise AIServiceError("The AI returned an empty answer")
        return text

    def _payload(self, messages: list[dict], *, max_tokens: int, temperature: float) -> dict[str, Any]:
        return {
            "model": self.s.llm_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "reasoning": {"enabled": self.s.llm_reasoning},
        }


def _user_content(turn: UserTurn) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    if turn.image_b64:
        parts.append({"type": "image_url", "image_url": {"url": f"data:{turn.image_mime};base64,{turn.image_b64}"}})
    if turn.audio_wav:
        audio_b64 = base64.b64encode(turn.audio_wav).decode("ascii")
        parts.append({"type": "input_audio", "input_audio": {"data": audio_b64, "format": "wav"}})
    if turn.text:
        parts.append({"type": "text", "text": turn.text})
    return parts


def _completion_text(data: dict[str, Any]) -> str:
    for choice in data.get("choices") or []:
        content = (choice.get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            text = " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text").strip()
            if text:
                return text
    return ""
