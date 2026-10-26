"""Forward-only migration runner using ``PRAGMA user_version`` (spec §9.6)."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings, get_settings
from app.db.connection import connect, has_json1

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def discover() -> list[tuple[int, Path]]:
    """Return ``[(version, path), …]`` sorted ascending by numeric prefix."""
    found: list[tuple[int, Path]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        prefix = path.name.split("_", 1)[0]
        if not prefix.isdigit():
            raise RuntimeError(f"Migration file has no numeric prefix: {path.name}")
        found.append((int(prefix), path))
    return sorted(found)


def current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def backup(settings: Settings, conn: sqlite3.Connection, version: int) -> Path | None:
    """Copy the DB via the backup API (WAL-safe) before a migration."""
    if not settings.DATABASE_PATH.exists() or current_version(conn) == 0:
        return None
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = settings.backup_dir / f"pre_migrate_{stamp}_v{version}.db"
    dest = sqlite3.connect(str(target))
    try:
        conn.backup(dest)
    finally:
        dest.close()
    return target


def upgrade(settings: Settings | None = None, *, quiet: bool = False) -> int:
    """Apply every pending migration. Returns the resulting schema version."""
    settings = settings or get_settings()
    conn = connect(settings.DATABASE_PATH)
    try:
        if not has_json1(conn):
            raise RuntimeError("SQLite build lacks JSON1; CHECK (json_valid(...)) cannot work.")

        version = current_version(conn)
        migrations = discover()
        highest = migrations[-1][0] if migrations else 0

        if version > highest:
            from app.errors import db_schema_too_new

            raise db_schema_too_new(version, highest)

        pending = [(v, p) for v, p in migrations if v > version]
        if pending:
            saved = backup(settings, conn, version)
            if saved and not quiet:
                print(f"Backed up database to {saved}")

        for target_version, path in pending:
            sql = path.read_text(encoding="utf-8")
            try:
                conn.executescript(
                    "BEGIN IMMEDIATE;\n" + sql + f"\nPRAGMA user_version = {target_version};\nCOMMIT;"
                )
            except Exception:
                conn.execute("ROLLBACK") if conn.in_transaction else None
                raise
            if not quiet:
                print(f"Applied {path.name} (schema version {target_version})")

        conn.execute(
            "INSERT INTO app_meta (key, value) VALUES ('schema_applied_at', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_utc_now(),),
        )
        return current_version(conn)
    finally:
        conn.close()


def status(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    conn = connect(settings.DATABASE_PATH)
    try:
        version = current_version(conn)
        migrations = discover()
        highest = migrations[-1][0] if migrations else 0
        pending = [p.name for v, p in migrations if v > version]
        size = settings.DATABASE_PATH.stat().st_size if settings.DATABASE_PATH.exists() else 0
        print(f"Database : {settings.DATABASE_PATH}")
        print(f"Version  : {version} (supported: {highest})")
        print(f"Pending  : {', '.join(pending) if pending else 'none'}")
        print(f"Size     : {size / 1024:.1f} KB")
    finally:
        conn.close()


def make_backup(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    conn = connect(settings.DATABASE_PATH)
    try:
        saved = backup(settings, conn, current_version(conn))
        print(f"Backup written to {saved}" if saved else "Nothing to back up yet.")
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.db.migrate")
    parser.add_argument("command", choices=["upgrade", "status", "backup"], nargs="?", default="status")
    args = parser.parse_args(argv)

    if args.command == "upgrade":
        version = upgrade()
        print(f"Schema is at version {version}.")
    elif args.command == "status":
        status()
    else:
        make_backup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
