"""PostgreSQL connection helpers."""

import os
from contextlib import contextmanager
from urllib.parse import quote_plus

import psycopg2
from psycopg2.extras import RealDictCursor


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if url:
        return url

    host = os.getenv("PG_HOST", "localhost")
    port = os.getenv("PG_PORT", "5432")
    user = os.getenv("PG_USER", "polymarket")
    password = os.getenv("PG_PASSWORD", "polymarket")
    database = os.getenv("PG_DATABASE", "polymarket")
    return (
        f"postgresql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{database}"
    )


@contextmanager
def get_connection():
    conn = psycopg2.connect(get_database_url())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def dict_cursor(conn):
    return conn.cursor(cursor_factory=RealDictCursor)
