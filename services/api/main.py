import os
import time
import logging
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from database import init_db, get_db, ReminderDB
from models import AskRequest, AskResponse, RemindRequest, Reminder, IngestRequest
from scheduler import scheduler, schedule_reminder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LLM_URL = f"http://{os.getenv('LLM_HOST', 'llm')}:{os.getenv('LLM_PORT', '8080')}"
EMBED_URL = f"http://{os.getenv('EMBED_HOST', 'embeddings')}:{os.getenv('EMBED_PORT', '8001')}"
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION = os.getenv("QDRANT_COLLECTION", "pi_node")
VAULT_PATH = os.getenv("VAULT_PATH", "/data/vault")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.start()
    logger.info("Scheduler started")
    yield
    scheduler.shutdown()


app = FastAPI(title="Pi Sovereign Node", version="0.1.0", lifespan=lifespan)


# ── Health ───────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


# ── Ask (RAG + LLM) ─────────────────────────────────────────

@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    t0 = time.monotonic()
    sources: list[str] = []
    context = ""

    if req.use_rag:
        # 1. Embed the query
        async with httpx.AsyncClient(timeout=30) as client:
            embed_resp = await client.post(f"{EMBED_URL}/embed", json={"text": req.prompt})
            embed_resp.raise_for_status()
            query_vector = embed_resp.json()["embedding"]

        # 2. Retrieve from Qdrant
        from qdrant_client import QdrantClient
        qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        results = qdrant.search(
            collection_name=COLLECTION,
            query_vector=query_vector,
            limit=5,
        )
        for hit in results:
            context += f"\n---\n{hit.payload.get('text', '')}"
            src = hit.payload.get("file_path", "")
            if src:
                sources.append(src)

    # 3. Build prompt and call LLM
    system = "You are a concise local assistant. Answer using the provided context. Cite sources."
    full_prompt = f"[CONTEXT]\n{context}\n\n[QUESTION]\n{req.prompt}" if context else req.prompt

    async with httpx.AsyncClient(timeout=120) as client:
        llm_resp = await client.post(
            f"{LLM_URL}/completion",
            json={"prompt": f"<|system|>{system}<|user|>{full_prompt}<|assistant|>", "n_predict": 512},
        )
        llm_resp.raise_for_status()
        answer = llm_resp.json()["content"].strip()

    latency = (time.monotonic() - t0) * 1000
    return AskResponse(answer=answer, sources=list(dict.fromkeys(sources)), latency_ms=round(latency, 1))


# ── Reminders ────────────────────────────────────────────────

@app.post("/remind", response_model=Reminder)
async def create_reminder(req: RemindRequest, db: Session = Depends(get_db)):
    record = ReminderDB(text=req.text, trigger_at=req.trigger_at, recurring=req.recurring)
    db.add(record)
    db.commit()
    db.refresh(record)
    schedule_reminder(record.id, record.text, record.trigger_at, record.recurring)
    return record


@app.get("/reminders", response_model=list[Reminder])
async def list_reminders(done: bool = False, db: Session = Depends(get_db)):
    return db.query(ReminderDB).filter(ReminderDB.completed == done).all()


@app.patch("/reminders/{reminder_id}/done")
async def mark_done(reminder_id: int, db: Session = Depends(get_db)):
    record = db.get(ReminderDB, reminder_id)
    if not record:
        raise HTTPException(status_code=404, detail="Reminder not found")
    record.completed = True
    db.commit()
    return {"ok": True}


# ── Ingestion ────────────────────────────────────────────────

@app.post("/ingest")
async def ingest(req: IngestRequest):
    # TODO: walk vault path, chunk markdown, embed, upsert to Qdrant
    path = req.path or VAULT_PATH
    return {"status": "queued", "path": path}
