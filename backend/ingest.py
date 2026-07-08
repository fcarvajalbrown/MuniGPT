"""
ingest.py
=========
Chunks all PDFs and TXTs in the corpus directory into LanceDB.
Scans corpus/ recursively - no tier subdirectories required.

Embeddings are produced in-process by the embedded llama.cpp model
(see inference.py) — no Ollama, no network.

Usage:
    python ingest.py                  # uses ./corpus and ./db
    python ingest.py --reset          # wipe and rebuild
    python ingest.py --corpus-dir C:/path/to/corpus

The core is exposed as run_ingest(corpus_dir, db_dir, reset) so both this CLI
and the FastAPI /ingest endpoint share one implementation.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import lancedb
import pyarrow as pa

import inference

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False
    print("[warn] pypdf not installed. pip install pypdf")

# ── Config ──────────────────────────────────────────────────────────────────────

CHUNK_SIZE    = 500
CHUNK_OVERLAP = 50
TABLE_NAME    = "corpus"
META_FILE     = "embedding_meta.json"
EMBED_BATCH   = 16


# ── Text extraction ──────────────────────────────────────────────────────────────

def extract_text_from_pdf(path: Path) -> str:
    """Extracts plain text from a PDF using pypdf. Warns on likely scanned files."""
    if not HAS_PYPDF:
        print(f"  [skip] {path.name} - pypdf not installed")
        return ""

    reader = PdfReader(str(path))  # type: ignore
    pages_text = []
    empty_pages = 0

    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            pages_text.append(text)
        else:
            empty_pages += 1

    total = len(reader.pages)
    if total > 0 and empty_pages > total / 2:
        print(f"  [warn] {path.name} - {empty_pages}/{total} empty pages, may be scanned")

    return "\n".join(pages_text)


def extract_text_from_txt(path: Path) -> str:
    """Reads a plain text file, trying utf-8 then latin-1."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def extract_text(path: Path) -> str:
    """Dispatches to PDF or TXT extractor based on file extension."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(path)
    elif suffix == ".txt":
        return extract_text_from_txt(path)
    else:
        print(f"  [skip] {path.name} - unsupported type")
        return ""


# ── Chunking ─────────────────────────────────────────────────────────────────────

def chunk_text(text: str) -> list[dict]:
    """
    Splits text into overlapping chunks of ~CHUNK_SIZE characters.
    Tries to split at sentence boundaries to avoid cutting mid-sentence.
    Returns list of dicts with: text, chunk_index, char_offset.
    """
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text).strip()

    if not text:
        return []

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))

        if end < len(text):
            search_start = max(start, end - 100)
            boundary = -1
            for sep in [". ", ".\n", "\n\n", "\n", " "]:
                pos = text.rfind(sep, search_start, end)
                if pos != -1:
                    boundary = pos + len(sep)
                    break
            if boundary > start:
                end = boundary

        chunk = text[start:end].strip()
        if chunk:
            chunks.append({
                "text":        chunk,
                "chunk_index": chunk_index,
                "char_offset": start,
            })
            chunk_index += 1

        next_start = end - CHUNK_OVERLAP
        if next_start <= start:
            next_start = end
        start = next_start
        if start >= len(text):
            break

    return chunks


# ── Schema ───────────────────────────────────────────────────────────────────────

def get_schema(embedding_dim: int) -> pa.Schema:
    """PyArrow schema for the LanceDB corpus table."""
    return pa.schema([
        pa.field("text",        pa.string()),
        pa.field("embedding",   pa.list_(pa.float32(), embedding_dim)),
        pa.field("source",      pa.string()),
        pa.field("chunk_index", pa.int32()),
        pa.field("char_offset", pa.int64()),
    ])


# ── Main ─────────────────────────────────────────────────────────────────────────

def run_ingest(corpus_dir: Path, db_dir: Path, reset: bool) -> dict:
    """
    Scans corpus_dir recursively for all PDFs and TXTs, chunks them, embeds each
    chunk via the local llama.cpp embedding model, and loads into LanceDB.
    Returns {"docs": n, "chunks": n, "embedding_model": name}.
    """
    corpus_dir = Path(corpus_dir)
    db_dir     = Path(db_dir)

    if not corpus_dir.exists():
        raise FileNotFoundError(f"Corpus directory not found: {corpus_dir}")

    documents = sorted(
        f for ext in ("*.pdf", "*.txt")
        for f in corpus_dir.rglob(ext)
    )
    if not documents:
        raise FileNotFoundError(f"No PDF or TXT files found in {corpus_dir}")

    print(f"Found {len(documents)} documents in {corpus_dir}/")

    # Embedding dimension from the live model (drives the table schema).
    embedding_dim = inference.embedding_dim()
    embed_model   = inference.embedding_model_name()
    print(f"  Embedding model: {embed_model}  (dim {embedding_dim})")

    db_dir.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(db_dir))

    if reset and TABLE_NAME in db.table_names():
        print(f"Dropping table '{TABLE_NAME}'...")
        db.drop_table(TABLE_NAME)

    schema = get_schema(embedding_dim)

    if TABLE_NAME not in db.table_names():
        print(f"Creating table '{TABLE_NAME}'...")
        table = db.create_table(TABLE_NAME, schema=schema)
    else:
        print(f"Appending to table '{TABLE_NAME}'...")
        table = db.open_table(TABLE_NAME)

    total_chunks = 0

    for doc_path in documents:
        print(f"\n  {doc_path.name}")

        text = extract_text(doc_path)
        if not text or len(text) < 100:
            print(f"    [skip] No text extracted")
            continue

        print(f"    {len(text):,} chars")

        chunks = chunk_text(text)
        if not chunks:
            print(f"    [skip] No chunks produced")
            continue

        print(f"    {len(chunks)} chunks - embedding...", flush=True)

        doc_chunks = 0
        for i in range(0, len(chunks), EMBED_BATCH):
            batch = chunks[i:i + EMBED_BATCH]
            try:
                embeddings = inference.embed_documents([c["text"] for c in batch])
            except Exception as e:
                print(f"    [warn] Embedding failed: {e}")
                continue

            table.add([
                {
                    "text":        c["text"],
                    "embedding":   emb,
                    "source":      doc_path.name,
                    "chunk_index": c["chunk_index"],
                    "char_offset": c["char_offset"],
                }
                for c, emb in zip(batch, embeddings)
            ])
            doc_chunks += len(batch)

        print(f"    {doc_chunks} chunks inserted")
        total_chunks += doc_chunks
        del chunks
        del text

    # Build full-text search index (BM-25).
    print(f"\nBuilding FTS index...")
    try:
        table.create_fts_index("text", replace=True)
        print("  FTS OK")
    except Exception as e:
        print(f"  [warn] FTS failed: {e} - pip install tantivy")

    # Embedding-model metadata sidecar — rag.get_table() asserts against this so
    # a stale/mismatched DB fails loudly instead of returning garbage retrieval.
    (db_dir / META_FILE).write_text(
        json.dumps({"embedding_model": embed_model, "dim": embedding_dim}),
        encoding="utf-8",
    )

    print(f"\n{'='*50}")
    print(f"Done. {len(documents)} docs, {total_chunks} chunks.")
    print(f"DB: {db_dir}/")

    return {"docs": len(documents), "chunks": total_chunks, "embedding_model": embed_model}


def main():
    parser = argparse.ArgumentParser(description="Ingest MuniGPT corpus into LanceDB.")
    parser.add_argument("--corpus-dir", type=Path, default=Path("corpus"))
    parser.add_argument("--db-dir",     type=Path, default=Path("db"))
    parser.add_argument("--reset",      action="store_true")
    args = parser.parse_args()

    print("MuniGPT -- ingest.py")
    print(f"Corpus: {args.corpus_dir}/")
    print(f"DB:     {args.db_dir}/")
    print(f"Reset:  {args.reset}\n")

    try:
        run_ingest(corpus_dir=args.corpus_dir, db_dir=args.db_dir, reset=args.reset)
    except FileNotFoundError as e:
        print(f"[error] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
