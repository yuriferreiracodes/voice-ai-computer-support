from typing import Literal

from pydantic import BaseModel


class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    text: str


class UserTurn(BaseModel):
    """What the user sent this turn. Any combination of the fields can be set."""

    text: str | None = None
    audio_wav: bytes | None = None
    image_b64: str | None = None
    image_mime: str = "image/jpeg"


class SpeechAudio(BaseModel):
    data_b64: str
    format: str
