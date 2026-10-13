"""Retrieval: vector search, optional keyword search fused with Reciprocal Rank Fusion, optional reranking.

Every Hit keeps its cosine similarity as `score`, whatever the mode. Fusion and reranking only
change the order, so the relevance gate (llm.is_answerable) means the same thing in every mode.
"""

from dataclasses import asdict, dataclass
from typing import Literal

from .config import settings
from .db import get_conn
from .embeddings import embed_query, rerank_scores

Mode = Literal["vector", "hybrid"]


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    document_id: str
    filename: str
    page: int | None
    chunk_index: int
    content: str
    score: float  # cosine similarity, higher is better

    def to_dict(self) -> dict:
        return asdict(self)


_COLUMNS = """c.id, c.document_id, d.filename, c.page, c.chunk_index, c.content,
       1 - (c.embedding <=> %(q)s) AS score"""

_VECTOR_SQL = f"""
SELECT {_COLUMNS}
FROM chunks c
JOIN documents d ON d.id = c.document_id
ORDER BY c.embedding <=> %(q)s
LIMIT %(n)s
"""

# plainto_tsquery ANDs every term, so a full question rarely matches anything. Turn it into an OR
# query instead; ts_rank_cd then ranks chunks that match more (and rarer, closer) terms higher.
_KEYWORD_SQL = f"""
WITH q AS (
    SELECT regexp_replace(plainto_tsquery('english', %(text)s)::text, '&|<\\d*-?>', '|', 'g')::tsquery AS query
)
SELECT {_COLUMNS}
FROM chunks c
JOIN documents d ON d.id = c.document_id
CROSS JOIN q
WHERE c.tsv @@ q.query
ORDER BY ts_rank_cd(c.tsv, q.query) DESC, c.id
LIMIT %(n)s
"""


def rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[int]:
    """Reciprocal Rank Fusion: each id scores sum(1 / (k + rank)) over the rankings it appears in.

    Uses only ranks, so the two retrievers' incomparable scores (cosine vs ts_rank_cd) never need
    normalising. Returns ids best first; ties keep first-seen order, so the first ranking wins them.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda item: -scores[item])


def _fetch(sql: str, params: dict) -> list[Hit]:
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        Hit(
            chunk_id=row[0],
            document_id=str(row[1]),
            filename=row[2],
            page=row[3],
            chunk_index=row[4],
            content=row[5],
            score=round(float(row[6]), 4),
        )
        for row in rows
    ]


def search(query: str, k: int, mode: Mode | None = None, rerank: bool | None = None) -> list[Hit]:
    mode = mode or settings.retrieval_mode
    rerank = settings.rerank if rerank is None else rerank
    query_vector = embed_query(query)
    # Fusion and reranking need a wider candidate pool than the k chunks finally returned.
    pool = max(k, settings.candidate_pool) if mode == "hybrid" or rerank else k

    candidates = _fetch(_VECTOR_SQL, {"q": query_vector, "n": pool})
    if mode == "hybrid":
        keyword = _fetch(_KEYWORD_SQL, {"q": query_vector, "text": query, "n": pool})
        by_id = {h.chunk_id: h for h in candidates + keyword}
        fused = rrf_fuse([[h.chunk_id for h in candidates], [h.chunk_id for h in keyword]], settings.rrf_k)
        candidates = [by_id[i] for i in fused[:pool]]

    if rerank and candidates:
        scores = rerank_scores(query, [f"{h.filename}\n{h.content}" for h in candidates])
        candidates = [h for _, h in sorted(zip(scores, candidates, strict=True), key=lambda p: -p[0])]
    return candidates[:k]
