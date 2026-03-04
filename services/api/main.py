import os
import time
import uuid
import hashlib
import logging
import json
import asyncio
import pytz
import httpx
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from database import init_db, get_db, ReminderDB, DocumentDB, TimerDB, ConversationDB, MessageDB, SessionLocal
from models import AskRequest, AskResponse, RemindRequest, Reminder, TimerRequest, Timer, TimeResponse, IngestRequest, IngestResponse, ConversationSummary, MessageOut, ConversationDetail
from scheduler import scheduler, schedule_reminder, schedule_timer, cancel_timer
from chunker import chunk_text
import trafilatura
from duckduckgo_search import DDGS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LLM_URL = f"http://{os.getenv('LLM_HOST', 'llm')}:{os.getenv('LLM_PORT', '8080')}"
EMBED_URL = f"http://{os.getenv('EMBED_HOST', 'embeddings')}:{os.getenv('EMBED_PORT', '8001')}"
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION = os.getenv("QDRANT_COLLECTION", "pi_node")
VAULT_PATH = os.getenv("VAULT_PATH", "/data/vault")
LOCAL_TZ = os.getenv("TZ", "UTC")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1600"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "400"))
EMBED_DIM = int(os.getenv("EMBED_DIM", "384"))

TOKEN_BUDGET = 3400

SYSTEM_PROMPT_RAG = (
    "You are a sharp, capable assistant running on a Raspberry Pi 5 — fast, precise, and privacy-first. "
    "Your owner has given you access to their personal knowledge vault.\n\n"
    "Answer directly and confidently. No filler, no 'Great question!', no hedging when you know the answer. "
    "If the context contains relevant information, use it and cite the source file path. "
    "If the context is not helpful, say so briefly and answer from general knowledge. "
    "Keep answers concise unless detail is clearly needed. "
    "You can be a little witty when it fits — but stay sharp and useful above all."
)

SYSTEM_PROMPT_WEB = (
    "You are a sharp, capable assistant running on a Raspberry Pi 5 — fast, precise, and privacy-first. "
    "You have access to your owner's knowledge vault and live web results.\n\n"
    "Answer directly and confidently. No filler, no hedging when you know the answer. "
    "Use vault context and web results as evidence — cite file paths for vault sources and URLs for web sources. "
    "Note when web content was retrieved. If sources conflict, flag it briefly. "
    "Keep answers concise unless detail is clearly needed. "
    "You can be a little witty when it fits — but stay sharp and useful above all."
)

SYSTEM_PROMPT_PLAIN = (
    "You are a sharp, capable assistant running on a Raspberry Pi 5 — fast, precise, and privacy-first.\n\n"
    "Answer directly and confidently. No filler, no 'Great question!', no unnecessary hedging. "
    "Keep answers concise unless detail is clearly needed. "
    "You can be a little witty when it fits — but stay sharp and useful above all."
)

qdrant: QdrantClient = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global qdrant
    init_db()
    qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    existing = [c.name for c in qdrant.get_collections().collections]
    if COLLECTION not in existing:
        qdrant.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )
        logger.info(f"Created Qdrant collection: {COLLECTION}")
    else:
        logger.info(f"Qdrant collection exists: {COLLECTION}")
    scheduler.start()
    logger.info("Scheduler started")
    _db = SessionLocal()
    try:
        pending = _db.query(ReminderDB).filter(
            ReminderDB.completed == False,
            ReminderDB.trigger_at > datetime.now(),
        ).all()
        for r in pending:
            schedule_reminder(r.id, r.text, r.trigger_at, r.recurring)
        logger.info(f"Re-scheduled {len(pending)} reminder(s) on startup")
    finally:
        _db.close()
    yield
    scheduler.shutdown()


app = FastAPI(title="Pi Sovereign Node", version="0.1.0", lifespan=lifespan)
app.mount("/ui", StaticFiles(directory="ui", html=True), name="ui")


# ── Health ───────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


# ── Ask helpers ──────────────────────────────────────────────

CONVERSATIONAL = {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "bye", "yes", "no", "sup", "yo"}

def _is_simple(prompt: str) -> bool:
    return len(prompt.strip()) < 20 or prompt.strip().lower() in CONVERSATIONAL

def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)

async def _build_context(req: AskRequest) -> tuple[list[str], list[str], list[str]]:
    rag_chunks: list[str] = []
    web_snippets: list[str] = []
    sources: list[str] = []

    if req.use_rag and not _is_simple(req.prompt):
        async with httpx.AsyncClient(timeout=30) as client:
            embed_resp = await client.post(f"{EMBED_URL}/embed", json={"text": req.prompt})
            embed_resp.raise_for_status()
            query_vector = embed_resp.json()["embedding"]
        results = qdrant.search(collection_name=COLLECTION, query_vector=query_vector, limit=5)
        for hit in results:
            chunk_text = hit.payload.get("text", "")
            if chunk_text:
                rag_chunks.append(chunk_text)
            src = hit.payload.get("file_path", "")
            if src:
                sources.append(src)

    if req.use_web and not _is_simple(req.prompt):
        try:
            with DDGS() as ddgs:
                web_results = list(ddgs.text(req.prompt, max_results=3))
            for r in web_results:
                url = r.get("href", "")
                downloaded = await asyncio.to_thread(trafilatura.fetch_url, url, timeout=10)
                text = trafilatura.extract(downloaded, max_chars=1500) if downloaded else r.get("body", "")
                if text:
                    web_snippets.append(f"[WEB: {url}]\n{text}")
                    sources.append(url)
        except Exception as e:
            logger.warning(f"Web search failed: {e}")

    return rag_chunks, web_snippets, list(dict.fromkeys(sources))

def _truncate_to_budget(rag_chunks: list[str], web_snippets: list[str], system_prompt: str, question: str) -> str:
    fixed_tokens = _estimate_tokens(system_prompt) + _estimate_tokens(question)
    remaining = TOKEN_BUDGET - fixed_tokens

    selected_rag: list[str] = []
    for chunk in rag_chunks:
        cost = _estimate_tokens(chunk)
        if cost > remaining:
            break
        selected_rag.append(chunk)
        remaining -= cost

    selected_web: list[str] = []
    for snippet in web_snippets:
        cost = _estimate_tokens(snippet)
        if cost > remaining:
            break
        selected_web.append(snippet)
        remaining -= cost

    total_used = TOKEN_BUDGET - fixed_tokens - remaining
    logger.info(f"[TOKENS] estimated: {fixed_tokens + total_used}, rag_chunks: {len(selected_rag)}, web_snippets: {len(selected_web)}")

    parts = selected_rag + selected_web
    return "\n---\n".join(parts) if parts else ""

def _build_prompt(req: AskRequest, rag_chunks: list[str], web_snippets: list[str]) -> tuple[str, str]:
    if req.use_web:
        system = SYSTEM_PROMPT_WEB
    elif rag_chunks or web_snippets:
        system = SYSTEM_PROMPT_RAG
    else:
        system = SYSTEM_PROMPT_PLAIN

    context = _truncate_to_budget(rag_chunks, web_snippets, system, req.prompt)
    full_prompt = f"[CONTEXT]\n{context}\n\n[QUESTION]\n{req.prompt}" if context else req.prompt
    return system, full_prompt

LLM_STOP = ["<|user|>", "<|im_end|>", "<|im_start|>"]


# ── Ask (JSON, for API clients) ───────────────────────────────

@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    t0 = time.monotonic()
    rag_chunks, web_snippets, sources = await _build_context(req)
    system, full_prompt = _build_prompt(req, rag_chunks, web_snippets)

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)) as client:
        llm_resp = await client.post(
            f"{LLM_URL}/completion",
            json={"prompt": f"<|system|>{system}<|user|>{full_prompt}<|assistant|>", "n_predict": 512, "stop": LLM_STOP},
        )
        llm_resp.raise_for_status()
        answer = llm_resp.json()["content"].strip()

    latency = (time.monotonic() - t0) * 1000
    return AskResponse(answer=answer, sources=sources, latency_ms=round(latency, 1))


# ── Ask/stream (SSE, for UI) ──────────────────────────────────

@app.post("/ask/stream")
async def ask_stream(req: AskRequest):
    t0 = time.monotonic()
    rag_chunks, web_snippets, sources = await _build_context(req)
    system, full_prompt = _build_prompt(req, rag_chunks, web_snippets)

    # ── Setup: create/get conversation and save user message ──
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        if req.conversation_id:
            conv = db.get(ConversationDB, req.conversation_id)
            if not conv:
                conv = ConversationDB(title=req.prompt[:60].strip(), created_at=now, updated_at=now)
                db.add(conv)
                db.commit()
                db.refresh(conv)
        else:
            conv = ConversationDB(title=req.prompt[:60].strip(), created_at=now, updated_at=now)
            db.add(conv)
            db.commit()
            db.refresh(conv)

        conv_id = conv.id
        db.add(MessageDB(
            conversation_id=conv_id,
            role="user",
            content=req.prompt,
            sources=None,
            latency_ms=None,
            created_at=now,
        ))
        db.commit()
    finally:
        db.close()

    async def generate():
        tokens = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)) as client:
            async with client.stream(
                "POST", f"{LLM_URL}/completion",
                json={"prompt": f"<|system|>{system}<|user|>{full_prompt}<|assistant|>", "n_predict": 512, "stream": True, "stop": LLM_STOP},
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        token = data.get("content", "")
                        tokens.append(token)
                        yield f"data: {json.dumps({'type': 'token', 'token': token, 'stop': data.get('stop', False)})}\n\n"
                        if data.get("stop"):
                            break

        # ── Save assistant message ──
        full_answer = "".join(tokens).strip()
        latency = round((time.monotonic() - t0) * 1000, 1)
        db2 = SessionLocal()
        try:
            db2.add(MessageDB(
                conversation_id=conv_id,
                role="assistant",
                content=full_answer,
                sources=json.dumps(sources),
                latency_ms=latency,
                created_at=datetime.now(timezone.utc),
            ))
            conv2 = db2.get(ConversationDB, conv_id)
            if conv2:
                conv2.updated_at = datetime.now(timezone.utc)
            db2.commit()
        finally:
            db2.close()

        yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'latency_ms': latency, 'conversation_id': conv_id})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Conversations ─────────────────────────────────────────────

@app.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(db: Session = Depends(get_db)):
    return db.query(ConversationDB).order_by(ConversationDB.updated_at.desc()).all()


@app.get("/conversations/{conv_id}", response_model=ConversationDetail)
async def get_conversation(conv_id: int, db: Session = Depends(get_db)):
    conv = db.get(ConversationDB, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = db.query(MessageDB).filter(MessageDB.conversation_id == conv_id).order_by(MessageDB.id).all()
    messages = []
    for m in msgs:
        messages.append(MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            sources=json.loads(m.sources) if m.sources else [],
            latency_ms=m.latency_ms,
            created_at=m.created_at,
        ))
    return ConversationDetail(
        id=conv.id, title=conv.title,
        created_at=conv.created_at, updated_at=conv.updated_at,
        messages=messages,
    )


@app.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: int, db: Session = Depends(get_db)):
    conv = db.get(ConversationDB, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.query(MessageDB).filter(MessageDB.conversation_id == conv_id).delete()
    db.delete(conv)
    db.commit()
    return {"ok": True}


@app.patch("/conversations/{conv_id}/title")
async def rename_conversation(conv_id: int, body: dict, db: Session = Depends(get_db)):
    conv = db.get(ConversationDB, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.title = body.get("title", conv.title)[:80]
    db.commit()
    return {"ok": True}


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


# ── Time ─────────────────────────────────────────────────────

@app.get("/time", response_model=TimeResponse)
def get_time():
    now_utc = datetime.now(timezone.utc)
    local_tz = pytz.timezone(LOCAL_TZ)
    valencia_tz = pytz.timezone("Europe/Madrid")
    montreal_tz = pytz.timezone("America/Toronto")
    return TimeResponse(
        utc=now_utc.isoformat(),
        local=now_utc.astimezone(local_tz).isoformat(),
        local_tz=LOCAL_TZ,
        valencia=now_utc.astimezone(valencia_tz).isoformat(),
        montreal=now_utc.astimezone(montreal_tz).isoformat(),
    )


# ── Timers ────────────────────────────────────────────────────

@app.post("/timers", response_model=Timer)
def create_timer(req: TimerRequest, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    fire_at = now + timedelta(seconds=req.duration_seconds)
    record = TimerDB(
        label=req.label,
        duration_seconds=req.duration_seconds,
        fire_at=fire_at.replace(tzinfo=None),
        fired=False,
        created_at=now.replace(tzinfo=None),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    schedule_timer(record.id, record.label, fire_at)
    seconds_remaining = max(0.0, (fire_at - datetime.now(timezone.utc)).total_seconds())
    return Timer(
        id=record.id,
        label=record.label,
        duration_seconds=record.duration_seconds,
        fire_at=record.fire_at,
        fired=record.fired,
        created_at=record.created_at,
        seconds_remaining=seconds_remaining,
    )


@app.get("/timers", response_model=list[Timer])
def list_timers(fired: bool = False, db: Session = Depends(get_db)):
    records = db.query(TimerDB).filter(TimerDB.fired == fired).all()
    now = datetime.now(timezone.utc)
    result = []
    for r in records:
        fire_at_utc = r.fire_at.replace(tzinfo=timezone.utc)
        seconds_remaining = max(0.0, (fire_at_utc - now).total_seconds())
        result.append(Timer(
            id=r.id,
            label=r.label,
            duration_seconds=r.duration_seconds,
            fire_at=r.fire_at,
            fired=r.fired,
            created_at=r.created_at,
            seconds_remaining=seconds_remaining,
        ))
    return result


@app.delete("/timers/{timer_id}")
def delete_timer(timer_id: int, db: Session = Depends(get_db)):
    record = db.query(TimerDB).filter(TimerDB.id == timer_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Timer not found")
    cancel_timer(timer_id)
    db.delete(record)
    db.commit()
    return {"ok": True}


# ── Ingestion ────────────────────────────────────────────────

@app.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest, db: Session = Depends(get_db)):
    t0 = time.monotonic()
    path = Path(req.path or VAULT_PATH)
    all_files = [f for f in path.rglob("*.md") if not any(p.startswith(".") for p in f.parts)]
    files_found = len(all_files)
    files_skipped = 0
    files_processed = 0
    chunks_upserted = 0
    errors = []

    for file_path in all_files:
        raw = file_path.read_bytes()
        file_hash = hashlib.sha256(raw).hexdigest()
        rel_path = str(file_path.relative_to(path))
        existing_doc = db.query(DocumentDB).filter(DocumentDB.file_path == rel_path).first()

        if existing_doc and existing_doc.file_hash == file_hash:
            files_skipped += 1
            continue

        text = raw.decode("utf-8", errors="replace")
        chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                embed_resp = await client.post(
                    f"{EMBED_URL}/embed/batch",
                    json={"texts": [c["text"] for c in chunks]},
                )
                embed_resp.raise_for_status()
                embeddings = embed_resp.json()["embeddings"]

            points = []
            for i, (chunk, vec) in enumerate(zip(chunks, embeddings)):
                point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{rel_path}:{chunk['char_start']}"))
                points.append(PointStruct(
                    id=point_id,
                    vector=vec,
                    payload={
                        "text": chunk["text"],
                        "file_path": rel_path,
                        "source_type": "vault",
                        "char_start": chunk["char_start"],
                        "char_end": chunk["char_end"],
                    },
                ))

            qdrant.upsert(collection_name=COLLECTION, points=points)

            now = datetime.now(timezone.utc)
            if existing_doc:
                existing_doc.file_hash = file_hash
                existing_doc.last_indexed = now
                existing_doc.chunk_count = len(chunks)
            else:
                db.add(DocumentDB(
                    file_path=rel_path,
                    file_hash=file_hash,
                    last_indexed=now,
                    chunk_count=len(chunks),
                ))
            db.commit()
            files_processed += 1
            chunks_upserted += len(points)
        except Exception as e:
            logger.error(f"Ingest failed for {rel_path}: {e}")
            errors.append(rel_path)

    return IngestResponse(
        status="ok" if not errors else "partial",
        path=str(path),
        files_found=files_found,
        files_skipped=files_skipped,
        files_processed=files_processed,
        chunks_upserted=chunks_upserted,
        errors=errors,
        elapsed_ms=round((time.monotonic() - t0) * 1000, 1),
    )
