import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, TypeAdapter, ValidationError
from starlette.websockets import WebSocketState

from app.core.config import get_settings
from app.schemas.call import CLIENT_MESSAGE_TYPES, ClientMessage, ErrorOut
from app.services.voice_call import VoiceCallService

log = logging.getLogger(__name__)
router = APIRouter(tags=["call"])

_client_message = TypeAdapter(ClientMessage)


def parse_client_message(raw: str) -> ClientMessage | ErrorOut:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ErrorOut(code="bad_message", message="Invalid message format")
    if not isinstance(data, dict) or "type" not in data:
        return ErrorOut(code="bad_message", message="Invalid message format")
    if data["type"] not in CLIENT_MESSAGE_TYPES:
        return ErrorOut(code="unknown_type", message=f"Unknown message type: {data['type']}")
    try:
        return _client_message.validate_python(data)
    except ValidationError:
        return ErrorOut(code="bad_message", message="Invalid message format")


@router.websocket("/ws/call")
async def call(ws: WebSocket, session_id: str | None = Query(default=None)):
    settings = get_settings()
    origin = ws.headers.get("origin")
    if origin and settings.cors_origin_list != ["*"] and origin not in settings.cors_origin_list:
        log.warning("rejected websocket from origin %s", origin)
        await ws.close(code=4403)
        return
    await ws.accept()

    state = ws.app.state
    session, resumed = state.sessions.get_or_create(session_id)
    log.info("call %s (session %s)", "resumed" if resumed else "started", session.id[:8])

    lock = asyncio.Lock()

    async def send(msg: BaseModel) -> None:
        if ws.client_state != WebSocketState.CONNECTED:
            return
        async with lock:
            try:
                await ws.send_text(msg.model_dump_json())
            except (RuntimeError, WebSocketDisconnect):
                pass  # socket closed while sending

    service = VoiceCallService(session, state.sessions, state.llm, state.tts, settings, send)
    await service.start(resumed)
    try:
        while True:
            frame = await ws.receive()
            if frame["type"] == "websocket.disconnect":
                break
            if frame.get("bytes") is not None:
                await service.on_audio(frame["bytes"])
            elif frame.get("text") is not None:
                msg = parse_client_message(frame["text"])
                if isinstance(msg, ErrorOut):
                    await send(msg)
                elif await service.handle(msg):
                    break
    except WebSocketDisconnect:
        pass
    finally:
        service.close()
