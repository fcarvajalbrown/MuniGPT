"""
main.py — FastAPI backend for MuniGPT.
Endpoints: /chat (SSE streaming), /search, /ingest, /status, /config.
Run with: uvicorn main:app --port 8000 --reload

Chat and embeddings run fully locally via embedded llama.cpp (see inference.py).
The only endpoint that ever reaches the network is /search (Brave), which sends
just the query string.
"""

import asyncio
import json
import httpx
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import inference
from rag import retrieve
from ingest import run_ingest

CONFIG_PATH = Path("../config.json")

SYSTEM_PROMPT = (
    "Eres un asistente de inteligencia artificial para funcionarios municipales chilenos. "
    "Respondes SIEMPRE en español. "
    "Cuando respondas, utiliza exclusivamente la información del contexto legal proporcionado. "
    "Si la respuesta no está en el contexto, di claramente que no tienes esa información. "
    "Cita la fuente documental cuando sea relevante. "
    "Sé claro, directo y preciso. No inventes artículos ni referencias legales."
)

app = FastAPI(title="MuniGPT API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serializes ingest runs so two callers can't rebuild the DB at once.
_ingest_lock = asyncio.Lock()


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []  # list of {role, content} dicts


class SearchRequest(BaseModel):
    query: str


class IngestRequest(BaseModel):
    reset: bool = False


@app.get("/status")
async def status():
    """Health check. The Electron shell polls this to know when the backend is ready."""
    missing = inference.missing_models()
    return {
        "status": "ok",
        "ready": not missing and inference.server_binary_present(),
        "missingModels": missing,
        **inference.model_info(),
    }


@app.get("/config")
async def config():
    """Serves config.json to the frontend, with secrets stripped."""
    if not CONFIG_PATH.exists():
        return {"municipio": "MuniGPT", "logo": "logo.png", "webSearchEnabled": False}
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    # Never expose secrets to the renderer.
    cfg.pop("braveApiKey", None)
    if isinstance(cfg.get("license"), dict):
        cfg["license"].pop("licenseKey", None)
    return cfg


@app.post("/chat")
async def chat(req: ChatRequest):
    """
    RAG-augmented chat endpoint. Streams the LLM response via SSE.
    Retrieves relevant legal context, injects it into the prompt, then streams
    the local model's response token by token.
    """
    context, chunks = await retrieve(req.message)

    if context:
        augmented = (
            f"Contexto legal relevante:\n\n{context}\n\n"
            f"Pregunta del funcionario: {req.message}"
        )
    else:
        augmented = req.message

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += req.history
    messages.append({"role": "user", "content": augmented})

    citations = [
        {"source": c.get("source", ""), "chunk_index": c.get("chunk_index", 0)}
        for c in chunks
    ]

    async def stream():
        # First event: citations so the frontend can display them immediately.
        yield f"data: {json.dumps({'type': 'citations', 'citations': citations})}\n\n"

        # Bridge the blocking llama.cpp generator (run on a worker thread) to the
        # async SSE response via a thread-safe queue.
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        DONE = object()

        def produce():
            try:
                for token in inference.stream_chat(messages):
                    loop.call_soon_threadsafe(queue.put_nowait, ("token", token))
            except Exception as e:  # surface model errors to the client
                loop.call_soon_threadsafe(queue.put_nowait, ("error", str(e)))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, DONE)

        loop.run_in_executor(None, produce)

        while True:
            item = await queue.get()
            if item is DONE:
                break
            kind, payload = item
            if kind == "token":
                yield f"data: {json.dumps({'type': 'token', 'content': payload})}\n\n"
            elif kind == "error":
                yield f"data: {json.dumps({'type': 'error', 'message': payload})}\n\n"
                break
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/ingest")
async def ingest(req: IngestRequest):
    """
    Rebuilds/updates the RAG index from backend/corpus/. Lets IT re-index after
    dropping Tier-3 PDFs without a terminal. Serialized; long-running.
    """
    if _ingest_lock.locked():
        raise HTTPException(status_code=409, detail="An ingest is already running.")
    async with _ingest_lock:
        try:
            result = await asyncio.to_thread(
                run_ingest, Path("corpus"), Path("db"), req.reset
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return result


@app.post("/search")
async def search(req: SearchRequest):
    """
    Web search via Brave Search API. Only the query string leaves the machine.
    Requires braveApiKey in config.json. Returns top results as JSON.
    """
    cfg = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    api_key = cfg.get("braveApiKey")

    if not api_key:
        raise HTTPException(status_code=503, detail="Brave API key not configured.")

    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": req.query, "count": 5, "lang": "es", "country": "CL"},
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()

    results = [
        {
            "title":   item.get("title"),
            "url":     item.get("url"),
            "snippet": item.get("description"),
        }
        for item in data.get("web", {}).get("results", [])
    ]
    return {"results": results}
