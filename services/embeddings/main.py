import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)
MODEL_NAME = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")

model: SentenceTransformer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global model
    logger.info(f"Loading embedding model: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)
    logger.info("Model loaded")
    yield


app = FastAPI(title="Embedding Service", lifespan=lifespan)


class EmbedRequest(BaseModel):
    text: str


class EmbedBatchRequest(BaseModel):
    texts: list[str]


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_NAME}


@app.post("/embed")
async def embed(req: EmbedRequest):
    vec = model.encode(req.text, normalize_embeddings=True).tolist()
    return {"embedding": vec, "dim": len(vec)}


@app.post("/embed/batch")
async def embed_batch(req: EmbedBatchRequest):
    vecs = model.encode(req.texts, normalize_embeddings=True).tolist()
    return {"embeddings": vecs, "dim": len(vecs[0]) if vecs else 0}
