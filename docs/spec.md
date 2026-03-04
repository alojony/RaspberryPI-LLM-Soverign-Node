# Pi Sovereign Node — Spec Reference

Full specs live in the Obsidian vault:

- Vision: `03_Projects/10_LocalLLM/00 Local LLM v1.md`
- Runtime constraints: `03_Projects/10_LocalLLM/0.5 Target Runtime Specs.md`
- Dev strategy & milestones: `03_Projects/10_LocalLLM/01 Dev Stage.md`
- TODO: `03_Projects/10_LocalLLM/todo.md`

## Quick Constraints Summary

| Resource | Limit |
|----------|-------|
| CPU | 4 cores (Pi 5) |
| RAM steady-state | < 7 GB |
| LLM model class | 3B Q4_K_M |
| Context window | 2k–4k tokens |
| Target response | < 10s (RAG query) |

## Milestone Gates

| Milestone | Done When |
|-----------|-----------|
| A — RAG | "Where did I mention X?" returns citations |
| B — Utility | Set reminder → survives restart → fires on time |
| C — Web tool | "Look up latest X" → summary + URLs |
| Pi deploy | `docker compose up -d` on Pi, all services healthy |

## Model Download

```bash
# Into data/models/ — then set MODEL_PATH in .env
wget https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf \
  -O data/models/qwen2.5-3b-instruct-q4_k_m.gguf
```
