"""
inference.py — local inference for MuniGPT via a bundled llama.cpp server.

Uses the official llama.cpp `llama-server` binary (backend/bin/) rather than an
in-process Python binding: the prebuilt llama-cpp-python wheels require CPU
instructions (AVX-512) that many target machines lack, whereas the official
binary does runtime CPU-feature dispatch and runs on any x86-64.

Two server processes are managed lazily and served over localhost HTTP
(OpenAI-compatible): one for chat (Qwen) and one for embeddings (nomic,
--embedding). They start on first use and are reaped at process exit. main.py,
rag.py and ingest.py all import this module, so query-time and index-time
embeddings are produced by the identical model and task prefixes — a hard
requirement for correct retrieval.
"""

from __future__ import annotations

import atexit
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Iterator, Optional

import httpx
import psutil

# ── Paths & config ────────────────────────────────────────────────────────────

BACKEND_DIR     = Path(__file__).resolve().parent
MODELS_DIR      = BACKEND_DIR / "models"
BIN_DIR         = BACKEND_DIR / "bin"
SERVER_EXE      = BIN_DIR / ("llama-server.exe" if os.name == "nt" else "llama-server")
_CONFIG_PATH    = BACKEND_DIR.parent / "config.json"
_CONFIG_EXAMPLE = BACKEND_DIR.parent / "config.example.json"

# nomic-embed-text task instruction prefixes. The document side and the query
# side MUST use their matching prefix or retrieval quality degrades badly.
_QUERY_PREFIX    = "search_query: "
_DOCUMENT_PREFIX = "search_document: "

_DEFAULT_MODELS = {
    "chatDefault":       "Qwen3-4B-Instruct-Q4_K_M.gguf",
    "chatLowRam":        "Qwen3-1.7B-Q4_K_M.gguf",
    "embedding":         "nomic-embed-text-v2-moe.Q4_K_M.gguf",
    "lowRamThresholdGb": 12,
    "nCtx":              4096,
    "nThreads":          0,
    "embedCtx":          512,
}


def _load_models_config() -> dict:
    """Reads the 'models' block from config.json (or the example), with defaults."""
    for path in (_CONFIG_PATH, _CONFIG_EXAMPLE):
        if path.exists():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
                return {**_DEFAULT_MODELS, **cfg.get("models", {})}
            except Exception:
                pass
    return dict(_DEFAULT_MODELS)


# ── Model selection (FR-15) ─────────────────────────────────────────────────────

def select_chat_model_name() -> str:
    """Picks the chat model by total RAM: low-RAM fallback below the threshold."""
    cfg = _load_models_config()
    total_gb = psutil.virtual_memory().total / (1024 ** 3)
    if total_gb < float(cfg["lowRamThresholdGb"]):
        return cfg["chatLowRam"]
    return cfg["chatDefault"]


def embedding_model_name() -> str:
    return _load_models_config()["embedding"]


def _thread_args() -> list[str]:
    n = int(_load_models_config().get("nThreads", 0))
    return ["-t", str(n)] if n > 0 else []


# ── llama-server process management ──────────────────────────────────────────────

def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Server:
    """A single managed llama-server subprocess (chat or embed)."""

    def __init__(self, role: str, model_name: str, extra_args: list[str]):
        self.role = role
        self.model_name = model_name
        self.extra_args = extra_args
        self.proc: Optional[subprocess.Popen] = None
        self.base: Optional[str] = None
        self._lock = threading.Lock()

    def ensure(self) -> str:
        """Starts the server if needed, waits until healthy, returns its base URL."""
        with self._lock:
            if self.proc is not None and self.proc.poll() is None:
                return self.base  # type: ignore[return-value]

            model_path = MODELS_DIR / self.model_name
            if not SERVER_EXE.exists():
                raise FileNotFoundError(f"llama-server binary not found: {SERVER_EXE}")
            if not model_path.exists():
                raise FileNotFoundError(f"Model not found: {model_path}")

            port = _free_port()
            self.base = f"http://127.0.0.1:{port}"
            args = [
                str(SERVER_EXE),
                "-m", str(model_path),
                "--host", "127.0.0.1",
                "--port", str(port),
                *self.extra_args,
                *_thread_args(),
            ]
            self.proc = subprocess.Popen(
                args,
                cwd=str(BIN_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._wait_healthy()
            return self.base

    def _wait_healthy(self, timeout: float = 180.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:  # type: ignore[union-attr]
                raise RuntimeError(f"llama-server ({self.role}) exited during startup")
            try:
                r = httpx.get(f"{self.base}/health", timeout=2.0)
                if r.status_code == 200 and r.json().get("status") == "ok":
                    return
            except Exception:
                pass
            time.sleep(0.5)
        raise TimeoutError(f"llama-server ({self.role}) did not become healthy in {timeout}s")

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()


_servers_lock = threading.Lock()
_chat_server: Optional[_Server] = None
_embed_server: Optional[_Server] = None
_embed_dim: Optional[int] = None


def _get_chat_base() -> str:
    global _chat_server
    with _servers_lock:
        if _chat_server is None:
            cfg = _load_models_config()
            _chat_server = _Server(
                "chat", select_chat_model_name(),
                # --jinja uses the GGUF's own chat template (correct for Qwen3,
                # incl. the enable_thinking switch used in stream_chat).
                ["-c", str(cfg.get("nCtx", 4096)), "--jinja"],
            )
    return _chat_server.ensure()


def _get_embed_base() -> str:
    global _embed_server
    with _servers_lock:
        if _embed_server is None:
            cfg = _load_models_config()
            _embed_server = _Server(
                "embed", embedding_model_name(),
                ["--embedding", "-c", str(cfg.get("embedCtx", 512))],
            )
    return _embed_server.ensure()


def shutdown():
    """Stops both managed servers. Registered atexit; also called on API shutdown."""
    for srv in (_chat_server, _embed_server):
        if srv is not None:
            srv.stop()


atexit.register(shutdown)


# ── Embeddings ──────────────────────────────────────────────────────────────────

def _embed_raw(texts: list[str]) -> list[list[float]]:
    base = _get_embed_base()
    r = httpx.post(f"{base}/v1/embeddings", json={"input": texts}, timeout=120.0)
    r.raise_for_status()
    data = sorted(r.json()["data"], key=lambda d: d.get("index", 0))
    return [d["embedding"] for d in data]


def embed_query(text: str) -> list[float]:
    """Embeds a search query (nomic query prefix)."""
    return _embed_raw([_QUERY_PREFIX + text])[0]


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embeds corpus chunks (nomic document prefix)."""
    return _embed_raw([_DOCUMENT_PREFIX + t for t in texts])


def embedding_dim() -> int:
    """Vector length of the embedding model (probes once, then cached)."""
    global _embed_dim
    if _embed_dim is None:
        _embed_dim = len(_embed_raw(["dimension probe"])[0])
    return _embed_dim


# ── Chat ────────────────────────────────────────────────────────────────────────

def stream_chat(messages: list[dict], *, temperature: float = 0.2,
                max_tokens: int = 1024) -> Iterator[str]:
    """
    Yields assistant token strings for the given chat messages, streamed from the
    chat llama-server (OpenAI-compatible /v1/chat/completions). The server applies
    the GGUF's embedded chat template.
    """
    base = _get_chat_base()
    payload = {
        "messages": messages,
        "stream": True,
        "temperature": temperature,
        "max_tokens": max_tokens,
        # Qwen3 hybrid-thinking models emit <think> blocks by default; municipal
        # users want direct answers. Harmless for non-thinking models (2507-Instruct).
        "chat_template_kwargs": {"enable_thinking": False},
    }
    with httpx.stream("POST", f"{base}/v1/chat/completions", json=payload, timeout=None) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            data = line[len("data: "):].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            delta = obj["choices"][0].get("delta", {})
            token = delta.get("content")
            if token:
                yield token


# ── Status helpers ────────────────────────────────────────────────────────────

def missing_models() -> list[str]:
    """Model filenames expected by config but not present on disk."""
    names = {select_chat_model_name(), embedding_model_name()}
    return [n for n in sorted(names) if not (MODELS_DIR / n).exists()]


def server_binary_present() -> bool:
    return SERVER_EXE.exists()


def model_info() -> dict:
    """Summary for the /status endpoint."""
    return {
        "chatModel":       select_chat_model_name(),
        "embeddingModel":  embedding_model_name(),
        "ramGb":           round(psutil.virtual_memory().total / (1024 ** 3), 1),
        "serverBinary":    server_binary_present(),
        "chatRunning":     _chat_server is not None and _chat_server.proc is not None
                           and _chat_server.proc.poll() is None,
        "embedRunning":    _embed_server is not None and _embed_server.proc is not None
                           and _embed_server.proc.poll() is None,
    }
