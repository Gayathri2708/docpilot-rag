from dataclasses import asdict, dataclass

from .db import get_conn
from .embeddings import embed_query


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


_SEARCH_SQL = """
SELECT c.id, c.document_id, d.filename, c.page, c.chunk_index, c.content,
       1 - (c.embedding <=> %(q)s) AS score
FROM chunks c
JOIN documents d ON d.id = c.document_id
ORDER BY c.embedding <=> %(q)s
LIMIT %(k)s
"""


def search(query: str, k: int) -> list[Hit]:
    query_vector = embed_query(query)
    with get_conn() as conn:
        rows = conn.execute(_SEARCH_SQL, {"q": query_vector, "k": k}).fetchall()
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
