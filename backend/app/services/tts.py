"""Text-to-speech through OpenRouter's /audio/speech (ElevenLabs Flash by default).

A failed TTS never fails the turn: it returns None and the browser speaks the text itself.
"""

import base64
import logging

from app.core.config import Settings
from app.schemas.ai import SpeechAudio
from app.services.openrouter import AIServiceError, OpenRouterClient

log = logging.getLogger(__name__)


class TTSService:
    def __init__(self, client: OpenRouterClient, settings: Settings):
        self.client = client
        self.s = settings

    @property
    def enabled(self) -> bool:
        return bool(self.s.tts_model)

    async def synthesize(self, text: str) -> SpeechAudio | None:
        if not self.enabled or not text.strip():
            return None
        payload = {"model": self.s.tts_model, "input": text, "response_format": self.s.tts_format}
        if self.s.tts_voice:
            payload["voice"] = self.s.tts_voice
        try:
            audio = await self.client.post_bytes("/audio/speech", payload)
        except AIServiceError as e:
            log.warning("TTS failed, browser will speak instead: %s", e)
            return None
        if not audio:
            return None
        return SpeechAudio(data_b64=base64.b64encode(audio).decode("ascii"), format=self.s.tts_format)
