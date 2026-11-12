from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every field can be overridden with an env var of the same name (case-insensitive)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---------- OpenRouter ----------
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    ai_timeout_s: float = 60.0
    ai_retries: int = 1

    # Omni model: hears the user's audio, sees screenshots, writes the reply text.
    llm_model: str = "qwen/qwen3.8-omni-flash"
    # Reasoning makes Qwen3.8 Omni ~10x slower (19 s vs 2 s per turn): keep it off for a live call.
    llm_reasoning: bool = False
    llm_max_tokens: int = 400
    llm_temperature: float = 0.6

    # Text-to-speech for the reply. Empty TTS_MODEL = no server voice (the browser speaks instead).
    tts_model: str = "elevenlabs/eleven-flash-v2.5"
    tts_voice: str = "21m00Tcm4TlvDq8ikWAM"  # ElevenLabs "Rachel" (English)
    tts_format: str = "mp3"

    # ---------- Call ----------
    # Comma-separated list of allowed browser origins
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Audio arriving over the WebSocket: PCM16 LE mono at this rate
    input_sample_rate: int = 16000
    min_utterance_s: float = 0.35
    max_utterance_s: float = 30.0

    max_image_bytes: int = 6 * 1024 * 1024
    max_history_messages: int = 30
    session_ttl_s: int = 15 * 60

    greeting_enabled: bool = True
    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
