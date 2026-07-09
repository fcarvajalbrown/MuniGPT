# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

MuniGPT is a fully-offline RAG assistant for Chilean municipal employees, developed by Felipe Carvajal Brown in the context of Ley 21.663 (Marco de Ciberseguridad). The core design constraint drives every decision: **no institutional data leaves the machine**. Everything (LLM inference, embeddings, vector search) runs locally via a bundled **llama.cpp** server + LanceDB. The one network-capable path is the optional `/search` endpoint (Brave, only the query string ever leaves the machine) — but the frontend web-search control is currently **parked** behind a "Pronto disponible!" pill, so the shipping UI makes no outbound calls.

All user-facing text and LLM output is in Spanish. The system prompt forbids the model from inventing legal articles or references and requires it to answer only from retrieved context. It answers directly (no reflexive clarifying questions), and for "cómo/dónde pagar" procedural questions it points to the municipal channel (Tesorería / Dirección de Administración y Finanzas, or the comuna portal) without inventing specific offices, URLs or amounts.

## Commands

All backend commands run from inside `backend/` (paths in the code are relative to it — e.g. `rag.py` opens `db/`, `main.py` reads `../config.json`).

```powershell
# One-time setup
python -m venv venv && venv\Scripts\activate
pip install -r backend/requirements.txt        # runtime deps
pip install -r backend/requirements-dev.txt    # + pytest, for running tests
# No `ollama pull`: inference uses the bundled llama.cpp binary at backend/bin/
# llama-server.exe with GGUF models in backend/models/ (both gitignored, shipped
# by the installer). Model filenames come from config.json's "models" block.

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

# Tests & acceptance
pytest                                         # backend/tests/ (rag, ingest, audit)
python acceptance_m1.py                        # ~15 Spanish queries through retrieve()
```

Frontend (`frontend/`) and desktop shell (`electron/`):

```powershell
cd frontend && npm install && npm run build    # tsc + vite -> frontend/dist
npm run dev                                     # Vite dev server
npm run smoke:render && npm run smoke:chat      # render + streamed-chat smoke tests

# From repo root, after frontend build:
npm install && npm start                        # Electron shell (spawns backend, loads dist)
```

`inference.py` starts the llama-server subprocesses lazily on first use (one for
chat, one for embeddings) and reaps them at exit — nothing external needs to be
running first. Scripts fail fast with a clear message if the binary or a required
model file is missing.

## Architecture

The request flow is: **corpus_fetcher.py** downloads PDFs → **ingest.py** chunks + embeds them into LanceDB → **main.py** serves chat, calling **rag.py** to retrieve context per query → the bundled **llama.cpp** server (via `inference.py`) generates the answer.

**`inference.py`** — local inference layer, imported by `main.py`, `rag.py`, and `ingest.py`. Manages the bundled official llama.cpp `llama-server` binary (`backend/bin/`) rather than an in-process Python binding (prebuilt `llama-cpp-python` wheels need AVX-512 that many target machines lack; the official binary does runtime CPU dispatch). Runs two lazily-started, localhost, OpenAI-compatible server processes — one chat, one embeddings (`--embedding`) — reaped at exit. Query-time and index-time embeddings go through the identical model and the correct nomic task prefixes (`search_query:` vs `search_document:`), a hard requirement for retrieval quality. Chat model is chosen by total RAM (FR-15): a low-RAM fallback below `lowRamThresholdGb` (default 12 GB).

**`main.py`** — FastAPI app, five endpoints:
- `POST /chat` — the core endpoint. Builds a **topic-aware retrieval query** from the recent user turns (via `_retrieval_query`, so multi-turn follow-ups like "menciona 5 ejemplos" keep the conversation topic instead of retrieving on the bare phrase), calls `rag.retrieve()`, injects the retrieved legal text into an augmented user message, then streams the model's response back as SSE. The stream sends a `citations` event first (so the frontend can render sources immediately), then `token` events, then a `done` event.
- `POST /ingest` — triggers a corpus ingest run.
- `POST /search` — Brave web search, gated on `braveApiKey` in config.json (503 if absent). Appends `{timestamp, query, resultCount}` to `backend/logs/search_audit.log`, one JSON line per outbound query (FR-07). Endpoint and its `webSearch` client remain in place but are **dormant** — the UI control is parked (see `frontend/`), so nothing calls it yet.
- `GET /status` — health check; the desktop shell polls this to know the backend is ready.
- `GET /config` — serves `config.json` (per-municipality branding + flags) to the frontend.

**`rag.py`** — hybrid retrieval, the heart of the system. `retrieve()` embeds the query via `inference.py`, runs **both** vector search and BM-25 full-text search against the same LanceDB table, then merges (vector results first, deduped by `(source, chunk_index)`, capped at `TOP_K=5`). FTS degrades gracefully to empty if the tantivy index is missing. LanceDB is synchronous, so the two searches run sequentially. Not a standalone script — imported by main.py.

**`ingest.py`** — builds the DB. Recursively scans `corpus/` for PDFs/TXTs (tier subdirectories are cosmetic — ingest flattens them). Chunks to ~500 chars with 50-char overlap, splitting on sentence boundaries. Embeds each chunk one-at-a-time via `inference.py` (embeddings are the slow step). Schema: `text, embedding, source, chunk_index, char_offset`. `source` is just the filename and is what appears in citations. Finally builds the FTS index that `rag.fts_search` depends on.

**`corpus_fetcher.py`** — downloads Chilean law PDFs from BCN's (leychile.cl) public export endpoint by `idNorma`. The corpus is defined as hardcoded tier lists (`TIER_0_GENERAL`, `TIER_1_CORE`, `TIER_2_EXTENDED`) — each entry is `{idNorma, filename, desc}`. To add a law, add an entry with its BCN norma id. BCN returns HTML error pages with HTTP 200 for bad ids, so the downloader sniffs content-type + size to detect failures. Municipality ordenanzas are discovered dynamically via BCN's CSV search endpoint.

**`convert.py`** — a throwaway utility that converts every corpus PDF to TXT via PyMuPDF (`fitz`). Non-destructive (writes the TXT alongside the PDF; earlier versions deleted the original). Not part of the main pipeline — `ingest.py` already reads PDFs directly, so this is only for cases where pypdf extraction is poor and PyMuPDF does better.

**`frontend/`** — React + Vite + TypeScript chat UI. `src/api.ts` `streamChat` is a fetch + ReadableStream SSE parser that consumes `/chat` (FR-04); `Chat.tsx` renders the conversation, `Message.tsx` renders citations (source filename + chunk, FR-03/FR-12), `ComingSoonPill.tsx` renders the two parked "Pronto disponible!" toolbar pills (Búsqueda web — FR-05, currently deferred — and a future "Fuentes oficiales" per-comuna source lookup; the old `SearchToggle.tsx` was removed), and `App.tsx` pulls per-municipality branding from `GET /config`. `scripts/smoke-render.mjs` and `scripts/smoke-chat.mjs` are Node smoke tests.

**`electron/`** — desktop shell. `main.js` spawns and reaps the Python backend (kills the uvicorn + llama-server process tree), polls `/status` via `waitForBackend`, then loads the built `frontend/dist` and injects the backend URL through `preload.js` `additionalArguments`. `splash.html` is the boot splash. contextIsolation on, nodeIntegration off. Packaged with electron-builder (root `package.json`).

**`installer/munigpt.iss`** — Inno Setup script (FR-14) for the Windows installer that bundles the llama.cpp binary, GGUF models, backend, and desktop UI. Git-tracked via a `!installer/munigpt.iss` exception to the `*.iss` ignore rule. Script only — the compiled `.exe` is not built in-repo.

## Important notes

- **Corpus, `db/`, `backend/bin/`, and `backend/models/` are gitignored** (too large — shipped via installer, not git). `config.json` and `.env` are also gitignored, so secrets like `braveApiKey` live only on the machine. `config.example.json` is the committed template.
- **Model choices are config-driven, not hardcoded.** `inference.py` reads the `models` block from `config.json` (falling back to `config.example.json`, then built-in defaults): `chatDefault` (`Qwen3-4B-Instruct-Q4_K_M.gguf`), `chatLowRam` (`Qwen3-1.7B-Q4_K_M.gguf`), `embedding` (`nomic-embed-text-v2-moe.Q4_K_M.gguf`), plus `lowRamThresholdGb`, `nCtx`, `nThreads`. Runs CPU-only, no GPU. To change a model, edit config and drop the GGUF into `backend/models/`.
- **Ollama has been fully removed** — replaced by the bundled llama.cpp server (commit `0ceb3ca`). The README, code, and this file all reflect that; older references to Ollama or `qwen2.5:3b`/`nomic-embed-text` are historical.
- **Offline licensing (FR-08) is not implemented yet.** `config.json` carries a `license` block placeholder and `requirements.txt` lists `cryptography`, but the actual license-verification scheme is a gated decision (see `docs/CHECKLIST_1.0.md` section B1) and must not be invented.
- **Status:** the repo is a 1.0 release candidate — code-complete for the backend (M1), frontend (M2), and Electron shell (M3), with the installer scripted but not compiled. `docs/CHECKLIST_1.0.md` is the authoritative Definition-of-Done; its section B lists what remains (licensing, shipping-model verification, compiled installer + pilot).

## Working conventions

These come from the repo owner's global preferences and apply to all work in this repo:

- **No emojis** anywhere — code, comments, docs, commit messages, PR descriptions, or chat.
- **No AI attribution** — never add a `Co-Authored-By: Claude` trailer, a "Generated with Claude Code" line, or any mention/credit of an AI in commits, PRs, code, comments, or docs.
- **Never invent facts** — no made-up legal articles, norma ids, citations, numbers, or references. This is both a house rule and the core product requirement: if a detail isn't verified or provided, stop and ask rather than fill the gap. It mirrors the system prompt in `main.py`, which forbids the model from inventing legal references.
- **Not a lawyer — no legal advice.** This project sits in the Chilean municipal-law domain, but do not give legal opinions or interpretations. On any IP, licensing, contract, or liability question, decline and defer to a qualified lawyer.
- **Present decisions as interactive options** (the arrow-selectable question UI), not plain-text lists, whenever offering the user a choice — with exactly one option marked "(Recommended)" first, and the reasoning stated.
- **Commit/push only when asked.** This is a solo repo: when told to commit, work directly on `main` unless asked otherwise (do not spin up feature branches for small changes).
