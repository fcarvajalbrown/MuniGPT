"""
rag.py — retrieves relevant chunks from LanceDB and assembles LLM context.
Embeddings are produced by the embedded llama.cpp model (see inference.py).
Used by main.py. Not a standalone script.
"""

import asyncio
import json
from pathlib import Path

import lancedb

import inference

DB_DIR     = Path("db")
TABLE_NAME = "corpus"
TOP_K      = 5
META_FILE  = "embedding_meta.json"


def _assert_embedding_meta():
    """
    Fails loudly if the shipped/prebuilt DB was embedded with a different model
    than the one running now — otherwise retrieval silently returns garbage.
    """
    meta_path = DB_DIR / META_FILE
    if not meta_path.exists():
        return  # DB predates metadata; ingest.py writes it going forward.
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    expected = inference.embedding_model_name()
    if meta.get("embedding_model") != expected:
        raise RuntimeError(
            f"DB was built with embedding model '{meta.get('embedding_model')}' "
            f"but the live model is '{expected}'. Re-run: python ingest.py --reset"
        )


def get_table():
    """Opens the LanceDB corpus table. Raises if DB or table not found."""
    if not DB_DIR.exists():
        raise RuntimeError(f"DB not found at {DB_DIR}. Run ingest.py first.")
    _assert_embedding_meta()
    db = lancedb.connect(str(DB_DIR))
    if TABLE_NAME not in db.table_names():
        raise RuntimeError(f"Table '{TABLE_NAME}' not found. Run ingest.py first.")
    return db.open_table(TABLE_NAME)


def vector_search(table, embedding: list[float]) -> list[dict]:
    """Returns top-k chunks by vector similarity."""
    return (
        table.search(embedding)
        .limit(TOP_K)
        .select(["text", "source", "chunk_index"])
        .to_list()
    )


def fts_search(table, query: str) -> list[dict]:
    """Returns top-k chunks by BM-25 full-text search."""
    try:
        return (
            table.search(query, query_type="fts")
            .limit(TOP_K)
            .select(["text", "source", "chunk_index"])
            .to_list()
        )
    except Exception:
        # FTS index may not exist if tantivy wasn't installed.
        return []


def deduplicate(chunks: list[dict]) -> list[dict]:
    """Removes duplicate chunks by (source, chunk_index), preserving order."""
    seen = set()
    unique = []
    for c in chunks:
        key = (c.get("source"), c.get("chunk_index"))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def build_context(chunks: list[dict]) -> str:
    """Formats retrieved chunks into a context block for the LLM prompt."""
    if not chunks:
        return ""
    parts = []
    for c in chunks:
        source = c.get("source", "desconocido")
        text   = c.get("text", "")
        parts.append(f"[Fuente: {source}]\n{text}")
    return "\n\n---\n\n".join(parts)


async def retrieve(query: str) -> tuple[str, list[dict]]:
    """
    Main entry point. Embeds the query, runs hybrid search, deduplicates,
    and returns (context_string, raw_chunks).

    The embedding call is synchronous (llama.cpp), so it runs in a worker
    thread to avoid blocking the event loop.
    """
    table = get_table()

    embedding   = await asyncio.to_thread(inference.embed_query, query)
    vec_results = vector_search(table, embedding)
    fts_results = fts_search(table, query)

    # Merge: vector results first (higher semantic relevance), then FTS.
    combined = deduplicate(vec_results + fts_results)[:TOP_K]
    context  = build_context(combined)

    return context, combined
