"""SQLite connection manager and versioned migration runner with transactional rollback."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("mineops_dw.storage")

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class MigrationError(RuntimeError):
    """Raised when a database schema migration fails and is rolled back."""


class SQLiteDatabase:
    """Manages SQLite connections in WAL mode and applies versioned SQL migrations."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)

    @property
    def db_path(self) -> Path:
        """Return the configured path to the SQLite database file."""
        return self._db_path

    def connect(self) -> sqlite3.Connection:
        """Open a configured SQLite connection with WAL mode and foreign keys enabled."""
        if str(self._db_path) != ":memory:":
            self._db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(self._db_path), timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        if str(self._db_path) != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        """Provide a transactional connection context that closes cleanly on exit."""
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    def apply_migrations(self, migrations_dir: Path | None = None) -> list[str]:
        """Apply pending .sql migrations in lexical order with transactional rollback on failure."""
        target_dir = migrations_dir or DEFAULT_MIGRATIONS_DIR
        if not target_dir.is_dir():
            raise FileNotFoundError(f"Migrations directory does not exist: {target_dir}")

        migration_files = sorted(target_dir.glob("*.sql"))
        applied_now: list[str] = []

        with self.session() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at_utc TEXT NOT NULL
                );
                """
            )
            rows = conn.execute("SELECT version FROM schema_migrations;").fetchall()
            already_applied = {str(row["version"]) for row in rows}

            for sql_file in migration_files:
                version = sql_file.stem
                if version in already_applied:
                    continue

                sql_script = sql_file.read_text(encoding="utf-8")
                applied_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

                conn.execute("BEGIN IMMEDIATE;")
                try:
                    for statement in _split_sql_statements(sql_script):
                        conn.execute(statement)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, applied_at_utc) VALUES (?, ?);",
                        (version, applied_at),
                    )
                    conn.execute("COMMIT;")
                    applied_now.append(version)
                    logger.info("Applied database migration: %s", version)
                except Exception as exc:
                    conn.execute("ROLLBACK;")
                    logger.error("Failed migration %s; transaction rolled back: %s", version, exc)
                    raise MigrationError(
                        f"Migration '{version}' failed and was rolled back: {exc}"
                    ) from exc

        return applied_now

    def applied_migrations(self) -> list[str]:
        """Return the ordered list of already-applied migration versions."""
        with self.session() as conn:
            table_check = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations';"
            ).fetchone()
            if table_check is None:
                return []
            rows = conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version ASC;"
            ).fetchall()
            return [str(row["version"]) for row in rows]


def _split_sql_statements(sql_script: str) -> list[str]:
    """Split a SQL script into individual executable statements while ignoring pure comments."""
    statements: list[str] = []
    current_lines: list[str] = []

    for line in sql_script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current_lines.append(line)
        candidate = "\n".join(current_lines)
        if sqlite3.complete_statement(candidate):
            statements.append(candidate.strip())
            current_lines.clear()

    if current_lines:
        leftover = "\n".join(current_lines).strip()
        if leftover:
            statements.append(leftover)

    return statements
