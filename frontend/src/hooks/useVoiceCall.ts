"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { base64ToArrayBuffer, micErrorMessage, prepareScreenshot } from "@/lib/media";
import { backendWsUrl, type ChatMessage, type ClientMessage, type ServerMessage } from "@/lib/protocol";

export type CallPhase = "idle" | "starting" | "active" | "ended";
export type Connection = "disconnected" | "connecting" | "connected" | "reconnecting";
export type AiState = "idle" | "listening" | "transcribing" | "thinking" | "speaking";

// Voice activity detection tuning (frames are 20 ms)
const VAD = {
  minThreshold: 0.012,
  noiseMultiplier: 3,
  startFrames: 3, // 60 ms above threshold to start
  endSilenceMs: 900, // silence that ends an utterance
  preRollFrames: 15, // 300 ms of audio kept from before speech started
  bargeInMultiplier: 2.5, // louder speech needed to interrupt the AI (avoids echo)
};
const MAX_RECONNECTS = 5;
const PING_MS = 10_000;

export function useVoiceCall() {
  const [phase, setPhase] = useState<CallPhase>("idle");
  const [connection, setConnection] = useState<Connection>("disconnected");
  const [aiState, setAiState] = useState<AiState>("idle");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [muted, setMuted] = useState(false);
  const [userSpeaking, setUserSpeaking] = useState(false);
  const [micLevel, setMicLevel] = useState(0);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const phaseRef = useRef<CallPhase>("idle");
  const reconnectsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastPongRef = useRef(0);

  const ctxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);
  const mutedRef = useRef(false);

  const vadRef = useRef({ speaking: false, above: 0, silenceMs: 0, noise: 0.005, preRoll: [] as ArrayBuffer[] });
  const playbackRef = useRef<AudioBufferSourceNode | null>(null);
  const aiSpeakingRef = useRef(false);
  const pendingImageRef = useRef<string | null>(null);
  const levelFrameRef = useRef(0);
  const connectRef = useRef<() => void>(() => {});

  const setPhaseBoth = (p: CallPhase) => {
    phaseRef.current = p;
    setPhase(p);
  };

  const send = useCallback((msg: ClientMessage | ArrayBuffer) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(msg instanceof ArrayBuffer ? msg : JSON.stringify(msg));
    return true;
  }, []);

  // ---------- playback ----------

  const stopPlayback = useCallback(() => {
    if (playbackRef.current) {
      try {
        playbackRef.current.onended = null;
        playbackRef.current.stop();
      } catch {
        /* already stopped */
      }
      playbackRef.current = null;
    }
    if (typeof window !== "undefined" && window.speechSynthesis) window.speechSynthesis.cancel();
    aiSpeakingRef.current = false;
  }, []);

  const speak = useCallback(
    async (text: string, audioB64: string | null) => {
      stopPlayback();
      const ctx = ctxRef.current;
      const done = () => {
        aiSpeakingRef.current = false;
        if (phaseRef.current === "active") setAiState("listening");
      };
      aiSpeakingRef.current = true;
      setAiState("speaking");

      if (audioB64 && ctx) {
        try {
          const buffer = await ctx.decodeAudioData(base64ToArrayBuffer(audioB64));
          const src = ctx.createBufferSource();
          src.buffer = buffer;
          src.connect(ctx.destination);
          src.onended = done;
          playbackRef.current = src;
          src.start();
          return;
        } catch (e) {
          console.warn("Could not play AI audio, falling back to browser speech", e);
        }
      }
      // Fallback: the browser's own speech synthesis
      if (window.speechSynthesis) {
        const u = new SpeechSynthesisUtterance(text);
        u.rate = 1.02;
        u.onend = done;
        u.onerror = done;
        window.speechSynthesis.speak(u);
      } else {
        done();
      }
    },
    [stopPlayback],
  );

  // ---------- server messages ----------

  const handleServer = useCallback(
    (msg: ServerMessage) => {
      switch (msg.type) {
        case "session":
          sessionIdRef.current = msg.session_id;
          if (!msg.resumed) {
            setMessages(msg.messages);
            if (reconnectsRef.current > 0) setNotice("Reconnected. The previous session expired, so this is a new conversation.");
          } else {
            setNotice(null);
          }
          reconnectsRef.current = 0;
          break;
        case "status":
          if (!aiSpeakingRef.current) setAiState(msg.state);
          break;
        case "message": {
          const imageUrl = msg.kind === "image" ? (pendingImageRef.current ?? undefined) : undefined;
          if (msg.kind === "image") pendingImageRef.current = null;
          setMessages((m) => [...m, { id: msg.id, role: msg.role, text: msg.text, kind: msg.kind, imageUrl }]);
          break;
        }
        case "assistant":
          setMessages((m) => [...m, { id: msg.id, role: "assistant", text: msg.text }]);
          void speak(msg.text, msg.audio);
          break;
        case "notice":
          setNotice(msg.message);
          break;
        case "error":
          setError(msg.message);
          break;
        case "pong":
          lastPongRef.current = Date.now();
          if (msg.t) setLatencyMs(Date.now() - msg.t);
          break;
        case "ended":
          break;
      }
    },
    [speak],
  );

  // ---------- websocket ----------

  const connect = useCallback(() => {
    const sid = sessionIdRef.current;
    const url = backendWsUrl() + (sid ? `?session_id=${encodeURIComponent(sid)}` : "");
    setConnection(reconnectsRef.current > 0 ? "reconnecting" : "connecting");

    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      setConnection("connected");
      setError(null);
      lastPongRef.current = Date.now();
      if (pingTimerRef.current) clearInterval(pingTimerRef.current);
      pingTimerRef.current = setInterval(() => {
        if (Date.now() - lastPongRef.current > PING_MS * 2.5) {
          console.warn("Heartbeat lost, reconnecting");
          ws.close();
          return;
        }
        send({ type: "ping", t: Date.now() });
      }, PING_MS);
      send({ type: "ping", t: Date.now() });
    };

    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") return;
      try {
        handleServer(JSON.parse(ev.data) as ServerMessage);
      } catch (e) {
        console.error("Bad server message", e);
      }
    };

    ws.onclose = (ev) => {
      if (pingTimerRef.current) clearInterval(pingTimerRef.current);
      if (wsRef.current !== ws) return; // an old socket
      wsRef.current = null;
      vadRef.current.speaking = false;
      setUserSpeaking(false);
      if (phaseRef.current !== "active" && phaseRef.current !== "starting") {
        setConnection("disconnected");
        return;
      }
      if (ev.code === 4403) {
        setError("The backend rejected this page's origin. Add it to CORS_ORIGINS in .env.");
        setConnection("disconnected");
        return;
      }
      if (reconnectsRef.current >= MAX_RECONNECTS) {
        setConnection("disconnected");
        setError("Lost connection to the server. Check that the backend is running, then start a new call.");
        return;
      }
      const delay = Math.min(8000, 1000 * 2 ** reconnectsRef.current);
      reconnectsRef.current += 1;
      setConnection("reconnecting");
      reconnectTimerRef.current = setTimeout(() => connectRef.current(), delay);
    };
  }, [handleServer, send]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  // ---------- microphone + VAD ----------

  const onFrame = useCallback(
    (pcm: ArrayBuffer, rms: number) => {
      const v = vadRef.current;
      // meter (throttled to ~12 fps)
      if (++levelFrameRef.current % 4 === 0) setMicLevel(Math.min(1, rms * 12));
      if (mutedRef.current) return;

      const threshold = Math.max(VAD.minThreshold, v.noise * VAD.noiseMultiplier);
      const startThreshold = aiSpeakingRef.current ? threshold * VAD.bargeInMultiplier : threshold;

      if (!v.speaking) {
        if (rms < threshold) v.noise = v.noise * 0.97 + rms * 0.03; // learn the room noise
        v.preRoll.push(pcm);
        if (v.preRoll.length > VAD.preRollFrames) v.preRoll.shift();
        v.above = rms > startThreshold ? v.above + 1 : 0;
        if (v.above >= VAD.startFrames && wsRef.current?.readyState === WebSocket.OPEN) {
          v.speaking = true;
          v.silenceMs = 0;
          if (aiSpeakingRef.current) stopPlayback(); // barge-in
          send({ type: "audio_start" });
          for (const f of v.preRoll) send(f);
          v.preRoll = [];
          setUserSpeaking(true);
          setAiState("listening");
        }
        return;
      }

      send(pcm);
      v.silenceMs = rms < threshold * 0.8 ? v.silenceMs + 20 : 0;
      if (v.silenceMs >= VAD.endSilenceMs) {
        v.speaking = false;
        v.above = 0;
        send({ type: "audio_end" });
        setUserSpeaking(false);
      }
    },
    [send, stopPlayback],
  );

  const teardownAudio = useCallback(() => {
    stopPlayback();
    workletRef.current?.port.close();
    workletRef.current?.disconnect();
    workletRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    void ctxRef.current?.close().catch(() => {});
    ctxRef.current = null;
    setMicLevel(0);
    setUserSpeaking(false);
  }, [stopPlayback]);

  const startCall = useCallback(async () => {
    if (phaseRef.current === "starting" || phaseRef.current === "active") return;
    setError(null);
    setNotice(null);
    setMessages([]);
    setLatencyMs(null);
    sessionIdRef.current = null;
    reconnectsRef.current = 0;
    vadRef.current = { speaking: false, above: 0, silenceMs: 0, noise: 0.005, preRoll: [] };
    setPhaseBoth("starting");

    if (!navigator.mediaDevices?.getUserMedia) {
      setError(micErrorMessage(new Error("this browser does not support microphone access")));
      setPhaseBoth("idle");
      return;
    }
    // Create the AudioContext inside the click handler so autoplay rules allow playback.
    const ctx = new AudioContext();
    ctxRef.current = ctx;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
      streamRef.current = stream;
      await ctx.resume();
      await ctx.audioWorklet.addModule("/pcm-worklet.js");
      const source = ctx.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(ctx, "pcm-capture", { processorOptions: { targetRate: 16000 } });
      node.port.onmessage = (e: MessageEvent<{ pcm: ArrayBuffer; rms: number }>) => onFrame(e.data.pcm, e.data.rms);
      const sink = ctx.createGain();
      sink.gain.value = 0; // keep the graph running without echoing the mic
      source.connect(node).connect(sink).connect(ctx.destination);
      workletRef.current = node;
    } catch (e) {
      console.error("Microphone setup failed", e);
      setError(micErrorMessage(e));
      teardownAudio();
      setPhaseBoth("idle");
      return;
    }

    mutedRef.current = false;
    setMuted(false);
    setPhaseBoth("active");
    setAiState("thinking");
    connect();
  }, [connect, onFrame, teardownAudio]);

  const endCall = useCallback(() => {
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    if (pingTimerRef.current) clearInterval(pingTimerRef.current);
    send({ type: "end" });
    const ws = wsRef.current;
    wsRef.current = null;
    ws?.close(1000, "call ended");
    teardownAudio();
    setPhaseBoth("ended");
    setConnection("disconnected");
    setAiState("idle");
    sessionIdRef.current = null;
  }, [send, teardownAudio]);

  const toggleMute = useCallback(() => {
    const next = !mutedRef.current;
    mutedRef.current = next;
    setMuted(next);
    streamRef.current?.getAudioTracks().forEach((t) => (t.enabled = !next));
    const v = vadRef.current;
    if (next && v.speaking) {
      // finish what the user already said
      v.speaking = false;
      send({ type: "audio_end" });
      setUserSpeaking(false);
    }
  }, [send]);

  const sendText = useCallback(
    (text: string) => {
      const t = text.trim();
      if (!t) return false;
      if (!send({ type: "text", text: t })) {
        setError("Not connected. Wait for the connection to come back.");
        return false;
      }
      stopPlayback();
      return true;
    },
    [send, stopPlayback],
  );

  const sendScreenshot = useCallback(
    async (file: Blob, note?: string) => {
      try {
        const img = await prepareScreenshot(file);
        pendingImageRef.current = img.previewUrl;
        if (!send({ type: "image", mime: img.mime, data: img.data, note })) {
          throw new Error("Not connected. Wait for the connection to come back.");
        }
        stopPlayback();
        setAiState("thinking");
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not send the screenshot.");
      }
    },
    [send, stopPlayback],
  );

  const interrupt = useCallback(() => {
    stopPlayback();
    send({ type: "interrupt" });
    setAiState("listening");
  }, [send, stopPlayback]);

  // clean up on unmount
  useEffect(
    () => () => {
      phaseRef.current = "ended";
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (pingTimerRef.current) clearInterval(pingTimerRef.current);
      wsRef.current?.close();
      teardownAudio();
    },
    [teardownAudio],
  );

  return {
    phase,
    connection,
    aiState,
    messages,
    muted,
    userSpeaking,
    micLevel,
    latencyMs,
    error,
    notice,
    startCall,
    endCall,
    toggleMute,
    sendText,
    sendScreenshot,
    interrupt,
    dismissError: () => setError(null),
    dismissNotice: () => setNotice(null),
  };
}
