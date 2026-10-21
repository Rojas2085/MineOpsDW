"""Online SQLite backup, integrity-checked restore, and disk-full resilience for MineOps DW."""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
import sqlite3

logger = logging.getLogger("mineops_dw.storage.backup")


class StorageCapacityError(RuntimeError):
    """Raised when disk space is exhausted or an I/O write fails during storage/backup."""


def create_sqlite_backup(source_db_path: Path | str, backup_file_path: Path | str) -> Path:
    """Create a consistent online backup of a SQLite database using the native backup API."""
    src_path = Path(source_db_path)
    dst_path = Path(backup_file_path)

    if not src_path.is_file():
        raise FileNotFoundError(f"Source SQLite database does not exist: {src_path}")

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dst = dst_path.with_suffix(dst_path.suffix + ".tmp")

    src_conn: sqlite3.Connection | None = None
    dst_conn: sqlite3.Connection | None = None
    try:
        src_conn = sqlite3.connect(str(src_path), timeout=5.0)
        dst_conn = sqlite3.connect(str(temp_dst), timeout=5.0)
        src_conn.backup(dst_conn)
        dst_conn.close()
        dst_conn = None
        src_conn.close()
        src_conn = None

        verify_sqlite_integrity(temp_dst)
        temp_dst.replace(dst_path)
        logger.info("Created verified SQLite backup at %s", dst_path)
        return dst_path
    except (sqlite3.OperationalError, OSError) as exc:
        if dst_conn is not None:
            dst_conn.close()
        if src_conn is not None:
            src_conn.close()
        if temp_dst.exists():
            temp_dst.unlink(missing_ok=True)
        logger.error("SQLite backup failed due to storage/IO error: %s", exc)
        raise StorageCapacityError(f"Failed to create SQLite backup: {exc}") from exc


def restore_sqlite_backup(
    backup_file_path: Path | str,
    target_db_path: Path | str,
    *,
    allow_overwrite: bool = False,
) -> Path:
    """Restore a verified SQLite backup to target_db_path.

    Never overwrites an existing database unless `allow_overwrite=True`, and creates
    a `.pre_restore.bak` safety copy before replacing an existing file.
    """
    bkp_path = Path(backup_file_path)
    tgt_path = Path(target_db_path)

    if not bkp_path.is_file():
        raise FileNotFoundError(f"Backup file does not exist: {bkp_path}")

    verify_sqlite_integrity(bkp_path)

    if tgt_path.exists():
        if not allow_overwrite:
            raise PermissionError(
                f"Target database '{tgt_path}' already exists. "
                "Explicit consent (allow_overwrite=True) is required before overwriting."
            )
        pre_restore_copy = tgt_path.with_suffix(tgt_path.suffix + ".pre_restore.bak")
        shutil.copy2(tgt_path, pre_restore_copy)
        logger.info("Created pre-restore safety backup at %s", pre_restore_copy)

    tgt_path.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(str(bkp_path), timeout=5.0)
    dst_conn = sqlite3.connect(str(tgt_path), timeout=5.0)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    verify_sqlite_integrity(tgt_path)
    logger.info("Restored SQLite database from %s to %s", bkp_path, tgt_path)
    return tgt_path


def verify_sqlite_integrity(db_path: Path | str) -> bool:
    """Run PRAGMA integrity_check on a SQLite file and raise ValueError if corrupted."""
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        row = conn.execute("PRAGMA integrity_check;").fetchone()
        if row is None or str(row[0]).lower() != "ok":
            raise ValueError(f"SQLite integrity check failed for {db_path}: {row}")
        return True
    finally:
        conn.close()
