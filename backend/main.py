"""
main.py — FastAPI backend for MuniGPT.
Endpoints: /chat (SSE streaming), /search, /status, /config.
Run with: uvicorn main:app --port 8000 --reload
"""

import json
import httpx
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from rag import retrieve

OLLAMA_URL  = "http://localhost:11434/api/chat"
CHAT_MODEL  = "qwen2.5:3b"
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


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []  # list of {role, content} dicts


class SearchRequest(BaseModel):
    query: str


@app.get("/status")
async def status():
    """Health check. Electron polls this to know when the backend is ready."""
    return {"status": "ok"}


@app.get("/config")
async def config():
    """Serves config.json to the frontend."""
    if not CONFIG_PATH.exists():
        return {"municipio": "MuniGPT", "logo": "logo.png", "webSearchEnabled": False}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@app.post("/chat")
async def chat(req: ChatRequest):
    """
    RAG-augmented chat endpoint. Streams the LLM response via SSE.
    Retrieves relevant legal context, injects it into the prompt,
    then streams Ollama's response token by token.
    """
    context, chunks = await retrieve(req.message)

    # Build augmented user message with legal context
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

    # Build citation list to send before streaming starts
    citations = [
        {"source": c.get("source", ""), "chunk_index": c.get("chunk_index", 0)}
        for c in chunks
    ]

    async def stream():
        # First event: citations so the frontend can display them immediately
        yield f"data: {json.dumps({'type': 'citations', 'citations': citations})}\n\n"

        # Stream LLM response
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                OLLAMA_URL,
                json={"model": CHAT_MODEL, "messages": messages, "stream": True},
                timeout=120.0,
            ) as response:
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        token = data.get("message", {}).get("content", "")
                        if token:
                            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
                        if data.get("done"):
                            yield f"data: {json.dumps({'type': 'done'})}\n\n"
                            break
                    except json.JSONDecodeError:
                        continue

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/search")
async def search(req: SearchRequest):
    """
    Web search via Brave Search API. Only the query string leaves the machine.
    Requires BRAVE_API_KEY in config.json. Returns top results as JSON.
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