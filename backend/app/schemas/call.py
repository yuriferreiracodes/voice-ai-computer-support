"""WebSocket call protocol (`/ws/call`). Mirrored by frontend/src/lib/protocol.ts.

client -> server
  <binary>                      PCM16 little-endian mono audio at INPUT_SAMPLE_RATE (16 kHz)
  {"type": "audio_start"}       user started speaking (also interrupts the AI)
  {"type": "audio_end"}         user stopped speaking -> process the utterance
  {"type": "text", "text"}      typed message
  {"type": "image", "data", "mime", "note"?}   screenshot (base64)
  {"type": "interrupt"}         stop the reply being generated
  {"type": "ping", "t"?}
  {"type": "end"}               end the call

server -> client
  {"type": "session", "session_id", "resumed", "messages"}
  {"type": "status", "state": "listening|transcribing|thinking"}
  {"type": "message", "id", "role", "text", "kind"}             user transcript
  {"type": "assistant", "id", "text", "audio", "audio_source"}  reply (+ base64 mp3/wav, or null)
  {"type": "notice", "code", "message"}
  {"type": "error", "code", "message", "recoverable"}
  {"type": "pong", "t"} / {"type": "ended"}
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

Role = Literal["user", "assistant"]
MessageKind = Literal["voice", "text", "image"]
CallState = Literal["listening", "transcribing", "thinking"]


# ---------- client -> server ----------


class AudioStart(BaseModel):
    type: Literal["audio_start"]


class AudioEnd(BaseModel):
    type: Literal["audio_end"]


class TextIn(BaseModel):
    type: Literal["text"]
    text: str = ""


class ImageIn(BaseModel):
    type: Literal["image"]
    data: str = ""
    mime: str = "image/jpeg"
    note: str | None = None


class Interrupt(BaseModel):
    type: Literal["interrupt"]


class Ping(BaseModel):
    type: Literal["ping"]
    t: Any = None


class End(BaseModel):
    type: Literal["end"]


ClientMessage = Annotated[
    AudioStart | AudioEnd | TextIn | ImageIn | Interrupt | Ping | End,
    Field(discriminator="type"),
]
CLIENT_MESSAGE_TYPES = {"audio_start", "audio_end", "text", "image", "interrupt", "ping", "end"}


# ---------- server -> client ----------


class ChatMessageOut(BaseModel):
    id: str
    role: Role
    text: str
    kind: MessageKind


class SessionOut(BaseModel):
    type: Literal["session"] = "session"
    session_id: str
    resumed: bool
    messages: list[ChatMessageOut]


class StatusOut(BaseModel):
    type: Literal["status"] = "status"
    state: CallState


class UserMessageOut(ChatMessageOut):
    type: Literal["message"] = "message"


class AssistantOut(BaseModel):
    type: Literal["assistant"] = "assistant"
    id: str
    text: str
    audio: str | None  # base64 audio file (mp3 by default); null -> the browser speaks the text
    audio_source: Literal["tts", "none"]


class NoticeOut(BaseModel):
    type: Literal["notice"] = "notice"
    code: str
    message: str


class ErrorOut(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
    recoverable: bool = True


class PongOut(BaseModel):
    type: Literal["pong"] = "pong"
    t: Any = None


class EndedOut(BaseModel):
    type: Literal["ended"] = "ended"
