from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class AskRequest(BaseModel):
    prompt: str
    use_rag: bool = True


class AskResponse(BaseModel):
    answer: str
    sources: list[str] = []
    latency_ms: float


class RemindRequest(BaseModel):
    text: str
    trigger_at: datetime
    recurring: Optional[str] = None  # "daily" | "weekly" | None


class Reminder(BaseModel):
    id: int
    text: str
    trigger_at: datetime
    recurring: Optional[str]
    completed: bool


class IngestRequest(BaseModel):
    path: Optional[str] = None  # defaults to VAULT_PATH env var
