# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

MuniGPT is a fully-offline RAG assistant for Chilean municipal employees, built by Instituto Igualdad in the context of Ley 21.663 (Marco de Ciberseguridad). The core design constraint drives every decision: **no institutional data leaves the machine**. Everything (LLM inference, embeddings, vector search) runs locally via Ollama + LanceDB. The one exception is the optional `/search` web-search endpoint, where only the query string is sent out (to the Brave API).

All user-facing text and LLM output is in Spanish. The system prompt forbids the model from inventing legal articles or references and requires it to answer only from retrieved context.

## Commands

All backend commands run from inside `backend/` (paths in the code are relative to it — e.g. `rag.py` opens `db/`, `main.py` reads `../config.json`).

```powershell
# One-time setup
python -m venv venv && venv\Scripts\activate
pip install -r backend/requirements.txt      # see note below — file not yet committed
ollama pull qwen2.5:3b                         # chat model
ollama pull nomic-embed-text                   # embedding model

# Download legal corpus from BCN (needs internet, run once)
cd backend
python corpus_fetcher.py                       # all tiers 0,1,2
python corpus_fetcher.py --tiers 0 1           # subset
python corpus_fetcher.py --municipio "Municipalidad de Chillán"   # + local ordenanzas

# Build the vector DB
python ingest.py --reset                       # wipe and rebuild db/
python ingest.py                               # append to existing db/
python ingest.py --corpus-dir C:/path/to/corpus --db-dir C:/path/to/db

# Run the API
uvicorn main:app --port 8000 --reload
```

There is no test suite, linter config, or `requirements.txt` committed yet. Ollama must be running (`http://localhost:11434`) for both ingest and serving — every script fails fast with a clear message if it can't reach it.

## Architecture

The request flow is: **corpus_fetcher.py** downloads PDFs → **ingest.py** chunks + embeds them into LanceDB → **main.py** serves chat, calling **rag.py** to retrieve context per query → Ollama generates the answer.

**`main.py`** — FastAPI app, four endpoints:
- `POST /chat` — the core endpoint. Calls `rag.retrieve()`, injects retrieved legal text into an augmented user message, then streams Ollama's response back as SSE. The stream sends a `citations` event first (so the frontend can render sources immediately), then `token` events, then a `done` event.
- `POST /search` — Brave web search, gated on `braveApiKey` in config.json (503 if absent).
- `GET /status` — health check; the desktop shell polls this to know the backend is ready.
- `GET /config` — serves `config.json` (per-municipality branding + flags) to the frontend.

**`rag.py`** — hybrid retrieval, the heart of the system. `retrieve()` embeds the query via Ollama, runs **both** vector search and BM-25 full-text search against the same LanceDB table, then merges (vector results first, deduped by `(source, chunk_index)`, capped at `TOP_K=5`). FTS degrades gracefully to empty if the tantivy index is missing. LanceDB is synchronous, so the two searches run sequentially. Not a standalone script — imported by main.py.

**`ingest.py`** — builds the DB. Recursively scans `corpus/` for PDFs/TXTs (tier subdirectories are cosmetic — ingest flattens them). Chunks to ~500 chars with 50-char overlap, splitting on sentence boundaries. Embeds each chunk one-at-a-time through Ollama (embeddings are the slow step). Schema: `text, embedding, source, chunk_index, char_offset`. `source` is just the filename and is what appears in citations. Finally builds the FTS index that `rag.fts_search` depends on.

**`corpus_fetcher.py`** — downloads Chilean law PDFs from BCN's (leychile.cl) public export endpoint by `idNorma`. The corpus is defined as hardcoded tier lists (`TIER_0_GENERAL`, `TIER_1_CORE`, `TIER_2_EXTENDED`) — each entry is `{idNorma, filename, desc}`. To add a law, add an entry with its BCN norma id. BCN returns HTML error pages with HTTP 200 for bad ids, so the downloader sniffs content-type + size to detect failures. Municipality ordenanzas are discovered dynamically via BCN's CSV search endpoint.

**`convert.py`** — a throwaway utility that converts every corpus PDF to TXT via PyMuPDF (`fitz`) **and deletes the original PDF**. Destructive; not part of the main pipeline. `ingest.py` already reads PDFs directly, so this is only for cases where pypdf extraction is poor and PyMuPDF does better.

## Important notes

- **Corpus and `db/` are gitignored** (too large — shipped via installer, not git). `config.json` and `.env` are also gitignored, so secrets like `braveApiKey` live only on the machine.
- **README describes the intended full product, not the current tree.** `frontend/` (React+Vite), `electron/`, `munigpt.py` launcher, and `requirements.txt` are described in README.md and `scaffold.ini` but are **not yet in the repo** — only the Python backend exists so far. `scaffold.ini` is the planned final layout.
- **Model choices are pinned in code, not config**: `qwen2.5:3b` (chat) and `nomic-embed-text` (embeddings) are hardcoded constants in main.py, rag.py, and ingest.py. Changing the model means editing those constants in all relevant files. Chosen to run CPU-only, no GPU.
- **Roadmap (from README):** Ollama is intended to be replaced by an embedded llama.cpp for a self-contained installer with no external dependencies.
