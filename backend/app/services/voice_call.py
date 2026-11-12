"""One live support call: buffers the user's audio, runs turns (voice, text, screenshot)
and pushes the protocol messages back through `send`. Knows nothing about WebSockets."""

import asyncio
import base64
import binascii
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from pydantic import BaseModel

from app.core.config import Settings
from app.core.prompts import GREETING_INSTRUCTION, SCREENSHOT_DEFAULT_NOTE, SYSTEM_PROMPT
from app.schemas.ai import HistoryItem, UserTurn
from app.schemas.call import (
    AssistantOut,
    AudioEnd,
    AudioStart,
    CallState,
    ChatMessageOut,
    ClientMessage,
    End,
    EndedOut,
    ErrorOut,
    ImageIn,
    Interrupt,
    NoticeOut,
    Ping,
    PongOut,
    SessionOut,
    StatusOut,
    TextIn,
    UserMessageOut,
)
from app.services.llm import LLMService
from app.services.openrouter import AIServiceError
from app.services.session import Session, SessionStore
from app.services.tts import TTSService
from app.utils.audio import pcm16_to_wav

log = logging.getLogger(__name__)

ALLOWED_IMAGE_MIME = {"image/png", "image/jpeg", "image/webp"}

Sender = Callable[[BaseModel], Awaitable[None]]


class VoiceCallService:
    def __init__(
        self,
        session: Session,
        store: SessionStore,
        llm: LLMService,
        tts: TTSService,
        settings: Settings,
        send: Sender,
    ):
        self.session = session
        self.store = store
        self.llm = llm
        self.tts = tts
        self.s = settings
        self.send = send
        self.log = logging.LoggerAdapter(log, {"sid": session.id[:8]})
        self.audio = bytearray()
        self.recording = False
        self.turn: asyncio.Task | None = None
        self._bytes_per_s = settings.input_sample_rate * 2

    # ---------- lifecycle ----------

    async def start(self, resumed: bool) -> None:
        await self.send(SessionOut(
            session_id=self.session.id,
            resumed=resumed,
            messages=[ChatMessageOut(id=m.id, role=m.role, text=m.text, kind=m.kind) for m in self.session.messages],
        ))
        if self.s.greeting_enabled and not self.session.greeted:
            self.session.greeted = True
            self._start_turn(self._greet())
        else:
            await self._status("listening")

    def close(self) -> None:
        self._cancel_turn()
        self.session.last_seen = time.time()
        self.log.info("connection closed (messages=%d)", len(self.session.messages))

    # ---------- inbound ----------

    async def on_audio(self, chunk: bytes) -> None:
        if not self.recording:
            return
        self.audio.extend(chunk)
        if len(self.audio) >= self.s.max_utterance_s * self._bytes_per_s:
            self.log.info("max utterance length reached, processing")
            await self.send(NoticeOut(code="max_length", message="That was a long message, processing it now."))
            await self._finish_utterance()

    async def handle(self, msg: ClientMessage) -> bool:
        """Process one control message. Returns True when the call is over."""
        match msg:
            case AudioStart():
                if self._cancel_turn():
                    self.log.info("barge-in: user started speaking during a reply")
                self.audio.clear()
                self.recording = True
                await self._status("listening")
            case AudioEnd():
                await self._finish_utterance()
            case TextIn(text=text):
                text = text.strip()[:4000]
                if text:
                    self._start_turn(self._text_turn(text))
            case ImageIn():
                await self._on_image(msg)
            case Interrupt():
                self._cancel_turn()
                await self._status("listening")
            case Ping(t=t):
                await self.send(PongOut(t=t))
            case End():
                self._cancel_turn()
                self.store.remove(self.session.id)
                await self.send(EndedOut())
                self.log.info("call ended by user")
                return True
        return False

    async def _finish_utterance(self) -> None:
        self.recording = False
        pcm, self.audio = bytes(self.audio), bytearray()
        if len(pcm) % 2:
            pcm = pcm[:-1]
        secs = len(pcm) / self._bytes_per_s
        if secs < self.s.min_utterance_s:
            self.log.debug("ignoring %.2fs utterance (too short)", secs)
            await self._status("listening")
            return
        self.log.info("utterance received: %.1fs", secs)
        self._start_turn(self._voice_turn(pcm16_to_wav(pcm, self.s.input_sample_rate)))

    async def _on_image(self, msg: ImageIn) -> None:
        mime = msg.mime.lower()
        if mime not in ALLOWED_IMAGE_MIME:
            await self._error("bad_image", "Please upload a PNG, JPEG or WebP image.")
            return
        data = msg.data.split(",", 1)[-1] if msg.data.startswith("data:") else msg.data
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            await self._error("bad_image", "The screenshot could not be read.")
            return
        if not raw or len(raw) > self.s.max_image_bytes:
            await self._error("bad_image", f"Screenshot is too large (max {self.s.max_image_bytes // (1024 * 1024)} MB).")
            return
        note = (msg.note or "").strip()[:1000]
        self._start_turn(self._image_turn(data, mime, note))

    # ---------- turns ----------

    async def _greet(self) -> None:
        await self._reply([], UserTurn(text=GREETING_INSTRUCTION))

    async def _voice_turn(self, wav: bytes) -> None:
        await self._status("transcribing")
        history = self._history()
        # The model answers from the original audio (tone, names, error codes), so the reply
        # does not need the transcript: run both calls at once and save a full round trip.
        reply = asyncio.create_task(self.llm.reply(SYSTEM_PROMPT, history, UserTurn(audio_wav=wav)))
        reply.add_done_callback(_consume_exception)
        t0 = time.perf_counter()
        try:
            transcript = await self.llm.transcribe(wav)
        except BaseException:
            reply.cancel()
            raise
        if not transcript:
            reply.cancel()
            await self.send(NoticeOut(code="no_speech", message="I didn't catch that. Could you say it again?"))
            await self._status("listening")
            return
        m = self.session.add("user", transcript, "voice")
        self.log.info("user said (%d chars) in %.0fms", len(transcript), (time.perf_counter() - t0) * 1000)
        await self.send(UserMessageOut(id=m.id, role="user", text=transcript, kind="voice"))
        await self._status("thinking")
        await self._deliver(await reply, t0)

    async def _text_turn(self, text: str) -> None:
        history = self._history()
        m = self.session.add("user", text, "text")
        await self.send(UserMessageOut(id=m.id, role="user", text=text, kind="text"))
        await self._reply(history, UserTurn(text=text))

    async def _image_turn(self, image_b64: str, mime: str, note: str) -> None:
        history = self._history()
        label = f"[Shared a screenshot] {note}".strip()
        m = self.session.add("user", label, "image")
        await self.send(UserMessageOut(id=m.id, role="user", text=label, kind="image"))
        self.log.info("screenshot received (%s, %d b64 chars)", mime, len(image_b64))
        await self._reply(history, UserTurn(text=note or SCREENSHOT_DEFAULT_NOTE, image_b64=image_b64, image_mime=mime))

    async def _reply(self, history: list[HistoryItem], turn: UserTurn) -> None:
        await self._status("thinking")
        t0 = time.perf_counter()
        await self._deliver(await self.llm.reply(SYSTEM_PROMPT, history, turn), t0)

    async def _deliver(self, text: str, t0: float) -> None:
        t_text = time.perf_counter()
        speech = await self.tts.synthesize(text)
        m = self.session.add("assistant", text)
        self.log.info(
            "assistant reply: %d chars, llm %.0fms, tts %.0fms (%s)",
            len(text), (t_text - t0) * 1000, (time.perf_counter() - t_text) * 1000, "ok" if speech else "browser",
        )
        await self.send(AssistantOut(
            id=m.id, text=text,
            audio=speech.data_b64 if speech else None,
            audio_source="tts" if speech else "none",
        ))
        await self._status("listening")

    def _history(self) -> list[HistoryItem]:
        return self.session.history_for_model(self.s.max_history_messages)

    # ---------- plumbing ----------

    async def _status(self, state: CallState) -> None:
        await self.send(StatusOut(state=state))

    async def _error(self, code: str, message: str, recoverable: bool = True) -> None:
        await self.send(ErrorOut(code=code, message=message, recoverable=recoverable))

    def _cancel_turn(self) -> bool:
        if self.turn and not self.turn.done():
            self.turn.cancel()
            return True
        return False

    def _start_turn(self, coro: Coroutine[Any, Any, None]) -> None:
        self._cancel_turn()
        self.turn = asyncio.create_task(self._guard(coro))

    async def _guard(self, coro: Coroutine[Any, Any, None]) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            self.log.info("turn cancelled")
            raise
        except AIServiceError as e:
            self.log.error("AI error: %s", e)
            await self._error("ai_unavailable", str(e))
            await self._status("listening")
        except Exception:
            self.log.exception("turn failed")
            await self._error("internal", "Something went wrong while answering. Please try again.")
            await self._status("listening")


def _consume_exception(task: asyncio.Task) -> None:
    """Avoid 'Task exception was never retrieved' when a parallel reply is discarded."""
    if not task.cancelled():
        task.exception()
