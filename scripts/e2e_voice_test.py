#!/usr/bin/env python3
"""End-to-end voice call test against a running stack (docker compose up).

Speaks real audio into the WebSocket exactly like the browser does (16 kHz PCM16
frames of 20 ms), then checks the transcript, the reply text and the reply audio,
over several turns plus a screenshot.

    pip install websockets
    python scripts/e2e_voice_test.py                       # generates natural speech with the OpenRouter TTS (via the backend container)
    python scripts/e2e_voice_test.py --wav my_question.wav # or use your own recording
    python scripts/e2e_voice_test.py --url ws://gpu-box:8000/ws/call
"""

import argparse
import asyncio
import base64
import io
import json
import subprocess
import sys
import time
import wave
from array import array
from pathlib import Path

import websockets

TARGET_RATE = 16000
FRAME = 320  # 20 ms
OUT = Path(__file__).parent / "out"

PROMPTS = [
    "Hi, my Wi-Fi stopped working on my Windows 11 laptop this morning.",
    "The icon shows a globe and says no internet.",
]

# 64x64 blue PNG (Qwen rejects images with a side of 10 px or less)
TINY_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAT0lEQVR42u3PQQkAAAgEsEtiEvtjLCP4FgYrsFTPaxEQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQuCwwHSEPxotItwAAAABJRU5ErkJggg=="
)


TTS_SNIPPET = """
import httpx, os, sys
from app.core.config import get_settings
s = get_settings()
r = httpx.post(s.openrouter_base_url + "/audio/speech", timeout=60,
    headers={"Authorization": "Bearer " + s.openrouter_api_key},
    json={"model": s.tts_model, "voice": s.tts_voice, "input": sys.argv[1], "response_format": "pcm"})
r.raise_for_status()
sys.stdout.buffer.write(r.content)
"""


def tts_wav(text: str) -> bytes:
    """Natural speech (24 kHz PCM16) from the configured OpenRouter TTS, wrapped as WAV."""
    pcm = subprocess.run(
        ["docker", "compose", "exec", "-T", "backend", "python", "-c", TTS_SNIPPET, text],
        check=True, capture_output=True,
    ).stdout
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)
    return buf.getvalue()


def to_pcm16k(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise SystemExit("need 16-bit WAV")
    s = array("h", raw)
    if ch > 1:
        s = array("h", (sum(s[i:i + ch]) // ch for i in range(0, len(s), ch)))
    if rate != TARGET_RATE:
        ratio = rate / TARGET_RATE
        s = array("h", (s[min(int(i * ratio), len(s) - 1)] for i in range(int(len(s) / ratio))))
    return s.tobytes()


async def recv(ws, *types, timeout=240):
    deadline = time.time() + timeout
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=max(1, deadline - time.time())))
        print(f"  <- {msg['type']}: " + (msg.get("text") or msg.get("state") or msg.get("message") or "")[:110])
        if msg["type"] == "error":
            raise AssertionError(f"server error: {msg}")
        if msg["type"] in types:
            return msg


def check_reply(reply: dict, n: int) -> None:
    assert reply["text"], "empty reply text"
    if reply["audio"]:
        audio = base64.b64decode(reply["audio"])
        ext = "wav" if audio[:4] == b"RIFF" else "mp3"
        assert ext == "wav" or audio[:3] == b"ID3" or audio[0] == 0xFF, "reply audio is neither WAV nor MP3"
        OUT.mkdir(exist_ok=True)
        (OUT / f"reply_{n}.{ext}").write_bytes(audio)
        print(f"     audio: {len(audio) // 1024} KB {ext} from {reply['audio_source']} -> scripts/out/reply_{n}.{ext}")
    else:
        print("     audio: none (browser would use speech synthesis)")


async def speak(ws, pcm: bytes, realtime: bool) -> None:
    await ws.send(json.dumps({"type": "audio_start"}))
    for i in range(0, len(pcm), FRAME * 2):
        await ws.send(pcm[i:i + FRAME * 2])
        if realtime:
            await asyncio.sleep(0.02)
    await ws.send(b"\x00\x00" * FRAME * 10)  # a bit of trailing silence
    await ws.send(json.dumps({"type": "audio_end"}))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://localhost:8000/ws/call")
    ap.add_argument("--wav", action="append", help="WAV file(s) to send as user turns")
    ap.add_argument("--fast", action="store_true", help="don't pace audio in real time")
    args = ap.parse_args()

    turns = [Path(p).read_bytes() for p in args.wav] if args.wav else [tts_wav(t) for t in PROMPTS]
    t0 = time.time()
    async with websockets.connect(args.url, origin="http://localhost:3000", max_size=32 * 1024 * 1024) as ws:
        session = await recv(ws, "session")
        print(f"session {session['session_id'][:8]} resumed={session['resumed']}")

        greeting = await recv(ws, "assistant")
        check_reply(greeting, 0)
        replies = [greeting["text"]]

        for n, wav in enumerate(turns, 1):
            pcm = to_pcm16k(wav)
            print(f"-> user turn {n}: {len(pcm) / 2 / TARGET_RATE:.1f}s of speech")
            await speak(ws, pcm, realtime=not args.fast)
            user = await recv(ws, "message")
            assert user["role"] == "user" and user["text"], "no transcript"
            reply = await recv(ws, "assistant")
            check_reply(reply, n)
            replies.append(reply["text"])

        print("-> screenshot")
        await ws.send(json.dumps({"type": "image", "mime": "image/png", "data": TINY_PNG, "note": "This error popped up"}))
        assert (await recv(ws, "message"))["kind"] == "image"
        check_reply(await recv(ws, "assistant"), len(turns) + 1)

        await ws.send(json.dumps({"type": "ping", "t": int(time.time() * 1000)}))
        await recv(ws, "pong")
        await ws.send(json.dumps({"type": "end"}))
        await recv(ws, "ended")

    assert len(set(replies)) > 1, "assistant repeated itself - history not kept?"
    print(f"\nPASS: {len(turns)} voice turns + screenshot in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
