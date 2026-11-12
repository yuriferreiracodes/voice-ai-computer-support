"use client";

import { useEffect, useRef } from "react";
import type { AiState } from "@/hooks/useVoiceCall";
import type { ChatMessage } from "@/lib/protocol";

export function Transcript({ messages, aiState }: { messages: ChatMessage[]; aiState: AiState }) {
  const endRef = useRef<HTMLLIElement>(null);
  const busy = aiState === "thinking" || aiState === "transcribing";

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy]);

  if (messages.length === 0 && !busy) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-sm text-slate-400">
        The conversation will appear here.
      </div>
    );
  }

  return (
    <ol className="flex flex-col gap-3 p-4" aria-label="Conversation">
      {messages.map((m) => (
        <li key={m.id} data-role={m.role} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
          <div
            className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
              m.role === "user"
                ? "rounded-br-md bg-indigo-600 text-white"
                : "rounded-bl-md bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100"
            }`}
          >
            <span className="mb-0.5 block text-[11px] font-semibold uppercase tracking-wide opacity-60">
              {m.role === "user" ? (m.kind === "text" ? "You (typed)" : m.kind === "image" ? "You (screenshot)" : "You") : "Support AI"}
            </span>
            {m.imageUrl && (
              // eslint-disable-next-line @next/next/no-img-element -- local blob preview
              <img src={m.imageUrl} alt="Uploaded screenshot" className="mb-2 max-h-48 rounded-lg border border-white/20" />
            )}
            {m.text}
          </div>
        </li>
      ))}
      {busy && (
        <li className="flex justify-start">
          <div className="flex gap-1 rounded-2xl rounded-bl-md bg-slate-100 px-4 py-3 dark:bg-slate-800" aria-label="AI is thinking">
            {[0, 150, 300].map((d) => (
              <span key={d} className="h-2 w-2 animate-bounce rounded-full bg-slate-400" style={{ animationDelay: `${d}ms` }} />
            ))}
          </div>
        </li>
      )}
      <li ref={endRef} aria-hidden />
    </ol>
  );
}
