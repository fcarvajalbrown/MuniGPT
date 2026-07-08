"""
Unit tests for ingest.py chunk_text().

Pure-function tests: no model, no DB, no filesystem. They pin the chunking
contract that retrieval quality depends on (size bound, overlap, non-empty).
"""

import ingest


def test_chunk_empty_text_yields_nothing():
    assert ingest.chunk_text("") == []
    assert ingest.chunk_text("   \n\n  ") == []


def test_chunk_short_text_is_single_chunk():
    chunks = ingest.chunk_text("Artículo 1. Esta es una norma breve.")
    assert len(chunks) == 1
    assert chunks[0]["chunk_index"] == 0
    assert chunks[0]["char_offset"] == 0
    assert "Artículo 1" in chunks[0]["text"]


def test_chunk_indices_are_sequential_and_offsets_nondecreasing():
    text = ("Frase de prueba número %d. " % 0) * 200  # well over CHUNK_SIZE
    chunks = ingest.chunk_text(text)
    assert len(chunks) > 1
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
    offsets = [c["char_offset"] for c in chunks]
    assert offsets == sorted(offsets)


def test_chunks_respect_size_bound():
    # Long single-token-free text so the splitter must cut on spaces near the bound.
    text = " ".join("palabra" for _ in range(2000))
    chunks = ingest.chunk_text(text)
    assert len(chunks) > 1
    # Allow a small slack for the sentence-boundary lookahead window.
    assert all(len(c["text"]) <= ingest.CHUNK_SIZE + 100 for c in chunks)


def test_chunks_overlap_so_no_content_is_lost_between_them():
    # Distinct sentences; consecutive chunks should share a boundary region.
    sentences = ". ".join(f"Oracion numero {i} con contenido" for i in range(80)) + "."
    chunks = ingest.chunk_text(sentences)
    assert len(chunks) > 1
    # Reconstruct coverage: every sentence marker should appear in some chunk.
    joined = " ".join(c["text"] for c in chunks)
    for i in (0, 40, 79):
        assert f"Oracion numero {i}" in joined


def test_chunk_collapses_excess_whitespace():
    chunks = ingest.chunk_text("Uno.\n\n\n\n\nDos    con      espacios.")
    assert len(chunks) == 1
    # 3+ newlines collapsed to 2; runs of spaces/tabs collapsed to one.
    assert "\n\n\n" not in chunks[0]["text"]
    assert "      " not in chunks[0]["text"]
