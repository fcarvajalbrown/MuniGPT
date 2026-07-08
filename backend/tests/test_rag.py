"""
Unit tests for rag.py retrieval merge/dedup logic.

These tests are hermetic: the embedding model and LanceDB are monkeypatched out,
so they exercise the pure merge/dedup/context logic of retrieve() without needing
a running llama-server or a built DB.
"""

import asyncio

import rag


def _chunk(source, idx, text="texto"):
    return {"source": source, "chunk_index": idx, "text": text}


# ── deduplicate ──────────────────────────────────────────────────────────────────

def test_deduplicate_removes_repeats_by_source_and_index():
    chunks = [
        _chunk("a.txt", 0),
        _chunk("a.txt", 1),
        _chunk("a.txt", 0),  # duplicate of the first
        _chunk("b.txt", 0),
    ]
    out = rag.deduplicate(chunks)
    keys = [(c["source"], c["chunk_index"]) for c in out]
    assert keys == [("a.txt", 0), ("a.txt", 1), ("b.txt", 0)]


def test_deduplicate_preserves_first_occurrence_order():
    chunks = [_chunk("z.txt", 5), _chunk("a.txt", 2), _chunk("z.txt", 5)]
    out = rag.deduplicate(chunks)
    assert [(c["source"], c["chunk_index"]) for c in out] == [("z.txt", 5), ("a.txt", 2)]


# ── build_context ────────────────────────────────────────────────────────────────

def test_build_context_empty():
    assert rag.build_context([]) == ""


def test_build_context_includes_source_labels_and_separator():
    ctx = rag.build_context([_chunk("a.txt", 0, "uno"), _chunk("b.txt", 1, "dos")])
    assert "[Fuente: a.txt]" in ctx
    assert "[Fuente: b.txt]" in ctx
    assert "uno" in ctx and "dos" in ctx
    assert "---" in ctx  # chunks joined by a separator


# ── retrieve() merge/dedup (monkeypatched I/O) ───────────────────────────────────

def _patch(monkeypatch, vec, fts):
    monkeypatch.setattr(rag, "get_table", lambda: object())
    monkeypatch.setattr(rag.inference, "embed_query", lambda q: [0.0, 0.1, 0.2])
    monkeypatch.setattr(rag, "vector_search", lambda table, emb: vec)
    monkeypatch.setattr(rag, "fts_search", lambda table, q: fts)


def test_retrieve_vector_results_come_before_fts(monkeypatch):
    vec = [_chunk("vec.txt", 0)]
    fts = [_chunk("fts.txt", 0)]
    _patch(monkeypatch, vec, fts)
    _, chunks = asyncio.run(rag.retrieve("consulta"))
    assert chunks[0]["source"] == "vec.txt"
    assert chunks[1]["source"] == "fts.txt"


def test_retrieve_dedups_across_vector_and_fts(monkeypatch):
    # Same (source, chunk_index) appears in both searches -> kept once, vector wins.
    shared = _chunk("shared.txt", 3, "vector-text")
    fts_dup = _chunk("shared.txt", 3, "fts-text")
    _patch(monkeypatch, [shared], [fts_dup, _chunk("other.txt", 1)])
    _, chunks = asyncio.run(rag.retrieve("consulta"))
    keys = [(c["source"], c["chunk_index"]) for c in chunks]
    assert keys == [("shared.txt", 3), ("other.txt", 1)]
    # The vector-side text is the one preserved for the deduped chunk.
    assert chunks[0]["text"] == "vector-text"


def test_retrieve_caps_at_top_k(monkeypatch):
    vec = [_chunk("v.txt", i) for i in range(rag.TOP_K)]
    fts = [_chunk("f.txt", i) for i in range(rag.TOP_K)]
    _patch(monkeypatch, vec, fts)
    _, chunks = asyncio.run(rag.retrieve("consulta"))
    assert len(chunks) == rag.TOP_K


def test_retrieve_returns_empty_context_when_no_results(monkeypatch):
    _patch(monkeypatch, [], [])
    ctx, chunks = asyncio.run(rag.retrieve("consulta"))
    assert ctx == ""
    assert chunks == []
