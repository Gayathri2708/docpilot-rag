from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from .config import settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

pool = ConnectionPool(
    settings.database_url,
    min_size=1,
    max_size=10,
    configure=register_vector,
    open=False,
)


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
