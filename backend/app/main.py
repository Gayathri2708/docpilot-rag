import json
import logging
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import openai
from fastapi import Depends, FastAPI, Form, HTTPException, Response, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, llm
from .auth import ACCESS_GROUPS, Principal, require_principal, seed_demo_keys
from .config import settings
from .embeddings import embed_passages
from .ingest import UnsupportedFileType, chunk_pages, extract_pages, sha256
from .retrieval import Hit, Mode, search

log = logging.getLogger("docpilot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.apply_schema()
    db.open_pool()
    if settings.seed_demo_keys:
        seed_demo_keys()
    yield
    db.close_pool()


app = FastAPI(title="DocPilot", version="0.1.0", lifespan=lifespan)
app.mount("/ui", StaticFiles(directory=Path(__file__).with_name("static"), html=True), name="ui")


# ---------- Schemas ----------

class DocumentOut(BaseModel):
    id: str
    filename: str
    num_chunks: int
    access_group: str = "all"
    duplicate: bool = False


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=settings.top_k, ge=1, le=20)
    mode: Mode | None = Field(default=None, description="vector or hybrid; defaults to RETRIEVAL_MODE")
    rerank: bool | None = Field(default=None, description="cross-encoder reranking; defaults to RERANK")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=settings.top_k, ge=1, le=20)
    mode: Mode | None = Field(default=None, description="vector or hybrid; defaults to RETRIEVAL_MODE")
    rerank: bool | None = Field(default=None, description="cross-encoder reranking; defaults to RERANK")


class Source(BaseModel):
    number: int
    filename: str
    page: int | None
    score: float
    content: str
    access_group: str
    cited: bool


class AskResponse(BaseModel):
    answer: str
    answered: bool
    sources: list[Source]
    timings_ms: dict[str, int]


def _sources(hits: list[Hit], cited: list[int]) -> list[Source]:
    return [
        Source(
            number=i,
            filename=h.filename,
            page=h.page,
            score=h.score,
            content=h.content,
            access_group=h.access_group,
            cited=i in cited,
        )
        for i, h in enumerate(hits, start=1)
    ]


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


# ---------- Routes ----------

@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/ui/")


@app.get("/health")
def health() -> dict:
    with db.get_conn() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "llm_configured": bool(settings.llm_api_key)}


Caller = Depends(require_principal)


@app.post("/documents", response_model=DocumentOut, status_code=201)
def upload_document(
    file: UploadFile,
    response: Response,
    access_group: str = Form("all", description=f"one of {', '.join(ACCESS_GROUPS)}"),
    principal: Principal = Caller,
) -> DocumentOut:
    if access_group not in ACCESS_GROUPS:
        raise HTTPException(422, f"access_group must be one of {', '.join(ACCESS_GROUPS)}.")
    if not principal.can_access(access_group):
        raise HTTPException(403, f"This API key cannot write to the {access_group!r} group.")
    filename = file.filename or "upload"
    data = file.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB.")
    if not data:
        raise HTTPException(422, "File is empty.")

    digest = sha256(data)
    with db.get_conn() as conn:
        existing = conn.execute(
            "SELECT id, filename, num_chunks, access_group FROM documents WHERE sha256 = %s", (digest,)
        ).fetchone()
    if existing:
        if not principal.can_access(existing[3]):  # don't reveal a document the caller can't read
            raise HTTPException(409, "This file is already indexed in an access group this key cannot read.")
        response.status_code = 200
        return DocumentOut(
            id=str(existing[0]), filename=existing[1], num_chunks=existing[2], access_group=existing[3], duplicate=True
        )

    start = time.perf_counter()
    try:
        pages = extract_pages(filename, data)
    except UnsupportedFileType as exc:
        raise HTTPException(415, str(exc)) from exc
    chunks = chunk_pages(pages, settings.chunk_max_chars, settings.chunk_overlap_chars)
    if not chunks:
        raise HTTPException(422, "No extractable text found. Scanned PDFs need OCR, which is not supported yet.")

    # Contextual header: prefix each chunk with its filename before embedding,
    # so chunks like "It is 24 days per year" still carry document context.
    vectors = embed_passages([f"{filename}\n{c.content}" for c in chunks])

    with db.get_conn() as conn, conn.transaction():
        doc_id = conn.execute(
            "INSERT INTO documents (filename, sha256, num_chunks, access_group) VALUES (%s, %s, %s, %s) RETURNING id",
            (filename, digest, len(chunks), access_group),
        ).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (document_id, chunk_index, page, content, embedding) VALUES (%s, %s, %s, %s, %s)",
                [(doc_id, c.index, c.page, c.content, v) for c, v in zip(chunks, vectors, strict=True)],
            )

    log.info(
        "ingested %s into %s: %d pages, %d chunks in %d ms", filename, access_group, len(pages), len(chunks), _ms(start)
    )
    return DocumentOut(id=str(doc_id), filename=filename, num_chunks=len(chunks), access_group=access_group)


@app.get("/documents", response_model=list[DocumentOut])
def list_documents(principal: Principal = Caller) -> list[DocumentOut]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, filename, num_chunks, access_group FROM documents"
            " WHERE access_group = ANY(%s) ORDER BY created_at DESC",
            (list(principal.groups),),
        ).fetchall()
    return [DocumentOut(id=str(r[0]), filename=r[1], num_chunks=r[2], access_group=r[3]) for r in rows]


@app.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, principal: Principal = Caller) -> Response:
    with db.get_conn() as conn:
        # Documents outside the caller's groups are reported as not found, not as forbidden.
        deleted = conn.execute(
            "DELETE FROM documents WHERE id::text = %s AND access_group = ANY(%s) RETURNING id",
            (document_id, list(principal.groups)),
        ).fetchone()
    if not deleted:
        raise HTTPException(404, "Document not found.")
    return Response(status_code=204)


@app.post("/search")
def search_chunks(req: SearchRequest, principal: Principal = Caller) -> list[dict]:
    """Retrieval only, no LLM. Used by the eval harness to measure retrieval quality."""
    return [h.to_dict() for h in search(req.query, req.top_k, principal.groups, req.mode, req.rerank)]


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, principal: Principal = Caller) -> AskResponse:
    t0 = time.perf_counter()
    hits = search(req.question, req.top_k, principal.groups, req.mode, req.rerank)
    timings = {"retrieval": _ms(t0)}

    if not llm.is_answerable(hits, settings.min_relevance):
        timings["total"] = _ms(t0)
        return AskResponse(answer=llm.REFUSAL, answered=False, sources=_sources(hits, []), timings_ms=timings)

    t1 = time.perf_counter()
    try:
        answer = llm.complete(llm.build_messages(req.question, hits))
    except llm.LLMNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except openai.APIError as exc:  # provider failure (bad model, rate limit, outage): report it, don't 500
        log.warning("generation failed: %s", exc)
        raise HTTPException(502, f"LLM provider error: {exc}") from exc
    timings["generation"] = _ms(t1)
    timings["total"] = _ms(t0)

    cited = llm.cited_indices(answer, len(hits))
    answered = llm.REFUSAL.lower().rstrip(".") not in answer.lower()
    return AskResponse(answer=answer, answered=answered, sources=_sources(hits, cited), timings_ms=timings)


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@app.post("/ask/stream")
def ask_stream(req: AskRequest, principal: Principal = Caller) -> StreamingResponse:
    """Server-Sent Events: `sources` first, then `token` events, then `done` (or `error`)."""

    def events() -> Iterator[str]:
        t0 = time.perf_counter()
        hits = search(req.question, req.top_k, principal.groups, req.mode, req.rerank)
        yield _sse("sources", {"sources": [s.model_dump() for s in _sources(hits, [])]})

        if not llm.is_answerable(hits, settings.min_relevance):
            yield _sse("token", {"text": llm.REFUSAL})
            yield _sse("done", {"answered": False, "cited": [], "total_ms": _ms(t0)})
            return

        answer = ""
        try:
            for text in llm.stream(llm.build_messages(req.question, hits)):
                answer += text
                yield _sse("token", {"text": text})
        except Exception as exc:  # surface the failure to the client instead of a silent cut-off
            log.exception("generation failed")
            yield _sse("error", {"message": str(exc)})
            return

        yield _sse("done", {"answered": True, "cited": llm.cited_indices(answer, len(hits)), "total_ms": _ms(t0)})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
