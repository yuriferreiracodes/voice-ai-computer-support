# AI Computer Support

A voice-first web app that helps people fix Windows computer problems. Click **Start Call**, describe the problem out loud, and the assistant asks short questions and walks you through the fix **one step at a time**. It speaks its answers and shows the whole conversation as text. You can also upload or paste a screenshot of an error.

Everything AI runs on **[OpenRouter](https://openrouter.ai)**, so no GPU is needed:

- **Qwen3.8 Omni Flash** (`qwen/qwen3.8-omni-flash`) hears the user's voice, reads screenshots and writes the reply.
- **ElevenLabs Flash v2.5** (`elevenlabs/eleven-flash-v2.5`) speaks the reply in a natural voice.

> **Safety:** The app never runs anything on the user's computer. It has no way to do so. The model only gives instructions, and the system prompt makes it warn the user before risky steps (registry, resets, deleting files).

## Architecture

```
Browser (Next.js)                 backend (FastAPI)                               OpenRouter
──────────────────                ─────────────────                               ──────────
mic → AudioWorklet (16k PCM)      routes/call.py   /ws/call WebSocket
    → VAD (speech start/end) ──►  services/voice_call.py  turns + history  ──►   /chat/completions  Qwen3.8 Omni Flash
screenshots (resized JPEG)  ──►   services/llm.py  transcribe + reply      ──►   /audio/speech      ElevenLabs Flash
◄── reply text + MP3 audio  ◄──   services/tts.py  reply → speech
play audio / browser TTS
```

| Service    | Port | What it does |
|------------|------|--------------|
| `frontend` | 3000 | Next.js 16 + TypeScript + Tailwind 4. Call UI, mic capture, voice activity detection, playback, transcript. |
| `backend`  | 8000 | FastAPI. WebSocket call, session history, support prompt, OpenRouter calls (LLM + TTS), errors and logs. |

The backend follows **routes + services + schemas**:

```
backend/app/
  main.py                 app, lifespan (builds the services), CORS, routers
  core/                   config.py (env settings), logging.py, prompts.py (support persona + safety rules)
  routes/                 call.py (WebSocket: origin check, frame loop, message parsing), health.py
  schemas/                call.py (WebSocket protocol), ai.py (turn/history types), health.py
  services/
    openrouter.py         HTTP client: auth, timeouts, retries, error mapping
    llm.py                transcribe() and reply() with the omni model
    tts.py                synthesize() via /audio/speech (failure -> browser voice)
    voice_call.py         one call: audio buffering, turns, barge-in, greeting (no WebSocket code)
    session.py            in-memory sessions with TTL (resume after reconnect)
  utils/audio.py          PCM16 -> WAV
```

**One voice turn:** the browser detects speech and streams 20 ms PCM frames → on silence it sends `audio_end` → the backend wraps the audio as WAV and makes **two calls in parallel**: one *transcribes* it (shown on screen) and one *answers* from the history plus the original audio, so the model hears the voice and not just the transcript → the reply goes to the TTS → text and MP3 go back → the browser plays them. If you start talking while the AI speaks, playback stops and the reply in progress is cancelled (barge-in).

Measured end to end: about **3.5 s** from the end of speech to the reply audio (≈2.5 s LLM, ≈1 s TTS).

## Quick start

```bash
cp .env.example .env          # then set OPENROUTER_API_KEY (https://openrouter.ai/keys)
docker compose up --build
curl localhost:8000/health/ai # {"status":"ok", ...} = the key works
```

Open **http://localhost:3000** and click **Start Call**.

> The microphone only works on `http://localhost` or HTTPS. To open the app from another machine, put it behind HTTPS (for example Caddy or nginx) and set `CORS_ORIGINS` and `NEXT_PUBLIC_BACKEND_URL`.

## Configuration

All settings are environment variables (see `.env.example`).

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | – | **Required.** Your OpenRouter key |
| `LLM_MODEL` | `qwen/qwen3.8-omni-flash` | Any OpenRouter model with **audio input** (and image input for screenshots) |
| `LLM_REASONING` | `false` | Qwen3.8 Omni reasons by default, which takes ~19 s per turn instead of ~2 s. Keep off for calls |
| `TTS_MODEL` | `elevenlabs/eleven-flash-v2.5` | OpenRouter speech model. Empty = the browser speaks the reply |
| `TTS_VOICE` | `21m00Tcm4TlvDq8ikWAM` | Voice id for the TTS model (ElevenLabs "Rachel", English) |
| `TTS_FORMAT` | `mp3` | Audio format sent to the browser |
| `AI_TIMEOUT_S` | `60` | Per-request timeout to OpenRouter (one retry on timeouts, 429 and 5xx) |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Allowed browser origins (HTTP and WebSocket) |
| `NEXT_PUBLIC_BACKEND_URL` | empty | Fixed backend URL baked at build time. Empty = `<page host>:8000` |
| `GREETING_ENABLED` | `true` | The AI greets the user when the call starts |
| `LOG_LEVEL` | `INFO` | Backend log level |

Backend limits (`backend/app/core/config.py`): utterances 0.35–30 s, screenshots ≤ 6 MB (the browser downsizes them to ≤1600 px JPEG first; the model rejects images with a side of 10 px or less), last 30 messages sent as history, sessions kept 15 min after a disconnect so a dropped connection resumes the same conversation.

## Features

- **Start Call** asks for the microphone, connects, and the AI greets you.
- Hands-free talking: voice activity detection with an adaptive noise floor finds where speech starts and ends. No push-to-talk.
- Spoken replies with a natural ElevenLabs voice, with browser speech synthesis as a fallback if the TTS fails.
- Live transcript of both sides. You can also type (useful for error codes).
- Screenshots: use the upload button or **paste with Ctrl+V** during a call. The model reads the error and explains the next step.
- Controls: **mute**, **stop AI speaking**, **end call**, and a **connection status** pill with latency.
- Auto-reconnect (exponential backoff, 5 tries) that resumes the same session, plus a heartbeat ping.
- Barge-in: talking over the AI stops it.
- Clear errors for mic blocked, no mic, mic busy, insecure origin, AI service down or timed out, bad images and lost connection.
- Logs: every turn is logged with a session id, durations and latencies. Transcripts themselves aren't logged.

## WebSocket protocol (`/ws/call`)

| Direction | Message |
|---|---|
| client → server | binary: PCM16 LE mono 16 kHz frames · `audio_start` · `audio_end` · `text {text}` · `image {mime,data,note?}` · `interrupt` · `ping {t}` · `end` |
| server → client | `session {session_id,resumed,messages}` · `status {state}` · `message {role:user,text,kind}` · `assistant {text,audio,audio_source}` · `notice` · `error {code,message,recoverable}` · `pong` · `ended` |

Reconnect with `/ws/call?session_id=<id>` to resume. The full spec is in `backend/app/schemas/call.py`.

## Testing

```bash
# Unit/integration tests (run inside the containers)
docker compose exec backend pytest -q        # WebSocket flow, history, OpenRouter payloads, TTS fallback, errors (OpenRouter mocked)

# End-to-end voice test over the real WebSocket (real speech audio, 2 voice turns + screenshot)
pip install websockets
python scripts/e2e_voice_test.py                         # against localhost:8000, speech generated by the TTS (uses credits)
python scripts/e2e_voice_test.py --wav my_question.wav   # use your own recording

# Browser end-to-end: headless Chromium with a fake microphone playing a WAV
npm i playwright && npx playwright install chromium
node scripts/browser-e2e.cjs path/to/speech.wav          # silence + speech + silence works best

# Frontend checks
cd frontend && npm run lint && npx tsc --noEmit && npm run build
```

`e2e_voice_test.py` saves the AI's reply audio to `scripts/out/`, so you can listen to it.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Microphone access was blocked" | Allow the mic using the lock icon in the address bar, then click Start Call again. |
| Mic does not work from another computer | Browsers need HTTPS for the mic (except on localhost). |
| "OPENROUTER_API_KEY is not set" / HTTP 401 | Set the key in `.env`, then `docker compose up -d` (no rebuild needed). Check with `curl localhost:8000/health/ai`. |
| "Cannot reach the AI provider" / "took too long" | Check the internet connection and https://status.openrouter.ai. Raise `AI_TIMEOUT_S` if needed. |
| Replies take 15+ seconds | `LLM_REASONING` is on. Set it to `false`. |
| AI answers with a robotic browser voice | The TTS call failed (see backend logs for `TTS failed`). Check `TTS_MODEL` / `TTS_VOICE` and your credits. |
| WebSocket closes immediately (code 4403) | Add the page origin to `CORS_ORIGINS`. |
| AI hears itself / keeps interrupting | Use headphones. Echo cancellation is on, but laptop speakers can leak. |

Logs: `docker compose logs -f backend` (each turn logs LLM and TTS latency).

## Project layout

```
frontend/   Next.js app: src/hooks/useVoiceCall.ts (call logic), public/pcm-worklet.js (mic capture), src/components/*
backend/    FastAPI, routes + services + schemas (see Architecture)
scripts/    e2e_voice_test.py, browser-e2e.cjs
```

## Known limitations / next steps

- Replies are generated as a whole, not streamed. Streaming the LLM text into a streaming TTS would cut the time before the AI starts talking to about 1 s.
- Each voice turn makes two LLM calls (transcribe + answer, in parallel). A single call returning both would halve the token cost.
- Sessions live in memory, so you can only run one backend replica. Move them to Redis to scale out.
- The backend has no user authentication, and every call spends OpenRouter credits. Add auth and rate limits before exposing the app publicly.
