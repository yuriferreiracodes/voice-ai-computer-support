from pydantic import BaseModel


class HealthOut(BaseModel):
    status: str
    active_sessions: int


class AIHealthOut(BaseModel):
    status: str  # ok | missing_key | unreachable | error
    llm_model: str
    tts_model: str
    detail: str | None = None
