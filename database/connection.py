from queue import Empty, LifoQueue
from threading import Lock
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - lets local fallback work without psycopg installed.
    psycopg = None
    dict_row = None

from supabase import Client, create_client

from backend.core.config import settings


class PostgresDatabase:
    def __init__(self, database_url: str, max_pool_size: int = 8) -> None:
        self.database_url = database_url
        self.max_pool_size = max_pool_size
        self._pool: LifoQueue[Any] = LifoQueue(maxsize=max_pool_size)
        self._created = 0
        self._lock = Lock()

    def _new_connection(self):
        if psycopg is None or dict_row is None:
            raise RuntimeError("psycopg is required when SUPABASE_DB_URL is configured. Run: pip install psycopg[binary]")
        return psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=15, prepare_threshold=None)

    def _acquire(self):
        while True:
            try:
                connection = self._pool.get_nowait()
                if not connection.closed:
                    return connection
                with self._lock:
                    self._created = max(0, self._created - 1)
            except Empty:
                with self._lock:
                    if self._created < self.max_pool_size:
                        self._created += 1
                        create_new = True
                    else:
                        create_new = False
                if create_new:
                    try:
                        return self._new_connection()
                    except Exception:
                        with self._lock:
                            self._created = max(0, self._created - 1)
                        raise
                connection = self._pool.get(timeout=15)
                if not connection.closed:
                    return connection

    def _release(self, connection, discard: bool = False) -> None:
        if discard or connection.closed:
            try:
                connection.close()
            finally:
                with self._lock:
                    self._created = max(0, self._created - 1)
            return
        try:
            self._pool.put_nowait(connection)
        except Exception:
            try:
                connection.close()
            finally:
                with self._lock:
                    self._created = max(0, self._created - 1)

    def connect(self):
        return PooledPostgresConnection(self)

    def fetch_one(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                return cursor.fetchone()

    def fetch_all(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                return list(cursor.fetchall())

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
            connection.commit()

    def execute_returning(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()
            connection.commit()
            return row


def get_postgres_database() -> PostgresDatabase | None:
    if not settings.postgres_enabled:
        return None
    return PostgresDatabase(settings.supabase_db_url, max_pool_size=settings.postgres_pool_max_size)


class PooledPostgresConnection:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database
        self.connection = None
        self.released = False

    def _ensure_connection(self):
        if self.connection is None:
            self.connection = self.database._acquire()
        return self.connection

    def __enter__(self):
        self._ensure_connection()
        return self

    def __exit__(self, exc_type, _exc, _tb) -> None:
        self.close(discard=exc_type is not None)

    def __getattr__(self, name: str):
        return getattr(self._ensure_connection(), name)

    def close(self, discard: bool = False) -> None:
        if self.released or self.connection is None:
            return
        try:
            if discard:
                self.connection.rollback()
            else:
                self.connection.rollback()
        except Exception:
            discard = True
        self.database._release(self.connection, discard=discard)
        self.released = True
        self.connection = None


def get_supabase_client() -> Client | None:
    if settings.postgres_enabled:
        return None
    if not settings.supabase_enabled:
        return None
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


postgres_db = get_postgres_database()
supabase = get_supabase_client()
