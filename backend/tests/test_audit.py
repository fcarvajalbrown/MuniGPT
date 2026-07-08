"""
Unit test for FR-07: the /search local audit log helper in main.py.

Verifies that _append_search_audit writes one well-formed JSON line per call,
containing exactly {timestamp, query, resultCount}.
"""

import json
from pathlib import Path

import main


def test_append_search_audit_writes_json_line(tmp_path, monkeypatch):
    log_path = tmp_path / "logs" / "search_audit.log"
    monkeypatch.setattr(main, "AUDIT_LOG_PATH", log_path)

    main._append_search_audit("ordenanza de tránsito", 5)
    main._append_search_audit("permisos de circulación", 0)

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert set(first.keys()) == {"timestamp", "query", "resultCount"}
    assert first["query"] == "ordenanza de tránsito"
    assert first["resultCount"] == 5
    # Timestamp is ISO-8601 parseable.
    from datetime import datetime
    datetime.fromisoformat(first["timestamp"])

    second = json.loads(lines[1])
    assert second["resultCount"] == 0


def test_append_search_audit_is_non_fatal_on_bad_path(monkeypatch):
    # A directory that cannot be created must not raise out of the helper.
    monkeypatch.setattr(main, "AUDIT_LOG_PATH", Path("\0invalid") / "x.log")
    main._append_search_audit("q", 1)  # should silently no-op, not raise
