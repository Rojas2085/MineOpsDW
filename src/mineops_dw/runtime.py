"""Application runtime bootstrapper for starting MineOps DW locally on 127.0.0.1."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import logging
from pathlib import Path
import signal
import threading
import time

from mineops_dw.adapters.binance import BinanceDepositReadOnlyAdapter
from mineops_dw.adapters.mining import SimulatedMinerPoolAdapter
from mineops_dw.adapters.prices import MarketPriceAdapter
from mineops_dw.adapters.sensors import HostResourceSensorAdapter, LhmSensorAdapter
from mineops_dw.api.server import LocalHttpServer, MineOpsApiService
from mineops_dw.collector.service import PeriodicCollectorScheduler, TelemetryCollectorService
from mineops_dw.config import AppSettings, load_settings
from mineops_dw.domain.models import PaymentEvent, PriceSnapshot, normalize_utc_timestamp
from mineops_dw.logging_config import configure_logging
from mineops_dw.reporting.generator import PeriodicReportGenerator, align_window_utc
from mineops_dw.storage.database import SQLiteDatabase
from mineops_dw.storage.repositories import MineOpsRepository

logger = logging.getLogger("mineops_dw.runtime")


def bootstrap_demo_simulation(
    repository: MineOpsRepository,
    collector: TelemetryCollectorService,
) -> str:
    """Seed an initial simulated session and run real host telemetry cycles so the UI is ready."""
    now_dt = datetime.now(UTC)
    start_dt = now_dt - timedelta(minutes=5)

    sim = SimulatedMinerPoolAdapter(
        seed=42,
        scenario_name="live_demo",
        nominal_hashrate_hs=1850.0,
        reward_per_accepted_share_btc=Decimal("0.00000080"),
        pool_fee_ratio=Decimal("0.02"),
        payout_threshold_btc=Decimal("0.00000200"),
    )
    session = sim.start_session("sim_session_live_001", started_at_utc=start_dt)
    repository.upsert_session(session)

    # Run 4 deterministic simulation steps across the last few minutes
    for idx in range(4):
        step_dt = start_dt + timedelta(minutes=idx + 1)
        step_res = sim.step_simulation(
            observed_at_utc=step_dt,
            force_accept=(idx != 2),  # 3 accepted, 1 rejected ('stale') for realistic testing
            reject_reason="stale",
        )
        sim.sync_step_to_repository(step_res, repository)

        # If the simulator emitted a payout, also register a simulated Binance deposit to test reconciliation
        if step_res.payout_event is not None and step_res.payout_event.external_reference:
            net_amt = Decimal(step_res.payout_event.amount) - Decimal(
                step_res.payout_event.network_fee or "0"
            )
            dep = PaymentEvent(
                id=f"sim_dep_{session.id}_{idx:02d}",
                event_type="deposit_detected",
                asset="BTC",
                amount=net_amt,
                settlement_status="confirmed",
                data_status="simulated",
                source="simulator:binance",
                external_reference=step_res.payout_event.external_reference,
                observed_at_utc=step_dt + timedelta(seconds=30),
            )
            repository.insert_payment_event(dep)

    # Seed two simulated BTC/USD price snapshots so variation (%) is visible
    p1_ts = normalize_utc_timestamp(now_dt - timedelta(minutes=10))
    p2_ts = normalize_utc_timestamp(now_dt)
    repository.insert_price_snapshot(
        PriceSnapshot(
            id=f"sim_price_usd_{p1_ts}",
            asset="BTC",
            quote_asset="USD",
            price="68250.00",
            status="simulated",
            source="simulator:market",
            observed_at_utc=p1_ts,
        )
    )
    repository.insert_price_snapshot(
        PriceSnapshot(
            id=f"sim_price_usd_{p2_ts}",
            asset="BTC",
            quote_asset="USD",
            price="68940.50",
            status="simulated",
            source="simulator:market",
            observed_at_utc=p2_ts,
        )
    )

    # Run two immediate host telemetry collection cycles (so Win32 CPU delta and RAM are measured)
    collector.collect_once(active_session_id=session.id)
    time.sleep(0.15)
    collector.collect_once(active_session_id=session.id)

    # Generate initial 30-minute window report
    win_start, win_end = align_window_utc(now_dt, interval_minutes=30)
    rep_gen = PeriodicReportGenerator(
        repository,
        sample_interval_seconds=10,
        electricity_Wait_rate_usd_per_kwh=Decimal("0.12"),
    )
    rep_gen.generate_window_report(win_start, win_end, data_mode="simulated")
    return session.id


def bootstrap_real_mode(
    repository: MineOpsRepository,
    collector: TelemetryCollectorService,
    settings: AppSettings,
) -> None:
    """Collect real host telemetry, live BTC market price, and read-only Binance status (no simulation)."""
    # 1. Two real host telemetry cycles so Win32 CPU delta and RAM are measured immediately
    collector.collect_once(active_session_id=None)
    time.sleep(0.25)
    collector.collect_once(active_session_id=None)

    # 2. Fetch live BTC/USD market price (and BOB at official reference 6.96)
    price_adapter = MarketPriceAdapter(usd_to_bob_rate=Decimal("6.96"))
    for snap in price_adapter.fetch_prices(include_bob=True):
        repository.insert_price_snapshot(snap)

    # 3. Poll read-only Binance deposit history if configured in .env
    binance_adapter = BinanceDepositReadOnlyAdapter(
        api_key=settings.binance_read_only_api_key,
        api_secret=settings.binance_read_only_api_secret,
    )
    dep_result = binance_adapter.fetch_deposit_history(coin="BTC")
    for dep_event in dep_result.deposits:
        repository.insert_payment_event(dep_event)

    # 4. Generate initial 30-minute real-mode analytical report
    now_dt = datetime.now(UTC)
    win_start, win_end = align_window_utc(now_dt, interval_minutes=settings.report_interval_minutes)
    rep_gen = PeriodicReportGenerator(
        repository,
        sample_interval_seconds=settings.sample_interval_seconds,
        electricity_Wait_rate_usd_per_kwh=Decimal("0.12"),
    )
    rep_gen.generate_window_report(win_start, win_end, data_mode="real")


def run_local_service(settings: AppSettings | None = None) -> None:
    """Start SQLite, collector scheduler, and HTTP server on 127.0.0.1 until interrupted."""
    cfg = settings or load_settings(env_file=Path(".env"))
    configure_logging(
        level=cfg.log_level,
        explicit_secrets=cfg.secret_values(),
    )

    db = SQLiteDatabase(cfg.database_path)
    migrations = db.apply_migrations()
    repo = MineOpsRepository(db)

    host_adapter = HostResourceSensorAdapter()
    lhm_adapter = LhmSensorAdapter()
    collector = TelemetryCollectorService(
        repository=repo,
        adapters=[host_adapter, lhm_adapter],
        settings=cfg,
    )

    if cfg.telemetry_mode == "real":
        bootstrap_real_mode(repo, collector, cfg)
        session_id = "none (real mode)"
    else:
        session_id = bootstrap_demo_simulation(repo, collector)

    scheduler = PeriodicCollectorScheduler(
        collector=collector,
        interval_seconds=float(cfg.sample_interval_seconds),
    )
    api_service = MineOpsApiService(
        database=db,
        repository=repo,
        settings=cfg,
        collector=collector,
    )
    server = LocalHttpServer(
        api_service=api_service,
        host=cfg.app_host,
        port=cfg.app_port,
        allow_non_loopback=cfg.allow_non_loopback,
    )

    stop_event = threading.Event()

    def _handle_sig(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    scheduler.start()
    server.start()
    logger.info(
        "MineOps DW started on %s (mode=%s, session=%s, migrations=%s)",
        server.base_url,
        cfg.telemetry_mode,
        session_id,
        migrations,
    )

    try:
        while not stop_event.is_set():
            stop_event.wait(1.0)
    finally:
        logger.info("Shutting down MineOps DW local service...")
        scheduler.stop()
        server.stop()
