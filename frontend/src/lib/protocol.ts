// Mirrors backend/app/schemas/call.py

export type Role = "user" | "assistant";
export type MessageKind = "voice" | "text" | "image";

export interface ChatMessage {
  id: string;
  role: Role;
  text: string;
  kind?: MessageKind;
  imageUrl?: string; // local preview for screenshots
}

export type ServerState = "listening" | "transcribing" | "thinking";

export type ServerMessage =
  | { type: "session"; session_id: string; resumed: boolean; messages: ChatMessage[] }
  | { type: "status"; state: ServerState }
  | { type: "message"; id: string; role: Role; text: string; kind: MessageKind }
  | { type: "assistant"; id: string; text: string; audio: string | null; audio_source: string }
  | { type: "notice"; code: string; message: string }
  | { type: "error"; code: string; message: string; recoverable: boolean }
  | { type: "pong"; t?: number }
  | { type: "ended" };

export type ClientMessage =
  | { type: "audio_start" }
  | { type: "audio_end" }
  | { type: "text"; text: string }
  | { type: "image"; mime: string; data: string; note?: string }
  | { type: "interrupt" }
  | { type: "ping"; t: number }
  | { type: "end" };

export function backendWsUrl(): string {
  const configured = process.env.NEXT_PUBLIC_BACKEND_URL;
  if (configured) return configured.replace(/^http/, "ws").replace(/\/$/, "") + "/ws/call";
  // Default: same host as the page, backend on port 8000.
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.hostname}:8000/ws/call`;
}
