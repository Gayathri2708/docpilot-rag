"""API tests with retrieval and the LLM stubbed out, so they run without Postgres or an API key.
(TestClient is used without a `with` block, so the startup hook that connects to the DB does not run.)"""

import json

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from app import llm, main
from app.retrieval import Hit

client = TestClient(main.app)

HITS = [
    Hit(1, "d1", "handbook.md", None, 0, "Employees receive 24 days of paid leave per calendar year.", 0.82),
    Hit(2, "d1", "handbook.md", None, 1, "Sick leave is 12 days per year.", 0.61),
]


@pytest.fixture
def relevant(monkeypatch):
    monkeypatch.setattr(main, "search", lambda q, k: HITS[:k])


@pytest.fixture
def irrelevant(monkeypatch):
    monkeypatch.setattr(main, "search", lambda q, k: [Hit(3, "d1", "handbook.md", None, 2, "Unrelated.", 0.2)])


def test_ask_returns_answer_with_cited_sources(relevant, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda messages: "Employees get 24 days of paid leave [1].")
    body = client.post("/ask", json={"question": "How much leave?"}).json()
    assert body["answered"] is True
    assert body["answer"].startswith("Employees get 24 days")
    assert [s["cited"] for s in body["sources"]] == [True, False]
    assert {"retrieval", "generation", "total"} <= body["timings_ms"].keys()


def test_low_relevance_refuses_without_calling_llm(irrelevant, monkeypatch):
    def fail(_):
        raise AssertionError("LLM must not be called when retrieval confidence is low")

    monkeypatch.setattr(llm, "complete", fail)
    body = client.post("/ask", json={"question": "Who is the CEO?"}).json()
    assert body["answered"] is False
    assert body["answer"] == llm.REFUSAL


def test_llm_refusal_is_reported_as_not_answered(relevant, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda messages: llm.REFUSAL)
    body = client.post("/ask", json={"question": "Dress code?"}).json()
    assert body["answered"] is False


def test_missing_api_key_returns_503(relevant, monkeypatch):
    def not_configured(_):
        raise llm.LLMNotConfigured("LLM_API_KEY is not set.")

    monkeypatch.setattr(llm, "complete", not_configured)
    assert client.post("/ask", json={"question": "How much leave?"}).status_code == 503


def test_llm_provider_error_returns_502(relevant, monkeypatch):
    def provider_down(_):
        raise openai.APIConnectionError(request=httpx.Request("POST", "https://llm.example/chat"))

    monkeypatch.setattr(llm, "complete", provider_down)
    resp = client.post("/ask", json={"question": "How much leave?"})
    assert resp.status_code == 502
    assert "LLM provider error" in resp.json()["detail"]


def test_validation_rejects_empty_question():
    assert client.post("/ask", json={"question": ""}).status_code == 422


def _events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_stream_emits_sources_tokens_done(relevant, monkeypatch):
    monkeypatch.setattr(llm, "stream", lambda messages: iter(["Leave is ", "24 days [1]."]))
    events = _events(client.post("/ask/stream", json={"question": "How much leave?"}).text)
    names = [e[0] for e in events]
    assert names == ["sources", "token", "token", "done"]
    assert "".join(e[1]["text"] for e in events if e[0] == "token") == "Leave is 24 days [1]."
    assert events[-1][1]["cited"] == [1]


def test_stream_reports_generation_errors(relevant, monkeypatch):
    def broken(_):
        yield "partial "
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(llm, "stream", broken)
    events = _events(client.post("/ask/stream", json={"question": "How much leave?"}).text)
    assert events[-1] == ("error", {"message": "provider timeout"})


def test_unsupported_upload_is_rejected(monkeypatch):
    class NoDuplicate:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *args):
            return self

        def fetchone(self):
            return None

    monkeypatch.setattr(main.db, "get_conn", lambda: NoDuplicate())
    res = client.post("/documents", files={"file": ("photo.png", b"\x89PNG data")})
    assert res.status_code == 415
