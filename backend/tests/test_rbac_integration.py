"""Access control end to end, against a real Postgres + pgvector database and real embeddings.

Proves that an engineering key cannot reach HR-only content through any route: search (both
retrieval modes), ask, streaming ask, listing or deleting. The LLM is stubbed so the test can check
exactly what would have been sent to it.

Skipped unless TEST_DATABASE_URL points at a disposable database (its tables are truncated), e.g.
    TEST_DATABASE_URL=postgresql://docpilot:docpilot@localhost:5432/docpilot_test pytest
"""

import os

import pytest
from fastapi.testclient import TestClient

from app import db, llm, main
from app.config import settings

TEST_DB = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="set TEST_DATABASE_URL to run against Postgres")

ADMIN = {"X-API-Key": "dp_demo_admin"}
HR = {"X-API-Key": "dp_demo_hr"}
ENGINEER = {"X-API-Key": "dp_demo_engineering"}

# A unique token only the HR document contains, so any leak is unambiguous.
CANARY = "ZEBRA-4471"
HR_DOC = (
    "# Compensation review\n\n"
    f"Salary bands for the 2027 compensation review are confidential. The review code is {CANARY}. "
    "Band L5 pays between 38 and 46 lakh per year, and the review closes on 15 March.\n"
)
ENG_DOC = (
    "# Deploy process\n\n"
    "Production deploys run every Tuesday and Thursday. A deploy freeze applies during the last week "
    "of each quarter, and rollbacks need approval from the on-call lead.\n"
)
HR_QUESTION = f"What are the salary bands in the compensation review {CANARY}?"


@pytest.fixture(scope="module")
def client():
    mp = pytest.MonkeyPatch()
    mp.setattr(settings, "database_url", TEST_DB)
    mp.setattr(settings, "seed_demo_keys", True)
    mp.setattr(db, "pool", db.make_pool(TEST_DB))
    main.app.dependency_overrides.clear()
    with TestClient(main.app) as c:  # runs startup: schema, pool, demo keys
        with db.get_conn() as conn:
            conn.execute("TRUNCATE documents CASCADE")
        assert c.post("/documents", headers=ADMIN, data={"access_group": "hr"},
                      files={"file": ("compensation.md", HR_DOC.encode())}).status_code == 201
        assert c.post("/documents", headers=ADMIN, data={"access_group": "engineering"},
                      files={"file": ("deploys.md", ENG_DOC.encode())}).status_code == 201
        yield c
    mp.undo()


@pytest.fixture
def llm_inbox(monkeypatch):
    """Records every message list that would be sent to the LLM."""
    sent = []

    def complete(messages):
        sent.append(messages)
        return "Stub answer [1]."

    def stream(messages):
        sent.append(messages)
        yield "Stub answer [1]."

    monkeypatch.setattr(llm, "complete", complete)
    monkeypatch.setattr(llm, "stream", stream)
    return sent


@pytest.mark.parametrize("mode", ["vector", "hybrid"])
def test_engineer_search_never_returns_hr_chunks(client, mode):
    hits = client.post("/search", headers=ENGINEER, json={"query": HR_QUESTION, "top_k": 20, "mode": mode}).json()
    assert hits, "engineering content should still be returned"
    assert all(h["access_group"] in ("all", "engineering") for h in hits)
    assert not any(CANARY in h["content"] for h in hits)


@pytest.mark.parametrize("mode", ["vector", "hybrid"])
def test_hr_key_finds_the_hr_document(client, mode):
    hits = client.post("/search", headers=HR, json={"query": HR_QUESTION, "top_k": 3, "mode": mode}).json()
    assert CANARY in hits[0]["content"]


def test_hr_content_never_reaches_the_llm_via_ask(client, llm_inbox):
    body = client.post("/ask", headers=ENGINEER, json={"question": HR_QUESTION, "mode": "hybrid"}).json()
    assert CANARY not in str(body)
    assert CANARY not in str(llm_inbox)


def test_hr_content_never_reaches_the_llm_via_stream(client, llm_inbox):
    text = client.post("/ask/stream", headers=ENGINEER, json={"question": HR_QUESTION, "mode": "hybrid"}).text
    assert CANARY not in text
    assert CANARY not in str(llm_inbox)


def test_hr_key_gets_hr_content_into_the_prompt(client, llm_inbox):
    client.post("/ask", headers=HR, json={"question": HR_QUESTION})
    assert CANARY in str(llm_inbox)


def test_engineer_cannot_list_or_delete_hr_documents(client):
    listed = client.get("/documents", headers=ENGINEER).json()
    assert [d["filename"] for d in listed] == ["deploys.md"]

    hr_doc = next(d for d in client.get("/documents", headers=ADMIN).json() if d["access_group"] == "hr")
    assert client.delete(f"/documents/{hr_doc['id']}", headers=ENGINEER).status_code == 404
    assert any(d["id"] == hr_doc["id"] for d in client.get("/documents", headers=HR).json())


def test_engineer_cannot_learn_about_hr_documents_by_reuploading(client):
    resp = client.post("/documents", headers=ENGINEER, files={"file": ("copy.md", HR_DOC.encode())})
    assert resp.status_code == 409
    assert "compensation.md" not in resp.text


def test_requests_without_a_valid_key_are_rejected(client):
    assert client.post("/search", json={"query": "deploys"}).status_code == 401
    assert client.post("/search", json={"query": "deploys"}, headers={"X-API-Key": "nope"}).status_code == 401


def test_disabling_demo_keys_revokes_seeded_ones(client):
    from app.auth import revoke_demo_keys, seed_demo_keys

    try:
        assert revoke_demo_keys() == 4
        assert client.get("/documents", headers=ADMIN).status_code == 401
    finally:
        seed_demo_keys()  # restore for any later tests
    assert client.get("/documents", headers=ADMIN).status_code == 200
