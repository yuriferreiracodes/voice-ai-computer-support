import time
import uuid
from dataclasses import dataclass, field

from app.schemas.ai import HistoryItem


@dataclass
class Message:
    id: str
    role: str  # "user" | "assistant"
    text: str
    kind: str = "voice"  # voice | text | image
    ts: float = field(default_factory=time.time)


@dataclass
class Session:
    id: str
    messages: list[Message] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    greeted: bool = False

    def add(self, role: str, text: str, kind: str = "voice") -> Message:
        m = Message(id=uuid.uuid4().hex[:12], role=role, text=text, kind=kind)
        self.messages.append(m)
        return m

    def history_for_model(self, limit: int) -> list[HistoryItem]:
        """Text-only history. Screenshots are stored as a short marker; the assistant's
        analysis that follows keeps what mattered."""
        return [HistoryItem(role=m.role, text=m.text) for m in self.messages[-limit:]]


class SessionStore:
    """In-memory sessions: survive a WebSocket reconnect, expire after a TTL.
    Swap for Redis if you run more than one backend replica."""

    def __init__(self, ttl_s: int):
        self.ttl_s = ttl_s
        self._sessions: dict[str, Session] = {}

    def get_or_create(self, session_id: str | None) -> tuple[Session, bool]:
        self.gc()
        if session_id and session_id in self._sessions:
            s = self._sessions[session_id]
            s.last_seen = time.time()
            return s, True
        s = Session(id=uuid.uuid4().hex)
        self._sessions[s.id] = s
        return s, False

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def gc(self) -> None:
        now = time.time()
        for sid in [k for k, v in self._sessions.items() if now - v.last_seen > self.ttl_s]:
            del self._sessions[sid]

    def __len__(self) -> int:
        return len(self._sessions)
