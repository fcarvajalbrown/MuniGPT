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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import inference
from rag import retrieve
from ingest import run_ingest
from license import verify_license

CONFIG_PATH = Path("../config.json")


def _current_license_status() -> dict:
    """Verifies the license key in config.json and returns a renderer-safe status.

    FR-08 enforcement is SOFT: this status is surfaced to the UI (banner) but no
    endpoint blocks on it. Reads config fresh so re-activation needs no restart.
    """
    key = None
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            lic = cfg.get("license")
            if isinstance(lic, dict):
                key = lic.get("licenseKey")
        except (ValueError, OSError):
            key = None
    return verify_license(key).to_public_dict()

# FR-07: local audit trail for /search. The web-search endpoint is the only path
# that sends anything off the machine (the query string, to Brave). We record one
# JSON line per outbound search — timestamp, query, and result count — so the
# institution can audit exactly what left the machine. Kept local; never sent
# anywhere. The .log extension is gitignored so audit data is not committed.
AUDIT_LOG_PATH = Path("logs/search_audit.log")


def _append_search_audit(query: str, result_count: int) -> None:
    """Appends one JSON line {timestamp, query, resultCount} to the local audit log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "resultCount": result_count,
    }
    try:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        # Auditing must never take down the search endpoint; any failure here
        # (bad path, disk full, permissions) is swallowed as a best-effort log.
        pass

SYSTEM_PROMPT = (
    "Eres un asistente de inteligencia artificial para funcionarios municipales "
    "chilenos que atienden a vecinos. Respondes SIEMPRE en español, de forma clara "
    "y directa, orientado a resolver la necesidad de la persona.\n\n"
    "Reglas de contenido:\n"
    "- Utiliza exclusivamente la información del contexto legal proporcionado. No "
    "inventes artículos, cifras, plazos ni referencias legales. Si la respuesta no "
    "está en el contexto, dilo con claridad.\n"
    "- Cita la fuente documental (el nombre del archivo) cuando entregues contenido legal.\n\n"
    "Responde directamente la consulta con la información del contexto. Solo si la "
    "consulta es tan vaga que no puedes identificar de qué trata, haz UNA pregunta "
    "breve para precisarla; en cualquier otro caso, responde de inmediato y no pidas "
    "aclaraciones.\n\n"
    "Cuando la consulta sea sobre CÓMO o DÓNDE realizar un trámite o pago:\n"
    "- Explica lo que sí establece la normativa (por ejemplo, quién debe pagar y "
    "sobre qué base), citando la fuente.\n"
    "- Para el procedimiento concreto (dónde, cómo, montos, plazos o portal de pago), "
    "indica que ese detalle depende de cada municipalidad y que debe realizarse en el "
    "canal municipal correspondiente (por ejemplo, la Tesorería Municipal o la "
    "Dirección de Administración y Finanzas del municipio, o el portal de pagos en "
    "línea de la comuna). NO inventes direcciones, URLs, montos, oficinas ni pasos "
    "específicos que no estén en el contexto."
)


def _configured_municipio() -> Optional[str]:
    """The comuna this install serves (config.json), or None if unset/placeholder.

    Named in the system prompt so procedural answers point to the right municipality
    without inventing its specific offices or portals.
    """
    if not CONFIG_PATH.exists():
        return None
    try:
        name = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("municipio")
    except (ValueError, OSError):
        return None
    if not isinstance(name, str) or not name.strip() or name.strip() == "MuniGPT":
        return None
    return name.strip()


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
        "license": _current_license_status(),
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
    # Verified license status (FR-08) so the UI can show an activation banner.
    cfg["licenseStatus"] = _current_license_status()
    return cfg


def _retrieval_query(message: str, history: list[dict]) -> str:
    """Builds the retrieval query from the recent user turns plus the new message.

    Retrieval must be topic-aware across turns: a follow-up like "menciona 5
    ejemplos" carries no topic on its own, so we prepend the last couple of user
    messages. Only user turns are used (assistant clarifying questions would add
    noise), and we keep the current message so it still dominates the search.
    """
    prior_user = [
        m.get("content", "") for m in history if m.get("role") == "user"
    ]
    parts = [p for p in prior_user[-2:] if p.strip()]
    parts.append(message)
    return "  ".join(parts).strip()


@app.post("/chat")
async def chat(req: ChatRequest):
    """
    RAG-augmented chat endpoint. Streams the LLM response via SSE.
    Retrieves relevant legal context, injects it into the prompt, then streams
    the local model's response token by token.
    """
    context, chunks = await retrieve(_retrieval_query(req.message, req.history))

    if context:
        augmented = (
            f"Contexto legal relevante:\n\n{context}\n\n"
            f"Pregunta del funcionario: {req.message}"
        )
    else:
        augmented = req.message

    system_content = SYSTEM_PROMPT
    municipio = _configured_municipio()
    if municipio:
        system_content += (
            f"\n\nEsta instalación atiende a la {municipio}. Cuando orientes sobre "
            f"dónde realizar un trámite o pago, refiérete a los canales de esa "
            f"municipalidad, sin inventar sus oficinas, direcciones ni portales."
        )

    messages = [{"role": "system", "content": system_content}]
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
    # FR-07: record the outbound query in the local audit log.
    _append_search_audit(req.query, len(results))
    return {"results": results}
