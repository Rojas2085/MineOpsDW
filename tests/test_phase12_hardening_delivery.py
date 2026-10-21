"""Phase 12 tests: Online backup, restore with consent, disk-full handling, and repo secret scan."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

from mineops_dw.domain import Measurement, MiningSession
from mineops_dw.security_scanner import scan_workspace_for_secrets
from mineops_dw.storage import (
    MineOpsRepository,
    SQLiteDatabase,
    StorageCapacityError,
    create_sqlite_backup,
    restore_sqlite_backup,
    verify_sqlite_integrity,
)


def test_backup_and_restore_with_overwrite_protection(tmp_path: Path) -> None:
    """Verify online SQLite backup, integrity check, overwrite protection, and full restore."""
    src_db_path = tmp_path / "live" / "mineops.sqlite3"
    db = SQLiteDatabase(src_db_path)
    db.apply_migrations()
    repo = MineOpsRepository(db)

    sess = MiningSession(
        id="sim_backup_001",
        started_at_utc="2026-10-21T22:00:00Z",
        session_state="running",
        data_mode="simulated",
    )
    repo.upsert_session(sess)
    repo.insert_measurement(
        Measurement(
            session_id=sess.id,
            metric_name="cpu_percent_total",
            value=31.2,
            unit="%",
            status="simulated",
            source="simulator:bkp",
            observed_at_utc="2026-10-21T22:00:10Z",
        )
    )

    # 1. Create online backup
    backup_path = tmp_path / "backups" / "mineops_backup.sqlite3"
    created = create_sqlite_backup(src_db_path, backup_path)
    assert created.is_file()
    assert verify_sqlite_integrity(created) is True

    # 2. Restore to a clean test path
    restored_path = tmp_path / "restored" / "mineops_restored.sqlite3"
    restore_sqlite_backup(backup_path, restored_path)
    restored_repo = MineOpsRepository(SQLiteDatabase(restored_path))
    loaded_sess = restored_repo.get_session("sim_backup_001")
    assert loaded_sess is not None
    assert len(restored_repo.list_measurements()) == 1

    # 3. Attempting to overwrite an existing database without explicit consent must raise PermissionError
    with pytest.raises(PermissionError, match="Explicit consent"):
        restore_sqlite_backup(backup_path, restored_path, allow_overwrite=False)

    # 4. With allow_overwrite=True, it creates a .pre_restore.bak safety copy and succeeds
    restore_sqlite_backup(backup_path, restored_path, allow_overwrite=True)
    safety_copy = restored_path.with_suffix(restored_path.suffix + ".pre_restore.bak")
    assert safety_copy.is_file()


def test_simulated_disk_full_raises_storage_capacity_error_and_cleans_temp(
    tmp_path: Path,
) -> None:
    """Simulated disk-full during backup must raise StorageCapacityError and leave no corrupt .tmp."""
    src_db_path = tmp_path / "disk_test.sqlite3"
    db = SQLiteDatabase(src_db_path)
    db.apply_migrations()

    dst_backup = tmp_path / "full_disk" / "bkp.sqlite3"

    with patch("mineops_dw.storage.backup.verify_sqlite_integrity") as mock_verify:
        mock_verify.side_effect = sqlite3.OperationalError("database or disk is full")
        with pytest.raises(StorageCapacityError, match="database or disk is full"):
            create_sqlite_backup(src_db_path, dst_backup)

    # Verify temporary file was cleaned up
    assert not dst_backup.with_suffix(".sqlite3.tmp").exists()


def test_repository_secret_scanner_finds_zero_leaks_and_detects_planted_secret(
    tmp_path: Path,
) -> None:
    """Workspace must have 0 leaked secrets, and scanner must catch planted credentials."""
    repo_root = Path(__file__).resolve().parents[1]
    real_findings = scan_workspace_for_secrets(repo_root)
    assert real_findings == []

    # Verify scanner catches a planted secret in a temporary directory
    leaked_env = tmp_path / "bad_config.env"
    leaked_env.write_text(
        "BINANCE_READ_ONLY_API_KEY=real_looking_secret_123456\n",
        encoding="utf-8",
    )
    planted_findings = scan_workspace_for_secrets(tmp_path)
    assert len(planted_findings) == 1
    assert planted_findings[0].rule_name == "populated_binance_credential"
