# bd-coldcall-agent

> An AI agent that automates pre-call research and drafts a first-pass proposal for B2B Business Development — built on LangGraph with a dual-model cost-optimized pipeline

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-1C3C3C)
![Models](https://img.shields.io/badge/Models-Exaone_7.8B_|_Sonnet_4.6-FF6B6B)
![Status](https://img.shields.io/badge/status-WIP-yellow)

## Overview

Before a B2B cold call, reps typically spend 15–30 minutes researching each target company. This agent automates that research and drafts a first-pass proposal so the rep can walk into the call with:

- A structured summary of the target company's recent business signals and pain points
- Matching talking points drawn from their own company's tech/product docs (via RAG)
- A lightweight Markdown proposal ready for personalization

## Architecture

```
[Input: target company + industry + language]
        │
        ▼
[1]   Brave Search API ─────────── industry / company news (en · ko, bilingual blend)
        │  articles (snippet only)
        ▼
[1.5] Fetch bodies  ────────────── trafilatura + ThreadPool (per-url timeout, snippet fallback)
        │  articles (full body filled)
        ▼
[2]   Local Exaone 7.8B (4-bit) ── deterministic preprocessing:
        │                              translate → 9-tag classify → bge-m3 dedup
        │  articles (translated_body, tags, dedup_group_id)
        ▼
[3]   RAG retrieval  ───────────── our own tech-docs vectorstore (ChromaDB + bge-m3)
        │  relevant tech chunks
        ▼
[4]   Claude Sonnet 4.6 ────────── synthesize proposal points (reads full translated bodies)
        │
        ▼
[5]   Claude Sonnet 4.6 ────────── draft Markdown proposal
        │
        ▼
[Output] outputs/{company}_{YYYYMMDD}.md
```

Orchestrated as a LangGraph state machine; intermediate artifacts are persisted per run for debugging and review.

## Dual-Model Cost Strategy

The local **Exaone 7.8B (4-bit, 6–12 GB VRAM)** handles only deterministic preprocessing — translation, 9-tag classification, and bge-m3 cosine dedup — where a small model is stable. All BD reasoning (signal extraction, proposal points, draft) goes to **Claude Sonnet 4.6** via the Anthropic SDK, which reads the **full translated bodies** directly so no context is lost to an intermediate summary. Running many targets against the same company tech-docs context amortizes cheaply via Sonnet **prompt caching** (`cache_control: ephemeral`), and a tag-tier policy sends high-value articles at full length while low-value tags drop to snippet.

## Tech Stack

| Layer | Tool |
|-------|------|
| Orchestration | LangGraph |
| Local LLM | Exaone 7.8B (Transformers + bitsandbytes 4-bit) |
| Cloud LLM | Claude Sonnet 4.6 (Anthropic SDK, prompt caching) |
| Embeddings | `BAAI/bge-m3` (ko / en) |
| Vector store | ChromaDB (persistent) |
| Search | Brave Search API |
| Doc connectors | Local PDF / MD / TXT, Notion API |
| Web backend | FastAPI + SSE (uvicorn, SqliteSaver checkpointer) |
| Web frontend | Next.js 15 + Tailwind CSS + TypeScript |
| Language | Python 3.11+ |

## Requirements

- Python 3.11+
- GPU with 6–12 GB VRAM for 4-bit Exaone loading (fp16 mode needs ~16 GB)
- API keys: **Anthropic**, **Brave Search**, and optionally **Notion** (only if indexing Notion pages)

## Getting Started

```bash
# 1. Clone
git clone https://github.com/<username>/bd-coldcall-agent.git
cd bd-coldcall-agent

# 2. Install — Phase 1 essentials (always installable, no CUDA required)
pip install -r requirements.txt

# 3. Install — Phase 2+ ML stack (pick a torch index URL FIRST)
pip install torch --index-url https://download.pytorch.org/whl/cu121   # or .../whl/cpu
pip install -r requirements-ml.txt

# 4. Configure API keys
cp .env.example .env
# Edit .env and fill in your keys

# 5. Drop company tech docs into data/company_docs/ (PDF / MD / TXT)
#    then index them
python main.py ingest

# 6. Run against a target — either CLI or the Web UI
python main.py run --company "NVIDIA" --industry "semiconductor" --lang en

# or start the API + Next.js frontend:
python -m uvicorn src.api.app:app --reload    # http://localhost:8000
cd web && npm install && npm run dev          # http://localhost:3000
```

The proposal lands in `outputs/{company}_{YYYYMMDD}.md`. Language is controlled by `--lang en|ko` (default `en`).

## License

MIT
