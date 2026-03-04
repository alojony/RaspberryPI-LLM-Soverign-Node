from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class AskRequest(BaseModel):
    prompt: str
    use_rag: bool = True
    use_web: bool = False
    conversation_id: Optional[int] = None


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
    model_config = {"from_attributes": True}


class TimerRequest(BaseModel):
    label: str
    duration_seconds: int = Field(gt=0)


class Timer(BaseModel):
    id: int
    label: str
    duration_seconds: int
    fire_at: datetime
    fired: bool
    created_at: datetime
    seconds_remaining: Optional[float] = None
    model_config = {"from_attributes": True}


class TimeResponse(BaseModel):
    utc: str
    local: str
    local_tz: str
    valencia: str
    montreal: str


class IngestRequest(BaseModel):
    path: Optional[str] = None  # defaults to VAULT_PATH env var


class IngestResponse(BaseModel):
    status: str
    path: str
    files_found: int
    files_skipped: int
    files_processed: int
    chunks_upserted: int
    errors: list[str] = []
    elapsed_ms: float


class ConversationSummary(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    sources: list[str] = []
    latency_ms: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetail(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut]

    model_config = {"from_attributes": True}
