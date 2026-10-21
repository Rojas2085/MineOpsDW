"""Idempotent, parameterized SQLite repositories for MineOps DW domain entities."""

from __future__ import annotations

import sqlite3

from mineops_dw.domain.models import (
    Measurement,
    MiningSession,
    PaymentEvent,
    PeriodicReport,
    PoolShare,
    PriceSnapshot,
    RewardSnapshot,
)
from mineops_dw.storage.database import SQLiteDatabase


class MineOpsRepository:
    """Provides parameterized CRUD and idempotent persistence over SQLiteDatabase."""

    def __init__(self, db: SQLiteDatabase) -> None:
        self._db = db

    # --- MiningSession ---

    def upsert_session(self, session: MiningSession) -> None:
        """Insert or update a mining session."""
        with self._db.session() as conn:
            conn.execute(
                """
                INSERT INTO mining_sessions (
                    id, started_at_utc, ended_at_utc, session_state,
                    data_mode, miner_name, pool_name, stop_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    ended_at_utc = excluded.ended_at_utc,
                    session_state = excluded.session_state,
                    stop_reason = excluded.stop_reason;
                """,
                (
                    session.id,
                    session.started_at_utc,
                    session.ended_at_utc,
                    session.session_state,
                    session.data_mode,
                    session.miner_name,
                    session.pool_name,
                    session.stop_reason,
                ),
            )

    def get_session(self, session_id: str) -> MiningSession | None:
        """Retrieve a mining session by id."""
        with self._db.session() as conn:
            row = conn.execute(
                "SELECT * FROM mining_sessions WHERE id = ?;",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return MiningSession(
                id=row["id"],
                started_at_utc=row["started_at_utc"],
                ended_at_utc=row["ended_at_utc"],
                session_state=row["session_state"],
                data_mode=row["data_mode"],
                miner_name=row["miner_name"],
                pool_name=row["pool_name"],
                stop_reason=row["stop_reason"],
            )

    # --- Measurement ---

    def insert_measurement(self, measurement: Measurement) -> int | None:
        """Insert a measurement idempotently by (metric_name, source, observed_at_utc)."""
        with self._db.session() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO measurements (
                    session_id, metric_name, value, unit, status,
                    source, observed_at_utc, quality_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    measurement.session_id,
                    measurement.metric_name,
                    measurement.value,
                    measurement.unit,
                    measurement.status,
                    measurement.source,
                    measurement.observed_at_utc,
                    measurement.quality_note,
                ),
            )
            if cursor.rowcount == 0:
                return None
            return int(cursor.lastrowid) if cursor.lastrowid is not None else None

    def list_measurements(
        self,
        metric_name: str | None = None,
        limit: int = 100,
    ) -> list[Measurement]:
        """List stored measurements ordered by observed_at_utc ascending."""
        with self._db.session() as conn:
            if metric_name is not None:
                rows = conn.execute(
                    """
                    SELECT * FROM measurements
                    WHERE metric_name = ?
                    ORDER BY observed_at_utc ASC, id ASC
                    LIMIT ?;
                    """,
                    (metric_name, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM measurements
                    ORDER BY observed_at_utc ASC, id ASC
                    LIMIT ?;
                    """,
                    (limit,),
                ).fetchall()
            return [_row_to_measurement(row) for row in rows]

    # --- PoolShare ---

    def insert_pool_share(self, share: PoolShare) -> bool:
        """Insert a pool share idempotently by primary key id. Returns True if newly inserted."""
        with self._db.session() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO pool_shares (
                    id, session_id, accepted, difficulty, reject_reason,
                    status, source, observed_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    share.id,
                    share.session_id,
                    1 if share.accepted else 0,
                    share.difficulty,
                    share.reject_reason,
                    share.status,
                    share.source,
                    share.observed_at_utc,
                ),
            )
            return cursor.rowcount > 0

    def list_pool_shares(self, session_id: str) -> list[PoolShare]:
        """Return all shares for a given session ordered by timestamp."""
        with self._db.session() as conn:
            rows = conn.execute(
                """
                SELECT * FROM pool_shares
                WHERE session_id = ?
                ORDER BY observed_at_utc ASC, id ASC;
                """,
                (session_id,),
            ).fetchall()
            return [
                PoolShare(
                    id=row["id"],
                    session_id=row["session_id"],
                    accepted=bool(row["accepted"]),
                    difficulty=row["difficulty"],
                    reject_reason=row["reject_reason"],
                    status=row["status"],
                    source=row["source"],
                    observed_at_utc=row["observed_at_utc"],
                )
                for row in rows
            ]

    # --- RewardSnapshot ---

    def insert_reward_snapshot(self, reward: RewardSnapshot) -> bool:
        """Insert a reward snapshot idempotently by id."""
        with self._db.session() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO reward_snapshots (
                    id, session_id, amount_btc, reward_stage,
                    status, source, observed_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    reward.id,
                    reward.session_id,
                    reward.amount_btc,
                    reward.reward_stage,
                    reward.status,
                    reward.source,
                    reward.observed_at_utc,
                ),
            )
            return cursor.rowcount > 0

    def list_reward_snapshots(
        self,
        reward_stage: str | None = None,
    ) -> list[RewardSnapshot]:
        """List reward snapshots, optionally filtered by reward_stage."""
        with self._db.session() as conn:
            if reward_stage is not None:
                rows = conn.execute(
                    """
                    SELECT * FROM reward_snapshots
                    WHERE reward_stage = ?
                    ORDER BY observed_at_utc ASC;
                    """,
                    (reward_stage,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM reward_snapshots ORDER BY observed_at_utc ASC;"
                ).fetchall()
            return [
                RewardSnapshot(
                    id=row["id"],
                    session_id=row["session_id"],
                    amount_btc=row["amount_btc"],
                    reward_stage=row["reward_stage"],
                    status=row["status"],
                    source=row["source"],
                    observed_at_utc=row["observed_at_utc"],
                )
                for row in rows
            ]

    # --- PriceSnapshot ---

    def insert_price_snapshot(self, snapshot: PriceSnapshot) -> bool:
        """Insert a price snapshot idempotently."""
        with self._db.session() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO price_snapshots (
                    id, asset, quote_asset, price, status, source, observed_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    snapshot.id,
                    snapshot.asset,
                    snapshot.quote_asset,
                    snapshot.price,
                    snapshot.status,
                    snapshot.source,
                    snapshot.observed_at_utc,
                ),
            )
            return cursor.rowcount > 0

    def list_price_snapshots(self, quote_asset: str = "USD") -> list[PriceSnapshot]:
        """List price snapshots for a quote asset ordered by timestamp."""
        with self._db.session() as conn:
            rows = conn.execute(
                """
                SELECT * FROM price_snapshots
                WHERE quote_asset = ?
                ORDER BY observed_at_utc ASC;
                """,
                (quote_asset,),
            ).fetchall()
            return [
                PriceSnapshot(
                    id=row["id"],
                    asset=row["asset"],
                    quote_asset=row["quote_asset"],
                    price=row["price"],
                    status=row["status"],
                    source=row["source"],
                    observed_at_utc=row["observed_at_utc"],
                )
                for row in rows
            ]

    # --- PaymentEvent ---

    def insert_payment_event(self, event: PaymentEvent) -> bool:
        """Insert a payment/deposit event idempotently by id."""
        with self._db.session() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO payment_events (
                    id, event_type, asset, amount, network_fee,
                    settlement_status, data_status, source, external_reference, observed_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    event.id,
                    event.event_type,
                    event.asset,
                    event.amount,
                    event.network_fee,
                    event.settlement_status,
                    event.data_status,
                    event.source,
                    event.external_reference,
                    event.observed_at_utc,
                ),
            )
            return cursor.rowcount > 0

    def list_payment_events(self, event_type: str | None = None) -> list[PaymentEvent]:
        """List payment events ordered by timestamp, optionally filtered by event_type."""
        with self._db.session() as conn:
            if event_type is not None:
                rows = conn.execute(
                    """
                    SELECT * FROM payment_events
                    WHERE event_type = ?
                    ORDER BY observed_at_utc ASC;
                    """,
                    (event_type,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM payment_events ORDER BY observed_at_utc ASC;"
                ).fetchall()
            return [
                PaymentEvent(
                    id=row["id"],
                    event_type=row["event_type"],
                    asset=row["asset"],
                    amount=row["amount"],
                    network_fee=row["network_fee"],
                    settlement_status=row["settlement_status"],
                    data_status=row["data_status"],
                    source=row["source"],
                    external_reference=row["external_reference"],
                    observed_at_utc=row["observed_at_utc"],
                )
                for row in rows
            ]

    # --- PeriodicReport ---

    def insert_periodic_report(self, report: PeriodicReport) -> bool:
        """Insert a 30-minute periodic report idempotently by id or window tuple."""
        with self._db.session() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO periodic_reports (
                    id, window_start_utc, window_end_utc, data_mode,
                    sample_coverage_pct, gaps_count, summary_json, generated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    report.id,
                    report.window_start_utc,
                    report.window_end_utc,
                    report.data_mode,
                    report.sample_coverage_pct,
                    report.gaps_count,
                    report.summary_json,
                    report.generated_at_utc,
                ),
            )
            return cursor.rowcount > 0

    def list_periodic_reports(self, data_mode: str | None = None) -> list[PeriodicReport]:
        """List periodic reports ordered by window_start_utc."""
        with self._db.session() as conn:
            if data_mode is not None:
                rows = conn.execute(
                    """
                    SELECT * FROM periodic_reports
                    WHERE data_mode = ?
                    ORDER BY window_start_utc ASC;
                    """,
                    (data_mode,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM periodic_reports ORDER BY window_start_utc ASC;"
                ).fetchall()
            return [
                PeriodicReport(
                    id=row["id"],
                    window_start_utc=row["window_start_utc"],
                    window_end_utc=row["window_end_utc"],
                    data_mode=row["data_mode"],
                    sample_coverage_pct=row["sample_coverage_pct"],
                    gaps_count=row["gaps_count"],
                    summary_json=row["summary_json"],
                    generated_at_utc=row["generated_at_utc"],
                )
                for row in rows
            ]


def _row_to_measurement(row: sqlite3.Row) -> Measurement:
    return Measurement(
        id=row["id"],
        session_id=row["session_id"],
        metric_name=row["metric_name"],
        value=row["value"],
        unit=row["unit"],
        status=row["status"],
        source=row["source"],
        observed_at_utc=row["observed_at_utc"],
        quality_note=row["quality_note"],
    )
