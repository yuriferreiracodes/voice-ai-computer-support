import type { Connection } from "@/hooks/useVoiceCall";

const styles: Record<Connection, { dot: string; label: string }> = {
  connected: { dot: "bg-emerald-500", label: "Connected" },
  connecting: { dot: "bg-amber-400 animate-pulse", label: "Connecting…" },
  reconnecting: { dot: "bg-amber-400 animate-pulse", label: "Reconnecting…" },
  disconnected: { dot: "bg-slate-400", label: "Offline" },
};

export function StatusPill({ connection, latencyMs }: { connection: Connection; latencyMs: number | null }) {
  const s = styles[connection];
  return (
    <div
      role="status"
      aria-live="polite"
      className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/70 px-3 py-1 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300"
    >
      <span className={`h-2 w-2 rounded-full ${s.dot}`} />
      {s.label}
      {connection === "connected" && latencyMs !== null && <span className="text-slate-400">· {latencyMs} ms</span>}
    </div>
  );
}
