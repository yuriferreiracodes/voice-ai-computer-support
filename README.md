# AI Computer Support

AI Computer Support is a voice app for Windows problems. You talk to the AI, and it tells you how to fix the problem, one step at a time.

## What does it do?

- You click **Start Call** and talk about your problem.
- The AI listens. It asks short questions.
- It gives you **one step at a time**. It speaks the answer, and you can also read it on the screen.
- You can send a screenshot of an error. The AI reads it and helps you.

All the AI runs on **[OpenRouter](https://openrouter.ai)**. You do not need a GPU.

- **Qwen3.8 Omni Flash** (`qwen/qwen3.8-omni-flash`) listens to your voice, reads screenshots and writes the answer.
- **ElevenLabs Flash v2.5** (`elevenlabs/eleven-flash-v2.5`) speaks the answer with a natural voice.

> **Safety:** The app never runs anything on your computer. It cannot do this. The AI only gives instructions. Before a dangerous step (registry, reset, deleting files), the AI warns you first.

## How it works

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
| `frontend` | 3000 | Next.js 16 + TypeScript + Tailwind 4. The call screen, the microphone, voice detection, audio and the conversation text. |
| `backend`  | 8000 | FastAPI. The WebSocket call, the chat history, the support prompt, the OpenRouter calls (AI + voice), errors and logs. |

The backend has three parts: **routes**, **services** and **schemas**.

```
backend/app/
  main.py                 the app, startup, CORS, routes
  core/                   config.py (settings), logging.py, prompts.py (AI rules and safety)
  routes/                 call.py (WebSocket), health.py
  schemas/                call.py (WebSocket messages), ai.py (chat types), health.py
  services/
    openrouter.py         HTTP client: key, timeouts, retries, errors
    llm.py                transcribe() and reply()
    tts.py                synthesize() — if it fails, the browser speaks
    voice_call.py         one call: audio, turns, interruptions, greeting
    session.py            sessions in memory (you can reconnect)
  utils/audio.py          PCM16 -> WAV
```

**One voice turn, step by step:**

1. The browser hears you speak. It sends your audio in small pieces (20 ms).
2. When you stop speaking, it sends `audio_end`.
3. The backend makes **two AI calls at the same time**: one writes your words as text (you see it on the screen), and one writes the answer. The AI hears your real voice, not only the text.
4. The answer goes to the voice model (TTS).
5. The text and the MP3 audio go back to the browser. The browser plays the audio.

If you start to talk when the AI is speaking, the AI stops (this is called *barge-in*).

Speed: about **3.5 seconds** from the end of your words to the AI voice (about 2.5 s for the AI, 1 s for the voice).

## Quick start

```bash
cp .env.example .env          # then add your OPENROUTER_API_KEY (https://openrouter.ai/keys)
docker compose up --build
curl localhost:8000/health/ai # {"status":"ok", ...} = your key works
```

Open **http://localhost:3000** and click **Start Call**.

> The microphone only works on `http://localhost` or on HTTPS. To use the app from another computer, use HTTPS (for example with Caddy or nginx) and set `CORS_ORIGINS` and `NEXT_PUBLIC_BACKEND_URL`.

## Settings

All settings are environment variables. See `.env.example`.

| Variable | Default | What it does |
|---|---|---|
| `OPENROUTER_API_KEY` | – | **Required.** Your OpenRouter key |
| `LLM_MODEL` | `qwen/qwen3.8-omni-flash` | Any OpenRouter model that accepts **audio** (and images for screenshots) |
| `LLM_REASONING` | `false` | With reasoning on, one answer takes about 19 s, not 2 s. Keep it off for calls |
| `TTS_MODEL` | `elevenlabs/eleven-flash-v2.5` | The voice model. Empty = the browser speaks |
| `TTS_VOICE` | `21m00Tcm4TlvDq8ikWAM` | The voice id (ElevenLabs "Rachel", English) |
| `TTS_FORMAT` | `mp3` | The audio format for the browser |
| `AI_TIMEOUT_S` | `60` | Time limit for one OpenRouter request (it tries again once on timeouts, 429 and 5xx) |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Browser addresses that can connect (HTTP and WebSocket) |
| `NEXT_PUBLIC_BACKEND_URL` | empty | A fixed backend URL, set at build time. Empty = `<page host>:8000` |
| `GREETING_ENABLED` | `true` | The AI says hello when the call starts |
| `LOG_LEVEL` | `INFO` | Backend log level |

Limits (in `backend/app/core/config.py`):

- Each thing you say: 0.35 to 30 seconds.
- Screenshots: 6 MB or less. The browser makes them smaller first (1600 px JPEG). Images with a side of 10 px or less do not work.
- The AI gets the last 30 messages as history.
- After you disconnect, your session stays for 15 minutes. If your connection stops, you can continue the same conversation.

## Features

- **Start Call** asks for the microphone, connects, and the AI says hello.
- No buttons to talk. The app finds when you start and stop speaking.
- The AI speaks with a natural ElevenLabs voice. If this fails, the browser voice speaks.
- You see the full conversation as text. You can also type (good for error codes).
- Screenshots: click the upload button or **paste with Ctrl+V** during a call.
- Buttons: **mute**, **stop AI speaking**, **end call**. You also see the **connection status** and the delay.
- If the connection stops, the app connects again (5 tries) and continues the same session.
- You can talk over the AI to stop it.
- Clear error messages: mic blocked, no mic, mic busy, not secure (no HTTPS), AI service down or slow, bad image, connection lost.
- Logs: each turn has a session id and times. The app does **not** save what you say in the logs.

## WebSocket messages (`/ws/call`)

| Direction | Message |
|---|---|
| client → server | binary: PCM16 LE mono 16 kHz frames · `audio_start` · `audio_end` · `text {text}` · `image {mime,data,note?}` · `interrupt` · `ping {t}` · `end` |
| server → client | `session {session_id,resumed,messages}` · `status {state}` · `message {role:user,text,kind}` · `assistant {text,audio,audio_source}` · `notice` · `error {code,message,recoverable}` · `pong` · `ended` |

To continue a session, connect to `/ws/call?session_id=<id>`. All the details are in `backend/app/schemas/call.py`.

## Tests

```bash
# Backend tests (inside the container, OpenRouter is mocked)
docker compose exec backend pytest -q

# Real voice test over the WebSocket (2 voice turns + 1 screenshot, uses credits)
pip install websockets
python scripts/e2e_voice_test.py                         # the TTS makes the test voice
python scripts/e2e_voice_test.py --wav my_question.wav   # use your own recording

# Browser test: Chromium with a fake microphone that plays a WAV file
npm i playwright && npx playwright install chromium
node scripts/browser-e2e.cjs path/to/speech.wav          # silence + speech + silence works best

# Frontend checks
cd frontend && npm run lint && npx tsc --noEmit && npm run build
```

`e2e_voice_test.py` saves the AI voice in `scripts/out/`, so you can listen to it.

## Problems and fixes

| Problem | Fix |
|---|---|
| "Microphone access was blocked" | Click the lock icon in the address bar, allow the mic, and click Start Call again. |
| The mic does not work from another computer | Browsers need HTTPS for the mic (but not on localhost). |
| "OPENROUTER_API_KEY is not set" / HTTP 401 | Add the key in `.env`, then run `docker compose up -d` (no rebuild). Check with `curl localhost:8000/health/ai`. |
| "Cannot reach the AI provider" / "took too long" | Check your internet and https://status.openrouter.ai. You can make `AI_TIMEOUT_S` bigger. |
| Answers take 15 seconds or more | `LLM_REASONING` is on. Change it to `false`. |
| The AI has a robot voice | The TTS failed (look for `TTS failed` in the backend logs). Check `TTS_MODEL`, `TTS_VOICE` and your credits. |
| The WebSocket closes at once (code 4403) | Add the page address to `CORS_ORIGINS`. |
| The AI hears itself / stops all the time | Use headphones. Laptop speakers can send the AI voice back to the mic. |

Logs: `docker compose logs -f backend` (each turn shows the AI and voice times).

## Folders

```
frontend/   Next.js app: src/hooks/useVoiceCall.ts (call logic), public/pcm-worklet.js (mic), src/components/*
backend/    FastAPI: routes + services + schemas (see "How it works")
scripts/    e2e_voice_test.py, browser-e2e.cjs
```

## Limits and next steps

- The app makes the full answer first, and then it speaks. With streaming, the AI can start to speak in about 1 second.
- Each voice turn uses two AI calls (text + answer). One call for both can cost half.
- Sessions are in memory, so you can only run one backend. Use Redis to run more.
- The backend has no login, and each call uses OpenRouter credits. Add login and rate limits before you put the app on the internet.
