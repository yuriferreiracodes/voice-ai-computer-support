import type { AiState } from "@/hooks/useVoiceCall";

const LABELS: Record<AiState, string> = {
  idle: "Ready",
  listening: "Listening…",
  transcribing: "Hearing you…",
  thinking: "Thinking…",
  speaking: "Speaking…",
};

export function VoiceOrb({
  aiState,
  userSpeaking,
  micLevel,
  muted,
}: {
  aiState: AiState;
  userSpeaking: boolean;
  micLevel: number;
  muted: boolean;
}) {
  const busy = aiState === "thinking" || aiState === "transcribing";
  const speaking = aiState === "speaking";
  const scale = userSpeaking ? 1 + micLevel * 0.35 : 1;
  const label = muted ? "Microphone muted" : userSpeaking ? "You're speaking…" : LABELS[aiState];

  return (
    <div className="flex flex-col items-center gap-5 py-6">
      <div className="relative flex h-40 w-40 items-center justify-center">
        {(speaking || userSpeaking) && (
          <span
            className={`absolute inset-0 rounded-full ${speaking ? "bg-indigo-400/30" : "bg-emerald-400/30"} animate-ping`}
          />
        )}
        <div
          className={`relative h-32 w-32 rounded-full shadow-xl transition-transform duration-100 ${
            muted
              ? "bg-slate-300 dark:bg-slate-700"
              : speaking
                ? "bg-gradient-to-br from-indigo-500 to-violet-600"
                : userSpeaking
                  ? "bg-gradient-to-br from-emerald-400 to-teal-600"
                  : "bg-gradient-to-br from-sky-400 to-indigo-500"
          } ${busy ? "animate-pulse" : ""}`}
          style={{ transform: `scale(${scale})` }}
        />
      </div>
      <p aria-live="polite" className="text-sm font-medium text-slate-600 dark:text-slate-300">
        {label}
      </p>
    </div>
  );
}
