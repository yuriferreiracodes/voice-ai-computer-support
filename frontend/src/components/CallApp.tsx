"use client";

import { useEffect, useRef, useState } from "react";
import { useVoiceCall } from "@/hooks/useVoiceCall";
import { ImageIcon, MicIcon, MicOffIcon, PhoneIcon, PhoneOffIcon, SendIcon, ShieldIcon, StopIcon, XIcon } from "./icons";
import { StatusPill } from "./StatusPill";
import { Transcript } from "./Transcript";
import { VoiceOrb } from "./VoiceOrb";

const TOPICS = ["Wi-Fi & internet", "Sound & microphone", "Drivers & devices", "Apps & installs", "Error messages"];

export function CallApp() {
  const call = useVoiceCall();
  const [draft, setDraft] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const inCall = call.phase === "active";
  const connected = call.connection === "connected";

  // Paste a screenshot with Ctrl+V during a call
  const { sendScreenshot } = call;
  useEffect(() => {
    if (!inCall) return;
    const onPaste = (e: ClipboardEvent) => {
      const file = Array.from(e.clipboardData?.files ?? []).find((f) => f.type.startsWith("image/"));
      if (file) {
        e.preventDefault();
        void sendScreenshot(file);
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [inCall, sendScreenshot]);

  const submitText = (e: React.FormEvent) => {
    e.preventDefault();
    if (call.sendText(draft)) setDraft("");
  };

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col px-4 py-6 sm:px-6">
      <header className="mb-6 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-white shadow">
            <PhoneIcon />
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight">AI Computer Support</h1>
            <p className="text-xs text-slate-500 dark:text-slate-400">Talk through your Windows problem, step by step</p>
          </div>
        </div>
        <StatusPill connection={call.connection} latencyMs={call.latencyMs} />
      </header>

      {call.error && (
        <div role="alert" className="mb-4 flex items-start justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200">
          <span>{call.error}</span>
          <button onClick={call.dismissError} aria-label="Dismiss error" className="shrink-0 opacity-70 hover:opacity-100">
            <XIcon width={16} height={16} />
          </button>
        </div>
      )}
      {call.notice && !call.error && (
        <div role="status" className="mb-4 flex items-start justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          <span>{call.notice}</span>
          <button onClick={call.dismissNotice} aria-label="Dismiss notice" className="shrink-0 opacity-70 hover:opacity-100">
            <XIcon width={16} height={16} />
          </button>
        </div>
      )}

      <main className="grid flex-1 gap-6 lg:grid-cols-[380px_1fr]">
        {/* Left: call controls */}
        <section className="flex flex-col rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          {inCall ? (
            <>
              <VoiceOrb aiState={call.aiState} userSpeaking={call.userSpeaking} micLevel={call.micLevel} muted={call.muted} />
              <div className="mt-auto flex items-center justify-center gap-3">
                <button
                  onClick={call.toggleMute}
                  aria-pressed={call.muted}
                  className={`flex h-12 w-12 items-center justify-center rounded-full border transition ${
                    call.muted
                      ? "border-amber-300 bg-amber-100 text-amber-800 dark:border-amber-700 dark:bg-amber-900/50 dark:text-amber-200"
                      : "border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
                  }`}
                  title={call.muted ? "Unmute" : "Mute"}
                >
                  {call.muted ? <MicOffIcon /> : <MicIcon />}
                  <span className="sr-only">{call.muted ? "Unmute" : "Mute"}</span>
                </button>
                <button
                  onClick={() => fileRef.current?.click()}
                  disabled={!connected}
                  className="flex h-12 w-12 items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-slate-700 transition hover:bg-slate-100 disabled:opacity-40 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
                  title="Upload a screenshot (or paste with Ctrl+V)"
                >
                  <ImageIcon />
                  <span className="sr-only">Upload screenshot</span>
                </button>
                {call.aiState === "speaking" && (
                  <button
                    onClick={call.interrupt}
                    className="flex h-12 w-12 items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-slate-700 transition hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
                    title="Stop the AI talking"
                  >
                    <StopIcon />
                    <span className="sr-only">Stop speaking</span>
                  </button>
                )}
                <button
                  onClick={call.endCall}
                  className="flex h-12 items-center gap-2 rounded-full bg-red-600 px-5 font-medium text-white shadow transition hover:bg-red-700"
                >
                  <PhoneOffIcon />
                  End call
                </button>
              </div>
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void call.sendScreenshot(f);
                  e.target.value = "";
                }}
              />
            </>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-6 text-center">
              <div>
                <h2 className="text-2xl font-semibold tracking-tight">
                  {call.phase === "ended" ? "Call ended" : "Computer trouble? Let's talk."}
                </h2>
                <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                  Describe the problem out loud. The assistant asks a few questions and walks you through the fix one step at a time.
                </p>
              </div>
              <ul className="flex flex-wrap justify-center gap-2">
                {TOPICS.map((t) => (
                  <li key={t} className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                    {t}
                  </li>
                ))}
              </ul>
              <button
                onClick={() => void call.startCall()}
                disabled={call.phase === "starting"}
                className="flex items-center gap-3 rounded-full bg-indigo-600 px-8 py-4 text-lg font-semibold text-white shadow-lg transition hover:bg-indigo-700 focus-visible:ring-4 focus-visible:ring-indigo-300 focus-visible:outline-none disabled:opacity-60"
              >
                <PhoneIcon />
                {call.phase === "starting" ? "Starting…" : call.phase === "ended" ? "Start a new call" : "Start Call"}
              </button>
              <p className="text-xs text-slate-400">Your browser will ask for microphone access.</p>
            </div>
          )}
          <p className="mt-6 flex items-start gap-2 rounded-xl bg-emerald-50 p-3 text-xs text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200">
            <ShieldIcon width={16} height={16} className="mt-0.5 shrink-0" />
            The assistant only gives instructions. It never runs commands or changes anything on your computer: you stay in control.
          </p>
        </section>

        {/* Right: transcript */}
        <section className="flex min-h-[420px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="border-b border-slate-100 px-4 py-3 text-sm font-medium text-slate-600 dark:border-slate-800 dark:text-slate-300">
            Conversation
          </div>
          <div className="flex-1 overflow-y-auto lg:max-h-[calc(100vh-260px)]">
            <Transcript messages={call.messages} aiState={call.aiState} />
          </div>
          {inCall && (
            <form onSubmit={submitText} className="flex gap-2 border-t border-slate-100 p-3 dark:border-slate-800">
              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Or type here (error codes, app names…)"
                aria-label="Type a message"
                className="flex-1 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 dark:border-slate-700 dark:bg-slate-800 dark:focus:ring-indigo-900"
              />
              <button
                type="submit"
                disabled={!connected || !draft.trim()}
                className="flex items-center justify-center rounded-xl bg-indigo-600 px-3 text-white disabled:opacity-40"
              >
                <SendIcon width={18} height={18} />
                <span className="sr-only">Send</span>
              </button>
            </form>
          )}
        </section>
      </main>
    </div>
  );
}
