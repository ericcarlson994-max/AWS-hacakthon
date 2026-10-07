from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from dms_core.config import Settings


def configure_connection(connection: psycopg.Connection) -> None:
    register_vector(connection)


class Database:
    def __init__(self, url: str, min_size: int = 1, max_size: int = 10, timeout: float = 10.0) -> None:
        self.url = url
        self.min_size = min_size
        self.max_size = max_size
        self.timeout = timeout
        self._pool: ConnectionPool | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> Database:
        return cls(settings.database_url)

    @property
    def pool(self) -> ConnectionPool:
        if self._pool is None:
            with self._lock:
                if self._pool is None:
                    pool = ConnectionPool(
                        self.url,
                        min_size=self.min_size,
                        max_size=self.max_size,
                        timeout=self.timeout,
                        kwargs={"row_factory": dict_row},
                        configure=configure_connection,
                        open=False,
                    )
                    pool.open(wait=True, timeout=self.timeout)
                    self._pool = pool
        return self._pool

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        with self.pool.connection() as connection:
            yield connection

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None
