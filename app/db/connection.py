"""Connection factory and transaction helpers (spec §9.2).

Rules enforced here:
  * WAL, foreign keys, busy timeout on every connection.
  * ``isolation_level=None`` so transactions are explicit.
  * Writes use ``BEGIN IMMEDIATE`` to avoid upgrade deadlocks.
  * A connection is never held across an ``await``; callers open, use, close.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA temp_store = MEMORY",
)


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a connection with the project's standard pragmas."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path),
        timeout=5.0,
        isolation_level=None,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS:
        try:
            conn.execute(pragma)
        except sqlite3.OperationalError:
            # journal_mode cannot change on an in-memory DB; everything else matters.
            if "journal_mode" not in pragma:
                raise
    return conn


@contextmanager
def read_txn(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN")
    try:
        yield conn
    finally:
        conn.execute("COMMIT")


@contextmanager
def write_txn(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def has_json1(conn: sqlite3.Connection) -> bool:
    """CHECK (json_valid(...)) needs JSON1; assert it rather than fail later (R-21)."""
    try:
        conn.execute("SELECT json_valid('{}')").fetchone()
        return True
    except sqlite3.OperationalError:
        return False


class _Connection:
    """Closes the underlying connection when the ``with`` block exits.

    ``sqlite3.Connection`` itself only ends the transaction on ``__exit__``; the call
    sites read as "open, use, close", so the factory returns this wrapper.
    """

    __slots__ = ("_conn",)

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __getattr__(self, name: str):
        return getattr(self._conn, name)

    def __enter__(self) -> sqlite3.Connection:
        return self._conn

    def __exit__(self, *exc_info) -> None:
        self._conn.close()


def connector(db_path: Path | str):
    """Return a zero-argument factory used by services that need ad-hoc connections.

    Every caller gets its own short-lived connection, which is what keeps connections
    from being held across an ``await`` (§9.2).
    """

    def open_connection() -> _Connection:
        return _Connection(connect(db_path))

    return open_connection
