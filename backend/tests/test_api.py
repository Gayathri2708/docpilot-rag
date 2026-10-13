"""API tests with retrieval, the LLM and API-key lookup stubbed out, so they run without Postgres or an LLM key.
(TestClient is used without a `with` block, so the startup hook that connects to the DB does not run.)
End-to-end access-control tests against a real database are in test_rbac_integration.py."""

import json

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from app import auth, llm, main
from app.auth import Principal, require_principal
from app.retrieval import Hit

client = TestClient(main.app)

ADMIN = Principal("test-admin", ("all", "hr", "finance", "engineering"))
ENGINEER = Principal("test-engineering", ("all", "engineering"))


@pytest.fixture(autouse=True)
def caller():
    """Every request is made as ADMIN unless a test switches the caller."""
    def use(principal):
        main.app.dependency_overrides[require_principal] = lambda: principal

    use(ADMIN)
    yield use
    main.app.dependency_overrides.clear()

HITS = [
    Hit(1, "d1", "handbook.md", None, 0, "Employees receive 24 days of paid leave per calendar year.", 0.82),
    Hit(2, "d1", "handbook.md", None, 1, "Sick leave is 12 days per year.", 0.61),
]


@pytest.fixture
def relevant(monkeypatch):
    monkeypatch.setattr(main, "search", lambda q, k, groups, mode=None, rerank=None: HITS[:k])


@pytest.fixture
def irrelevant(monkeypatch):
    unrelated = Hit(3, "d1", "handbook.md", None, 2, "Unrelated.", 0.2)
    monkeypatch.setattr(main, "search", lambda q, k, groups, mode=None, rerank=None: [unrelated])


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
    assert events[-1][0] == "error"
    assert "RuntimeError" in events[-1][1]["message"]
    assert "provider timeout" not in events[-1][1]["message"]  # details stay in the server log


def test_provider_error_details_are_not_returned_to_clients(relevant, monkeypatch):
    def rate_limited(_):
        raise openai.RateLimitError(
            "Rate limit reached in organization org_SECRET123 on tokens per day",
            response=httpx.Response(429, request=httpx.Request("POST", "https://llm.example/chat")),
            body=None,
        )

    monkeypatch.setattr(llm, "complete", rate_limited)
    resp = client.post("/ask", json={"question": "How much leave?"})
    assert resp.status_code == 502
    assert "rate limit" in resp.json()["detail"]
    assert "org_SECRET123" not in resp.text


def test_stream_reports_model_refusal_as_not_answered(relevant, monkeypatch):
    monkeypatch.setattr(llm, "stream", lambda messages: iter(["I couldn’t find this in the uploaded documents."]))
    events = _events(client.post("/ask/stream", json={"question": "Dress code?"}).text)
    assert events[-1][0] == "done"
    assert events[-1][1]["answered"] is False
    assert events[-1][1]["cited"] == []


def test_curly_apostrophe_refusal_is_not_answered(relevant, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda messages: "I couldn’t find this in the uploaded documents.")
    assert client.post("/ask", json={"question": "Dress code?"}).json()["answered"] is False


def test_unreadable_pdf_is_rejected_with_422(monkeypatch):
    monkeypatch.setattr(main.db, "get_conn", lambda: _NoDuplicateConn())
    res = client.post("/documents", files={"file": ("broken.pdf", b"%PDF-1.4 not really a pdf")})
    assert res.status_code == 422
    assert "could not be read" in res.json()["detail"]


def test_health_returns_503_when_database_is_down(monkeypatch):
    def down():
        raise OSError("connection refused")

    monkeypatch.setattr(main.db, "get_conn", down)
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["database"] is False


class _NoDuplicateConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args):
        return self

    def fetchone(self):
        return None


def test_unsupported_upload_is_rejected(monkeypatch):
    monkeypatch.setattr(main.db, "get_conn", lambda: _NoDuplicateConn())
    res = client.post("/documents", files={"file": ("photo.png", b"\x89PNG data")})
    assert res.status_code == 415


# ---------- authentication and access control ----------

@pytest.fixture
def real_auth(monkeypatch):
    """Use the real require_principal, with the key lookup stubbed instead of the database."""
    main.app.dependency_overrides.clear()
    keys = {"good-key": ENGINEER}
    monkeypatch.setattr(auth, "lookup", lambda key: keys.get(key))


@pytest.mark.parametrize("path, body", [
    ("/search", {"query": "leave"}),
    ("/ask", {"question": "leave"}),
    ("/ask/stream", {"question": "leave"}),
])
def test_missing_or_invalid_key_returns_401(real_auth, path, body):
    assert client.post(path, json=body).status_code == 401
    assert client.post(path, json=body, headers={"X-API-Key": "wrong"}).status_code == 401


def test_documents_endpoints_require_key(real_auth):
    assert client.get("/documents").status_code == 401
    assert client.delete("/documents/abc").status_code == 401
    assert client.post("/documents", files={"file": ("a.md", b"text")}).status_code == 401


def test_health_is_public(real_auth, monkeypatch):
    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *args):
            return self

    monkeypatch.setattr(main.db, "get_conn", lambda: Conn())
    assert client.get("/health").status_code == 200


def test_valid_key_reaches_search_with_its_groups(real_auth, monkeypatch):
    seen = {}

    def fake_search(q, k, groups, mode=None, rerank=None):
        seen["groups"] = groups
        return []

    monkeypatch.setattr(main, "search", fake_search)
    resp = client.post("/search", json={"query": "leave"}, headers={"X-API-Key": "good-key"})
    assert resp.status_code == 200
    assert seen["groups"] == ("all", "engineering")


@pytest.mark.parametrize("path, body", [("/ask", {"question": "q"}), ("/ask/stream", {"question": "q"})])
def test_ask_endpoints_retrieve_with_caller_groups(caller, monkeypatch, path, body):
    seen = {}

    def fake_search(q, k, groups, mode=None, rerank=None):
        seen["groups"] = groups
        return []

    caller(ENGINEER)
    monkeypatch.setattr(main, "search", fake_search)
    client.post(path, json=body)
    assert seen["groups"] == ("all", "engineering")


def test_upload_into_a_group_the_key_lacks_is_forbidden(caller):
    caller(ENGINEER)
    resp = client.post("/documents", files={"file": ("pay.md", b"salary bands")}, data={"access_group": "hr"})
    assert resp.status_code == 403


def test_upload_rejects_unknown_group():
    resp = client.post("/documents", files={"file": ("a.md", b"text")}, data={"access_group": "legal"})
    assert resp.status_code == 422
