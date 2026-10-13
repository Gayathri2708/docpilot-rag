"""DocPilot MCP server: lets Claude Desktop (or any MCP client) search and question your documents.

It is a thin client of the DocPilot HTTP API, not a second way into the database: every call sends
DOCPILOT_API_KEY, so the key's access groups apply exactly as they do in the web UI.

    DOCPILOT_URL=http://localhost:8000 DOCPILOT_API_KEY=dp_demo_hr python mcp_server/docpilot_mcp.py

Runs over stdio. Built on the official MCP Python SDK's MCPServer (the high-level API formerly
called FastMCP).
"""

import os

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

API_URL = os.getenv("DOCPILOT_URL", "http://localhost:8000")
API_KEY = os.getenv("DOCPILOT_API_KEY", "")
TIMEOUT_SECONDS = 120

mcp = MCPServer(
    "DocPilot",
    instructions=(
        "Search and question the user's indexed company documents (policies, handbooks, product docs). "
        "Use ask_documents for a cited answer, search_documents to read the raw passages, and "
        "list_documents to see what is indexed. Only documents in the API key's access groups are visible."
    ),
)

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

# Tests replace this with an httpx.MockTransport.
transport: httpx.AsyncBaseTransport | None = None


async def _request(method: str, path: str, body: dict | None = None):
    """Call the DocPilot API. Failures raise ToolError, whose message the MCP client (and model) sees;
    any other exception would reach the client only as a generic error."""
    if not API_KEY:
        raise ToolError("DOCPILOT_API_KEY is not set. Add it to the MCP server's env in your client config.")
    async with httpx.AsyncClient(
        base_url=API_URL, headers={"X-API-Key": API_KEY}, timeout=TIMEOUT_SECONDS, transport=transport
    ) as client:
        try:
            resp = await client.request(method, path, json=body)
        except httpx.TransportError as exc:
            raise ToolError(f"Cannot reach DocPilot at {API_URL}. Is the API running? ({exc})") from exc
    if resp.status_code == 401:
        raise ToolError("DocPilot rejected the API key. Check DOCPILOT_API_KEY.")
    if resp.is_error:
        detail = resp.json().get("detail", resp.text) if "json" in resp.headers.get("content-type", "") else resp.text
        raise ToolError(f"DocPilot returned HTTP {resp.status_code}: {detail}")
    return resp.json()


def _location(item: dict) -> str:
    return f"{item['filename']}, page {item['page']}" if item.get("page") else item["filename"]


@mcp.tool(annotations=READ_ONLY)
async def ask_documents(question: str, top_k: int = 5) -> dict:
    """Answer a question from the indexed documents, with numbered citations.

    Returns the answer, whether it was answered (False means the documents don't contain it, and
    nothing was made up), and the sources the answer cites.
    """
    data = await _request("POST", "/ask", {"question": question, "top_k": top_k})
    return {
        "answer": data["answer"],
        "answered": data["answered"],
        "sources": [
            {"number": s["number"], "source": _location(s), "cited": s["cited"], "excerpt": s["content"][:500]}
            for s in data["sources"]
            if s["cited"] or not data["answered"]
        ],
    }


@mcp.tool(annotations=READ_ONLY)
async def search_documents(query: str, top_k: int = 5) -> list[dict]:
    """Find the passages most relevant to a query (hybrid keyword + semantic search), without an LLM answer."""
    hits = await _request("POST", "/search", {"query": query, "top_k": top_k})
    return [
        {"rank": i, "source": _location(h), "relevance": h["score"], "access_group": h["access_group"],
         "content": h["content"]}
        for i, h in enumerate(hits, start=1)
    ]


@mcp.tool(annotations=READ_ONLY)
async def list_documents() -> list[dict]:
    """List the documents this API key can see."""
    docs = await _request("GET", "/documents")
    return [{"filename": d["filename"], "access_group": d["access_group"], "chunks": d["num_chunks"]} for d in docs]


if __name__ == "__main__":
    mcp.run()
