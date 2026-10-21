-- 0001_initial_schema.sql
-- Initial analytical and operational schema for MineOps DW (SQLite)

CREATE TABLE IF NOT EXISTS mining_sessions (
    id TEXT PRIMARY KEY,
    started_at_utc TEXT NOT NULL,
    ended_at_utc TEXT NULL,
    session_state TEXT NOT NULL CHECK (session_state IN ('idle', 'running', 'paused', 'stopped', 'error')),
    data_mode TEXT NOT NULL CHECK (data_mode IN ('simulated', 'real')),
    miner_name TEXT NULL,
    pool_name TEXT NULL,
    stop_reason TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_mining_sessions_started_at
    ON mining_sessions (started_at_utc);

CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NULL REFERENCES mining_sessions(id) ON DELETE SET NULL,
    metric_name TEXT NOT NULL,
    value REAL NULL,
    unit TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('measured', 'estimated', 'unavailable', 'simulated')),
    source TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL,
    quality_note TEXT NULL,
    CHECK (
        (status = 'unavailable' AND value IS NULL AND quality_note IS NOT NULL)
        OR (status != 'unavailable' AND value IS NOT NULL)
    ),
    UNIQUE (metric_name, source, observed_at_utc)
);

CREATE INDEX IF NOT EXISTS idx_measurements_metric_time
    ON measurements (metric_name, observed_at_utc);

CREATE TABLE IF NOT EXISTS pool_shares (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES mining_sessions(id) ON DELETE CASCADE,
    accepted INTEGER NOT NULL CHECK (accepted IN (0, 1)),
    difficulty REAL NULL,
    reject_reason TEXT NULL,
    status TEXT NOT NULL CHECK (status IN ('measured', 'simulated')),
    source TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pool_shares_session_time
    ON pool_shares (session_id, observed_at_utc);

CREATE TABLE IF NOT EXISTS reward_snapshots (
    id TEXT PRIMARY KEY,
    session_id TEXT NULL REFERENCES mining_sessions(id) ON DELETE SET NULL,
    amount_btc TEXT NOT NULL,
    reward_stage TEXT NOT NULL CHECK (reward_stage IN ('estimated', 'pool_reported')),
    status TEXT NOT NULL CHECK (status IN ('measured', 'estimated', 'unavailable', 'simulated')),
    source TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reward_snapshots_stage_time
    ON reward_snapshots (reward_stage, observed_at_utc);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id TEXT PRIMARY KEY,
    asset TEXT NOT NULL,
    quote_asset TEXT NOT NULL,
    price TEXT NULL,
    status TEXT NOT NULL CHECK (status IN ('measured', 'unavailable', 'simulated')),
    source TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL,
    UNIQUE (asset, quote_asset, source, observed_at_utc)
);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_pair_time
    ON price_snapshots (asset, quote_asset, observed_at_utc);

CREATE TABLE IF NOT EXISTS payment_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL CHECK (event_type IN ('payout_issued', 'deposit_detected', 'reconciliation')),
    asset TEXT NOT NULL,
    amount TEXT NOT NULL,
    network_fee TEXT NULL,
    settlement_status TEXT NOT NULL CHECK (settlement_status IN ('pending', 'confirmed', 'failed', 'unknown')),
    data_status TEXT NOT NULL CHECK (data_status IN ('measured', 'simulated')),
    source TEXT NOT NULL,
    external_reference TEXT NULL,
    observed_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_payment_events_type_time
    ON payment_events (event_type, observed_at_utc);

CREATE TABLE IF NOT EXISTS periodic_reports (
    id TEXT PRIMARY KEY,
    window_start_utc TEXT NOT NULL,
    window_end_utc TEXT NOT NULL,
    data_mode TEXT NOT NULL CHECK (data_mode IN ('simulated', 'real')),
    sample_coverage_pct REAL NOT NULL CHECK (sample_coverage_pct >= 0.0 AND sample_coverage_pct <= 100.0),
    gaps_count INTEGER NOT NULL CHECK (gaps_count >= 0),
    summary_json TEXT NOT NULL,
    generated_at_utc TEXT NOT NULL,
    UNIQUE (window_start_utc, window_end_utc, data_mode)
);
