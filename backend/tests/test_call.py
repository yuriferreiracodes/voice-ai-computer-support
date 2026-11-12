import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings, get_settings
from app.core.prompts import TRANSCRIBE_PROMPT
from app.main import app
from app.services.llm import LLMService
from app.services.openrouter import OpenRouterClient
from app.services.tts import TTSService

ONE_SECOND_PCM = b"\x10\x00" * 16000
FAKE_MP3 = b"ID3\x04fake-mp3"


class FakeOpenRouter:
    """Stands in for openrouter.ai: /chat/completions (transcribe + reply) and /audio/speech."""

    def __init__(self, transcript: str = "my wifi does not work", fail: bool = False, tts_status: int = 200):
        self.transcript = transcript
        self.fail = fail
        self.tts_status = tts_status
        self.replies: list[dict] = []
        self.transcribes: list[dict] = []
        self.speech: list[dict] = []
        self.auth: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            raise httpx.ConnectError("connection refused")
        self.auth.add(request.headers.get("authorization", ""))
        body = json.loads(request.content)
        if request.url.path.endswith("/audio/speech"):
            self.speech.append(body)
            if self.tts_status != 200:
                return httpx.Response(self.tts_status, json={"error": {"message": "tts down"}})
            return httpx.Response(200, content=FAKE_MP3, headers={"content-type": "audio/mpeg"})
        last = body["messages"][-1]["content"]
        if isinstance(last, list) and any(p.get("text") == TRANSCRIBE_PROMPT for p in last):
            self.transcribes.append(body)
            return _completion(self.transcript)
        self.replies.append(body)
        return _completion(f"reply {len(self.replies)}")


def _completion(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": text}}]})


@pytest.fixture
def make_client(monkeypatch):
    clients: list[TestClient] = []

    def _make(fake: FakeOpenRouter, greeting: bool = False, api_key: str = "test-key") -> TestClient:
        monkeypatch.setattr(get_settings(), "greeting_enabled", greeting)
        client = TestClient(app)
        client.__enter__()  # runs lifespan
        s = Settings(openrouter_api_key=api_key, ai_retries=0)
        router = OpenRouterClient(s, transport=httpx.MockTransport(fake))
        app.state.openrouter = router
        app.state.llm = LLMService(router, s)
        app.state.tts = TTSService(router, s)
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def recv_until(ws, type_):
    for _ in range(20):
        msg = ws.receive_json()
        if msg["type"] == type_:
            return msg
    raise AssertionError(f"never received {type_}")


def speak(ws, pcm: bytes = ONE_SECOND_PCM) -> None:
    ws.send_json({"type": "audio_start"})
    ws.send_bytes(pcm)
    ws.send_json({"type": "audio_end"})


def test_health(make_client):
    c = make_client(FakeOpenRouter())
    assert c.get("/health").json()["status"] == "ok"


def test_greeting_on_connect_has_tts_audio(make_client):
    fake = FakeOpenRouter()
    c = make_client(fake, greeting=True)
    with c.websocket_connect("/ws/call") as ws:
        assert ws.receive_json()["type"] == "session"
        msg = recv_until(ws, "assistant")
        assert msg["text"] == "reply 1"
        assert base64.b64decode(msg["audio"]) == FAKE_MP3 and msg["audio_source"] == "tts"
    # system prompt + greeting instruction only
    assert [m["role"] for m in fake.replies[0]["messages"]] == ["system", "user"]
    assert fake.speech[0]["input"] == "reply 1" and fake.speech[0]["voice"]
    assert fake.auth == {"Bearer test-key"}


def test_voice_turn_full_flow_and_history(make_client):
    fake = FakeOpenRouter()
    c = make_client(fake)
    with c.websocket_connect("/ws/call") as ws:
        session = ws.receive_json()
        assert session["type"] == "session" and not session["resumed"]
        for _ in range(2):
            speak(ws)
            user = recv_until(ws, "message")
            assert user["role"] == "user" and user["text"] == "my wifi does not work"
            assert recv_until(ws, "assistant")["audio"]

    assert len(fake.transcribes) == 2
    second = fake.replies[1]["messages"]
    # system, first exchange as text history, then the new turn as audio
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert second[1]["content"] == "my wifi does not work" and second[2]["content"] == "reply 1"
    audio = second[3]["content"][0]
    assert audio["type"] == "input_audio" and audio["input_audio"]["format"] == "wav"
    assert base64.b64decode(audio["input_audio"]["data"])[:4] == b"RIFF"


def test_reasoning_is_disabled_by_default(make_client):
    fake = FakeOpenRouter()
    c = make_client(fake)
    with c.websocket_connect("/ws/call") as ws:
        ws.receive_json()
        speak(ws)
        recv_until(ws, "assistant")
    for body in fake.transcribes + fake.replies:
        assert body["reasoning"] == {"enabled": False}
        assert body["model"] == "qwen/qwen3.8-omni-flash"


def test_no_speech_discards_parallel_reply(make_client):
    fake = FakeOpenRouter(transcript="")
    c = make_client(fake)
    with c.websocket_connect("/ws/call") as ws:
        ws.receive_json()
        speak(ws)
        assert recv_until(ws, "notice")["code"] == "no_speech"
        ws.send_json({"type": "ping"})
        recv_until(ws, "pong")
    assert fake.speech == []  # nothing was spoken


def test_tts_failure_falls_back_to_browser_voice(make_client):
    c = make_client(FakeOpenRouter(tts_status=500))
    with c.websocket_connect("/ws/call") as ws:
        ws.receive_json()
        ws.send_json({"type": "text", "text": "hello"})
        msg = recv_until(ws, "assistant")
        assert msg["text"] == "reply 1" and msg["audio"] is None and msg["audio_source"] == "none"


def test_too_short_audio_is_ignored(make_client):
    fake = FakeOpenRouter()
    c = make_client(fake)
    with c.websocket_connect("/ws/call") as ws:
        ws.receive_json()
        ws.receive_json()  # listening
        speak(ws, b"\x00\x00" * 1000)
        ws.send_json({"type": "ping"})
        assert recv_until(ws, "pong")
    assert fake.replies == [] and fake.transcribes == []


def test_text_and_image_turns(make_client):
    fake = FakeOpenRouter()
    c = make_client(fake)
    img = base64.b64encode(b"\x89PNG fake image").decode()
    with c.websocket_connect("/ws/call") as ws:
        ws.receive_json()
        ws.send_json({"type": "text", "text": "No sound from speakers"})
        recv_until(ws, "assistant")
        ws.send_json({"type": "image", "mime": "image/png", "data": img, "note": "this popped up"})
        user = recv_until(ws, "message")
        assert user["kind"] == "image"
        recv_until(ws, "assistant")
    parts = fake.replies[1]["messages"][-1]["content"]
    assert parts[0]["image_url"]["url"] == f"data:image/png;base64,{img}"
    assert parts[1] == {"type": "text", "text": "this popped up"}


def test_bad_image_rejected(make_client):
    c = make_client(FakeOpenRouter())
    with c.websocket_connect("/ws/call") as ws:
        ws.receive_json()
        ws.send_json({"type": "image", "mime": "application/pdf", "data": "AAAA"})
        assert recv_until(ws, "error")["code"] == "bad_image"


def test_ai_unreachable_sends_recoverable_error(make_client):
    c = make_client(FakeOpenRouter(fail=True))
    with c.websocket_connect("/ws/call") as ws:
        ws.receive_json()
        ws.send_json({"type": "text", "text": "hello"})
        err = recv_until(ws, "error")
        assert err["code"] == "ai_unavailable" and err["recoverable"]
        ws.send_json({"type": "ping"})  # the call stays usable
        assert recv_until(ws, "pong")


def test_missing_api_key_is_reported(make_client):
    c = make_client(FakeOpenRouter(), api_key="")
    with c.websocket_connect("/ws/call") as ws:
        ws.receive_json()
        ws.send_json({"type": "text", "text": "hello"})
        assert "OPENROUTER_API_KEY" in recv_until(ws, "error")["message"]


@pytest.mark.parametrize(("raw", "code"), [("not json", "bad_message"), ('{"type": "dance"}', "unknown_type"), ("[1]", "bad_message")])
def test_invalid_messages(make_client, raw, code):
    c = make_client(FakeOpenRouter())
    with c.websocket_connect("/ws/call") as ws:
        ws.receive_json()
        ws.send_text(raw)
        assert recv_until(ws, "error")["code"] == code


def test_resume_session_keeps_history(make_client):
    c = make_client(FakeOpenRouter())
    with c.websocket_connect("/ws/call") as ws:
        sid = ws.receive_json()["session_id"]
        ws.send_json({"type": "text", "text": "hi"})
        recv_until(ws, "assistant")
    with c.websocket_connect(f"/ws/call?session_id={sid}") as ws:
        session = ws.receive_json()
        assert session["resumed"] and len(session["messages"]) == 2


def test_end_call_removes_session(make_client):
    c = make_client(FakeOpenRouter())
    with c.websocket_connect("/ws/call") as ws:
        sid = ws.receive_json()["session_id"]
        ws.send_json({"type": "end"})
        assert recv_until(ws, "ended")
    with c.websocket_connect(f"/ws/call?session_id={sid}") as ws:
        assert not ws.receive_json()["resumed"]


def test_rejects_foreign_origin(make_client):
    c = make_client(FakeOpenRouter())
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/ws/call", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()


def test_provider_error_reason_is_surfaced():
    from app.services.openrouter import _error_detail

    raw = json.dumps({"error": {"message": "image too small", "type": "invalid_request_error"}})
    r = httpx.Response(400, json={"error": {"message": "Provider returned error", "code": 400, "metadata": {"raw": raw}}})
    assert _error_detail(r) == "Provider returned error: image too small"
    assert _error_detail(httpx.Response(401, json={"error": {"message": "No auth"}})) == "No auth"
