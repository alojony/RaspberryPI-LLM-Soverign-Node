# Pi Sovereign Node

A fully local personal assistant running on a Raspberry Pi 5. No cloud, no subscriptions, no data leaving your network.

## What it does

- **Chat** — conversational AI powered by a local quantized LLM (Qwen2.5-3B/7B via llama.cpp)
- **RAG** — semantic search over your personal knowledge vault (Obsidian markdown)
- **Web search** — live results via Brave Search API, fetched and summarized locally
- **Reminders & timers** — set via natural language in chat ("remind me tomorrow at 9am to…")
- **Google Calendar** — read and create events; shown in a month/week/day UI panel
- **Morning briefing** — daily digest: weather, today's reminders, today's meetings
- **Persistent chat history** — all conversations stored locally in SQLite

## Stack

| Service | Image / Build | Port |
|---------|--------------|------|
| FastAPI (main gateway) | `./services/api` | 8000 |
| llama.cpp server | `ghcr.io/ggml-org/llama.cpp:server` | 8080 |
| Sentence-transformers embeddings | `./services/embeddings` | 8001 |
| Qdrant vector DB | `qdrant/qdrant:latest` | 6333 |
| SQLite | volume at `data/db/` | — |

## Requirements

- Docker with Compose v2 plugin (`docker compose`)
- A GGUF model file in `data/models/` (see `.env.example` for `MODEL_PATH`)
- 8 GB RAM minimum (target: Raspberry Pi 5 8GB)

## Quick start

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env — set MODEL_PATH, TZ, VAULT_HOST_PATH, SEARCH_API_KEY

# 2. Download a model
mkdir -p data/models
wget -P data/models https://huggingface.co/.../qwen2.5-7b-instruct-q4_k_m.gguf

# 3. Boot the stack
docker compose up -d

# 4. Open the UI
open http://localhost:8000/ui
```

## Configuration (`.env`)

| Variable | Description | Default |
|----------|-------------|---------|
| `MODEL_PATH` | Path to GGUF model inside container | `/data/models/qwen2.5-3b-instruct-q4_k_m.gguf` |
| `VAULT_HOST_PATH` | Host path to your Obsidian vault | `./data/vault` |
| `TZ` | Timezone (pytz format) | `America/Los_Angeles` |
| `SEARCH_PROVIDER` | `brave` / `serper` / `ddg` | `ddg` |
| `SEARCH_API_KEY` | API key for Brave or Serper | — |
| `WEATHER_LOCATION` | Location for wttr.in | `Davis,California` |
| `BRIEFING_TIME` | Daily briefing time (24h) | `08:00` |
| `GCAL_CREDENTIALS_PATH` | Google OAuth2 credentials JSON | `/data/db/gcal_credentials.json` |

## Ingesting your vault

```bash
curl -X POST http://localhost:8000/ingest
```

Re-index is incremental — only changed files are re-embedded.

## Google Calendar setup

1. Create a **Desktop app** OAuth2 credential in GCP Console
2. Download `credentials.json` → copy to `data/db/gcal_credentials.json`
3. Visit `http://localhost:8000/calendar/auth` → complete OAuth flow
4. Done — events appear in the right panel

## Key endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ask/stream` | Streaming chat (SSE) |
| `POST` | `/ingest` | Index vault to Qdrant |
| `GET` | `/reminders` | List reminders |
| `GET` | `/calendar` | Google Calendar events |
| `GET` | `/briefing/today` | Today's morning briefing |
| `POST` | `/briefing/regenerate` | Regenerate today's briefing |
| `GET` | `/weather` | Current conditions (cached 30m) |
| `GET` | `/health` | Service health |

## Target hardware

Raspberry Pi 5 · 8 GB RAM · 1 TB NVMe
Model: Qwen2.5-7B Q4_K_M (~4.5 GB RAM)
LAN-only, no external access by default.

## License

Personal use. Not intended for public deployment.
