from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from backend.core.config import settings

try:
    import psycopg
except ImportError:  # pragma: no cover - reported clearly at runtime.
    psycopg = None


DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
MIGRATIONS_TABLE_SQL = """
create table if not exists public.schema_migrations (
  version text primary key,
  checksum text not null,
  applied_at timestamptz not null default now()
);
"""


def migrations_table_exists(connection) -> bool:
    row = connection.execute("select to_regclass('public.schema_migrations')").fetchone()
    return bool(row and row[0])


def migration_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iter_migration_files(migrations_dir: Path) -> list[Path]:
    files = []
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.name.startswith("000_"):
            continue
        files.append(path)
    return files


def load_applied_migrations(connection) -> dict[str, str]:
    connection.execute(MIGRATIONS_TABLE_SQL)
    rows = connection.execute("select version, checksum from public.schema_migrations").fetchall()
    return {row[0]: row[1] for row in rows}


def inspect_applied_migrations(connection) -> dict[str, str]:
    if not migrations_table_exists(connection):
        return {}
    rows = connection.execute("select version, checksum from public.schema_migrations").fetchall()
    return {row[0]: row[1] for row in rows}


def pending_migrations(migration_files: list[Path], applied: dict[str, str]) -> list[Path]:
    pending = []
    for path in migration_files:
        checksum = migration_checksum(path)
        applied_checksum = applied.get(path.name)
        if applied_checksum is None:
            pending.append(path)
            continue
        if applied_checksum != checksum:
            raise RuntimeError(
                f"Migration checksum mismatch for {path.name}. "
                "Create a new migration instead of editing an applied one."
            )
    return pending


def apply_migration(connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    checksum = migration_checksum(path)
    with connection.transaction():
        connection.execute(sql)
        connection.execute(
            "insert into public.schema_migrations (version, checksum) values (%s, %s)",
            (path.name, checksum),
        )


def run_migrations(migrations_dir: Path = DEFAULT_MIGRATIONS_DIR, dry_run: bool = False) -> list[str]:
    if psycopg is None:
        raise RuntimeError("psycopg is required. Run: pip install psycopg[binary]")
    if not settings.supabase_db_url:
        raise RuntimeError("SUPABASE_DB_URL is required")

    migration_files = iter_migration_files(migrations_dir)
    with psycopg.connect(settings.supabase_db_url) as connection:
        applied = inspect_applied_migrations(connection) if dry_run else load_applied_migrations(connection)
        pending = pending_migrations(migration_files, applied)
        if dry_run:
            return [path.name for path in pending]
        for path in pending:
            apply_migration(connection, path)
        return [path.name for path in pending]


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply SQL migrations recorded in public.schema_migrations.")
    parser.add_argument("--dry-run", action="store_true", help="Print pending migrations without applying them.")
    parser.add_argument(
        "--migrations-dir",
        default=str(DEFAULT_MIGRATIONS_DIR),
        help="Directory containing ordered .sql migration files.",
    )
    args = parser.parse_args()

    applied = run_migrations(Path(args.migrations_dir), dry_run=args.dry_run)
    if args.dry_run:
        print("pending_migrations:", applied)
    else:
        print("applied_migrations:", applied)


if __name__ == "__main__":
    main()
