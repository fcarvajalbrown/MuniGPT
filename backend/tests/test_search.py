"""
Unit tests for the /search endpoint (FR-05 web search via DDGS/DuckDuckGo).

DDGS is an unofficial, free, no-API-key client, so the endpoint is gated on the
`webSearchEnabled` config flag rather than the presence of a key. These tests
stub out DDGS itself (no real network calls) and check gating, result mapping,
error handling, and that FR-07 auditing still fires.
"""

import asyncio
import json

import main
from ddgs.exceptions import DDGSException


class FakeDDGS:
    def __init__(self, results=None, exc=None):
        self._results = results or []
        self._exc = exc

    def text(self, query, max_results=5):
        if self._exc:
            raise self._exc
        return self._results


def _write_config(tmp_path, monkeypatch, web_search_enabled):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({"webSearchEnabled": web_search_enabled}), encoding="utf-8"
    )
    monkeypatch.setattr(main, "CONFIG_PATH", cfg_path)


def test_search_disabled_returns_503(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, web_search_enabled=False)

    async def run():
        try:
            await main.search(main.SearchRequest(query="patente de alcoholes"))
            assert False, "expected HTTPException"
        except main.HTTPException as e:
            assert e.status_code == 503

    asyncio.run(run())


def test_search_maps_ddgs_results_and_audits(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, web_search_enabled=True)
    log_path = tmp_path / "logs" / "search_audit.log"
    monkeypatch.setattr(main, "AUDIT_LOG_PATH", log_path)
    monkeypatch.setattr(
        main,
        "DDGS",
        lambda: FakeDDGS(
            results=[
                {"title": "T1", "href": "https://a.example", "body": "B1"},
                {"title": "T2", "href": "https://b.example", "body": "B2"},
            ]
        ),
    )

    result = asyncio.run(main.search(main.SearchRequest(query="permiso de circulación")))

    assert result == {
        "results": [
            {"title": "T1", "url": "https://a.example", "snippet": "B1"},
            {"title": "T2", "url": "https://b.example", "snippet": "B2"},
        ]
    }
    audit_lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(audit_lines) == 1
    entry = json.loads(audit_lines[0])
    assert entry["query"] == "permiso de circulación"
    assert entry["resultCount"] == 2


def test_search_wraps_ddgs_exception_as_502(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, web_search_enabled=True)
    monkeypatch.setattr(
        main, "DDGS", lambda: FakeDDGS(exc=DDGSException("rate limited"))
    )

    async def run():
        try:
            await main.search(main.SearchRequest(query="patente municipal"))
            assert False, "expected HTTPException"
        except main.HTTPException as e:
            assert e.status_code == 502

    asyncio.run(run())
