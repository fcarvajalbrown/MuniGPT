"""
rag.py — retrieves relevant chunks from LanceDB and assembles LLM context.
Used by main.py. Not a standalone script.
"""

import httpx
import lancedb
from pathlib import Path

DB_DIR      = Path("db")
TABLE_NAME  = "corpus"
EMBED_MODEL = "nomic-embed-text"
OLLAMA_URL  = "http://localhost:11434/api/embeddings"
TOP_K       = 5


async def embed_query(query: str) -> list[float]:
    """Embeds a query string via Ollama, returns a vector."""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            OLLAMA_URL,
            json={"model": EMBED_MODEL, "prompt": query},
            timeout=30.0,
        )
        r.raise_for_status()
        return r.json()["embedding"]


def get_table():
    """Opens the LanceDB corpus table. Raises if DB or table not found."""
    if not DB_DIR.exists():
        raise RuntimeError(f"DB not found at {DB_DIR}. Run ingest.py first.")
    db = lancedb.connect(str(DB_DIR))
    if TABLE_NAME not in db.list_tables(): # type: ignore
        raise RuntimeError(f"Table '{TABLE_NAME}' not found. Run ingest.py first.")
    return db.open_table(TABLE_NAME)


def vector_search(table, embedding: list[float]) -> list[dict]:
    """Returns top-k chunks by vector similarity."""
    results = (
        table.search(embedding)
        .limit(TOP_K)
        .select(["text", "source", "chunk_index"])
        .to_list()
    )
    return results


def fts_search(table, query: str) -> list[dict]:
    """Returns top-k chunks by BM-25 full-text search."""
    try:
        results = (
            table.search(query, query_type="fts")
            .limit(TOP_K)
            .select(["text", "source", "chunk_index"])
            .to_list()
        )
        return results
    except Exception:
        # FTS index may not exist if tantivy wasn't installed
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
    Main entry point. Embeds the query, runs hybrid search,
    deduplicates results, and returns (context_string, raw_chunks).

    Args:
        query: User question in plain text.

    Returns:
        Tuple of (context string for LLM, list of raw chunk dicts for citations).
    """
    table = get_table()

    # Run both search types in parallel would be cleaner but LanceDB
    # is not async — run sequentially, combine results.
    embedding = await embed_query(query)
    vec_results = vector_search(table, embedding)
    fts_results = fts_search(table, query)

    # Merge: vector results first (higher semantic relevance), then FTS
    combined = deduplicate(vec_results + fts_results)[:TOP_K]
    context  = build_context(combined)

    return context, combined