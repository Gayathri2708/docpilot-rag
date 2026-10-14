import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from .config import settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
log = logging.getLogger("docpilot")


def _configure(conn: psycopg.Connection) -> None:
    register_vector(conn)
    # Retrieval filters by access group. Plain HNSW search filters *after* the index scan, so a
    # restrictive filter can return fewer than k rows; iterative scans keep going until enough
    # rows pass the filter, in exact distance order. Needs pgvector >= 0.8; older versions still
    # work, with that caveat, rather than failing every connection.
    try:
        conn.execute("SET hnsw.iterative_scan = strict_order")
    except psycopg.Error:
        conn.rollback()
        log.warning("pgvector < 0.8: hnsw.iterative_scan unavailable; filtered searches may return fewer rows")
    conn.commit()


def make_pool(database_url: str) -> ConnectionPool:
    # check: test each connection before handing it out. Serverless Postgres (e.g. Neon) closes idle
    # connections when it scales to zero; without this the first request after a pause would fail.
    return ConnectionPool(
        database_url, min_size=1, max_size=10, configure=_configure, check=ConnectionPool.check_connection, open=False
    )


pool = make_pool(settings.database_url)


def apply_schema() -> None:
    """Create the extension and tables. Runs before the pool opens, because
    register_vector needs the vector type to exist."""
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute(SCHEMA_PATH.read_text())


def open_pool() -> None:
    pool.open(wait=True)


def close_pool() -> None:
    pool.close()


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    with pool.connection() as conn:
        yield conn
