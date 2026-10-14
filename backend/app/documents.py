"""Indexing documents: extract, chunk, embed, store. Used by the upload endpoint and by startup pre-loading."""

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg

from . import db
from .config import settings
from .embeddings import embed_passages
from .ingest import SUPPORTED_EXTENSIONS, UnreadableFile, UnsupportedFileType, chunk_pages, extract_pages, sha256

log = logging.getLogger("docpilot")


class NoText(ValueError):
    pass


class ConcurrentDuplicate(ValueError):
    pass


@dataclass(frozen=True)
class IndexedDocument:
    id: str
    filename: str
    num_chunks: int
    access_group: str
    duplicate: bool = False


def find_by_hash(digest: str) -> IndexedDocument | None:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT id, filename, num_chunks, access_group FROM documents WHERE sha256 = %s", (digest,)
        ).fetchone()
    return IndexedDocument(str(row[0]), row[1], row[2], row[3], duplicate=True) if row else None


def index_document(filename: str, data: bytes, access_group: str) -> IndexedDocument:
    """Index a file, or return the existing document (duplicate=True) if identical bytes are already indexed.

    The caller decides whether it may see an existing duplicate. Raises UnsupportedFileType,
    UnreadableFile, NoText or ConcurrentDuplicate.
    """
    digest = sha256(data)
    if existing := find_by_hash(digest):
        return existing

    start = time.perf_counter()
    pages = extract_pages(filename, data)
    chunks = chunk_pages(pages, settings.chunk_max_chars, settings.chunk_overlap_chars)
    if not chunks:
        raise NoText("No extractable text found. Scanned PDFs need OCR, which is not supported yet.")

    # Contextual header: prefix each chunk with its filename before embedding,
    # so chunks like "It is 24 days per year" still carry document context.
    vectors = embed_passages([f"{filename}\n{c.content}" for c in chunks])

    try:
        with db.get_conn() as conn, conn.transaction():
            doc_id = conn.execute(
                "INSERT INTO documents (filename, sha256, num_chunks, access_group) VALUES (%s, %s, %s, %s)"
                " RETURNING id",
                (filename, digest, len(chunks), access_group),
            ).fetchone()[0]
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (document_id, chunk_index, page, content, embedding)"
                    " VALUES (%s, %s, %s, %s, %s)",
                    [(doc_id, c.index, c.page, c.content, v) for c, v in zip(chunks, vectors, strict=True)],
                )
    except psycopg.errors.UniqueViolation as exc:
        # The same file was indexed by a concurrent request after our duplicate check.
        raise ConcurrentDuplicate("This file was just indexed by another request. Retry to see it.") from exc

    ms = round((time.perf_counter() - start) * 1000)
    log.info("ingested %s into %s: %d pages, %d chunks in %d ms", filename, access_group, len(pages), len(chunks), ms)
    return IndexedDocument(str(doc_id), filename, len(chunks), access_group)


def preload(directory: str | Path, access_group: str = "all") -> list[IndexedDocument]:
    """Index every supported file in `directory` that isn't indexed yet. Safe to run on every startup:
    files already indexed (same bytes) are skipped. A bad file is logged and skipped, not fatal."""
    results = []
    for path in sorted(Path(directory).iterdir()):
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS or not path.is_file():
            continue
        try:
            results.append(index_document(path.name, path.read_bytes(), access_group))
        except (UnsupportedFileType, UnreadableFile, NoText, ConcurrentDuplicate) as exc:
            log.warning("preload skipped %s: %s", path.name, exc)
    new = sum(not d.duplicate for d in results)
    log.info("preload from %s: %d new, %d already indexed", directory, new, len(results) - new)
    return results
