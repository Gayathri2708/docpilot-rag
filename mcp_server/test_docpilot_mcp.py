"""The MCP server over the real MCP protocol (in-process client), with the DocPilot HTTP API stubbed."""

import asyncio
import json

import httpx
import pytest
from mcp import Client

import docpilot_mcp


@pytest.fixture
def api(monkeypatch):
    """Fake DocPilot API. Records requests; only 'good-key' is accepted."""
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers.get("X-API-Key") != "good-key":
            return httpx.Response(401, json={"detail": "Missing or invalid API key."})
        if request.url.path == "/ask":
            return httpx.Response(200, json={
                "answer": "Employees get 24 days of paid leave [1].",
                "answered": True,
                "sources": [
                    {"number": 1, "filename": "handbook.md", "page": None, "score": 0.8, "content": "24 days...",
                     "access_group": "all", "cited": True},
                    {"number": 2, "filename": "faq.md", "page": None, "score": 0.6, "content": "Other",
                     "access_group": "all", "cited": False},
                ],
            })
        if request.url.path == "/search":
            return httpx.Response(200, json=[
                {"chunk_id": 1, "document_id": "d1", "filename": "policy.pdf", "page": 3, "chunk_index": 0,
                 "content": "Hotel cap is USD 180.", "score": 0.71, "access_group": "finance"},
            ])
        if request.url.path == "/documents":
            return httpx.Response(200, json=[{"id": "d1", "filename": "policy.pdf", "num_chunks": 11,
                                              "access_group": "finance", "duplicate": False}])
        return httpx.Response(404, json={"detail": "Not found"})

    monkeypatch.setattr(docpilot_mcp, "transport", httpx.MockTransport(handler))
    monkeypatch.setattr(docpilot_mcp, "API_KEY", "good-key")
    return requests


def call(tool: str, arguments: dict | None = None):
    async def go():
        async with Client(docpilot_mcp.mcp) as client:
            return await client.call_tool(tool, arguments or {})

    return asyncio.run(go())


def payload(result):
    if result.structured_content is not None:
        content = result.structured_content
        return content.get("result", content)
    return json.loads(result.content[0].text)


def test_exposes_read_only_tools():
    async def go():
        async with Client(docpilot_mcp.mcp) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in asyncio.run(go())}
    assert set(tools) == {"ask_documents", "search_documents", "list_documents"}
    assert all(t.annotations.read_only_hint for t in tools.values())
    assert tools["ask_documents"].input_schema["required"] == ["question"]


def test_ask_returns_answer_and_only_cited_sources(api):
    result = call("ask_documents", {"question": "How much leave?"})
    assert not result.is_error
    body = payload(result)
    assert body["answer"].startswith("Employees get 24 days")
    assert [s["source"] for s in body["sources"]] == ["handbook.md"]
    assert json.loads(api[0].content) == {"question": "How much leave?", "top_k": 5}


def test_search_formats_hits_with_page(api):
    body = payload(call("search_documents", {"query": "hotel cap", "top_k": 3}))
    assert body == [{"rank": 1, "source": "policy.pdf, page 3", "relevance": 0.71, "access_group": "finance",
                     "content": "Hotel cap is USD 180."}]


def test_list_documents(api):
    assert payload(call("list_documents")) == [{"filename": "policy.pdf", "access_group": "finance", "chunks": 11}]


def test_every_request_carries_the_api_key(api):
    call("search_documents", {"query": "x"})
    call("list_documents")
    assert all(r.headers["X-API-Key"] == "good-key" for r in api)


def test_rejected_key_is_reported_as_tool_error(api, monkeypatch):
    monkeypatch.setattr(docpilot_mcp, "API_KEY", "bad-key")
    result = call("ask_documents", {"question": "q"})
    assert result.is_error
    assert "rejected the API key" in result.content[0].text


def test_missing_key_is_reported_without_calling_the_api(api, monkeypatch):
    monkeypatch.setattr(docpilot_mcp, "API_KEY", "")
    result = call("list_documents")
    assert result.is_error
    assert "DOCPILOT_API_KEY is not set" in result.content[0].text
    assert api == []
