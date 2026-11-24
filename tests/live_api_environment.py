"""Isolated real-API and real-socket test environment for MineOps DW.

Executes real probes against:
1. Windows 11 Host Telemetry (CPU %, RAM MiB, TDP power fallback)
2. Libre Hardware Monitor loopback HTTP endpoint (http://127.0.0.1:8085/data.json)
3. Live Binance Public Market REST APIs (https://api.binance.com/api/v3/ticker/24hr & /ticker/price)
4. Real TCP loopback HTTP servers & passive miner connectors (XMRig, SRBMiner, Kryptex, ThermalSupervisor)
5. Real MineOps LocalHttpServer over TCP loopback (GET /health, POST /api/v1/collect, GET /api/v1/supervisor/status, GET /api/v1/prices)
6. Read-only Pool (unMineable) and Binance SAPI adapters according to .env configuration

All persistence happens inside an isolated temporary SQLite database so user data in
`data/mineops_dw.sqlite3` is never modified.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
from typing import Any

import httpx

from mineops_dw.adapters.binance import BinanceDepositReadOnlyAdapter
from mineops_dw.adapters.kryptex import KryptexProcessAdapter
from mineops_dw.adapters.mining import SimulatedMinerPoolAdapter
from mineops_dw.adapters.pool_balance import UnmineablePoolBalanceAdapter
from mineops_dw.adapters.prices import BinancePublicMarketClient, MarketPriceAdapter
from mineops_dw.adapters.sensors import (
    HostResourceSensorAdapter,
    LhmSensorAdapter,
)
from mineops_dw.adapters.srbminer import SRBMinerApiAdapter
from mineops_dw.adapters.xmrig import XMRigApiAdapter
from mineops_dw.api.server import LocalHttpServer, MineOpsApiService
from mineops_dw.collector.service import TelemetryCollectorService
from mineops_dw.config import AppSettings, load_settings
from mineops_dw.domain.economics import compute_profitability_kpi
from mineops_dw.domain.models import Measurement, normalize_utc_timestamp
from mineops_dw.domain.telemetry import estimate_power_from_tdp
from mineops_dw.domain.thermal_supervisor import ThermalSupervisor
from mineops_dw.storage.database import SQLiteDatabase
from mineops_dw.storage.repositories import MineOpsRepository


@dataclass(frozen=True)
class ProbeSectionResult:
    """Structured result for one probe category in the live test environment."""

    section: str
    passed: bool
    latency_ms: float
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveEnvironmentReport:
    """Complete diagnostic report returned by LiveApiTestEnvironment."""

    executed_at_utc: str
    isolated_db_path: str
    include_external_internet: bool
    all_passed: bool
    sections: list[ProbeSectionResult]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report as a JSON-compatible dictionary."""
        return asdict(self)


class EphemeralLoopbackJsonServer:
    """Real TCP ThreadingHTTPServer bound to 127.0.0.1:0 for testing real HTTP client sockets."""

    def __init__(self, routes: dict[tuple[str, str], tuple[int, dict[str, Any]]]) -> None:
        self._routes = dict(routes)
        self._lock = threading.Lock()
        self.request_log: list[tuple[str, str, dict[str, str], bytes]] = []
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._httpd is None:
            raise RuntimeError("EphemeralLoopbackJsonServer has not been started.")
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def set_route(self, method: str, path: str, status_code: int, payload: dict[str, Any]) -> None:
        with self._lock:
            self._routes[(method.upper(), path)] = (status_code, payload)

    def start(self) -> None:
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self._handle("GET")

            def do_POST(self) -> None:  # noqa: N802
                self._handle("POST")

            def do_PUT(self) -> None:  # noqa: N802
                self._handle("PUT")

            def _handle(self, method: str) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length) if length > 0 else b""
                headers_copy = {k.lower(): v for k, v in self.headers.items()}
                with outer._lock:
                    outer.request_log.append((method, self.path, headers_copy, raw_body))
                    route = outer._routes.get((method, self.path))
                if route is None:
                    status_code, body_dict = 404, {"error": f"No route for {method} {self.path}"}
                else:
                    status_code, body_dict = route
                body_bytes = json.dumps(body_dict).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.end_headers()
                self.wfile.write(body_bytes)

            def log_message(self, format: str, *args: Any) -> None:
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="EphemeralLoopbackJsonServer",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None

    def __enter__(self) -> EphemeralLoopbackJsonServer:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()


class LiveApiTestEnvironment:
    """Isolated test harness for executing real hardware, loopback socket, and live API tests."""

    def __init__(
        self,
        *,
        base_settings: AppSettings | None = None,
        include_external_internet: bool = True,
        lhm_endpoint_url: str = "http://127.0.0.1:8085/data.json",
        fx_usd_to_bob: Decimal = Decimal("6.96"),
    ) -> None:
        self._base_settings = base_settings or load_settings(env_file=Path(".env"))
        self._include_external_internet = include_external_internet
        self._lhm_endpoint_url = lhm_endpoint_url
        self._fx_usd_to_bob = fx_usd_to_bob

    def run_all(self) -> LiveEnvironmentReport:
        """Run all probe sections inside a temporary sandbox directory and return the report."""
        now_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with tempfile.TemporaryDirectory(prefix="mineops_live_env_") as tmp_dir:
            sandbox_db_path = Path(tmp_dir) / "live_test_env.sqlite3"
            sandbox_settings = self._base_settings.model_copy(
                update={
                    "database_path": sandbox_db_path,
                    "app_host": "127.0.0.1",
                    "allow_non_loopback": False,
                }
            )
            db = SQLiteDatabase(sandbox_db_path)
            db.apply_migrations()
            repo = MineOpsRepository(db)

            sections: list[ProbeSectionResult] = [
                self.probe_host_and_lhm_telemetry(sandbox_settings),
                self.probe_real_tcp_miner_connectors_and_supervisor(sandbox_settings),
            ]
            if self._include_external_internet:
                sections.append(self.probe_live_binance_public_apis(sandbox_settings, repo))
            sections.append(self.probe_real_local_http_server(sandbox_settings, db, repo))
            sections.append(self.probe_optional_configured_endpoints(sandbox_settings))

            all_passed = all(section.passed for section in sections)
            return LiveEnvironmentReport(
                executed_at_utc=now_utc,
                isolated_db_path=str(sandbox_db_path),
                include_external_internet=self._include_external_internet,
                all_passed=all_passed,
                sections=sections,
            )

    def probe_host_and_lhm_telemetry(self, settings: AppSettings) -> ProbeSectionResult:
        """1. Real Windows 11 CPU/RAM sensors + real LHM HTTP probe + TDP power fallback."""
        t0 = time.perf_counter()
        host_adapter = HostResourceSensorAdapter()
        # Prime Win32 / psutil tick delta so CPU % has a valid interval sample
        host_adapter.collect()
        time.sleep(0.05)
        host_measurements = host_adapter.collect()
        lhm_measurements = LhmSensorAdapter(
            endpoint_url=self._lhm_endpoint_url,
            timeout_seconds=1.5,
        ).collect()

        by_name = {m.metric_name: m for m in [*host_measurements, *lhm_measurements]}
        cpu_m = by_name.get("cpu_percent_total")
        ram_m = by_name.get("ram_used_mib")
        lhm_temp = by_name.get("cpu_temp_c")
        lhm_power = by_name.get("cpu_package_power_w")

        tdp_fallback_measurement = estimate_power_from_tdp(
            cpu_m,
            tdp_watts=65.0,
            kappa=1.0,
        )

        passed = (
            cpu_m is not None
            and cpu_m.status == "measured"
            and ram_m is not None
            and ram_m.status == "measured"
            and ram_m.value is not None
            and ram_m.value > 0
            and tdp_fallback_measurement.status == "estimated"
            and tdp_fallback_measurement.value is not None
            and tdp_fallback_measurement.value >= 0.0
        )
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return ProbeSectionResult(
            section="host_and_lhm_telemetry",
            passed=passed,
            latency_ms=latency_ms,
            details={
                "cpu_percent_total": {
                    "value": cpu_m.value if cpu_m else None,
                    "status": cpu_m.status if cpu_m else "unavailable",
                    "source": cpu_m.source if cpu_m else None,
                },
                "ram_used_mib": {
                    "value": ram_m.value if ram_m else None,
                    "status": ram_m.status if ram_m else "unavailable",
                },
                "lhm_probe": {
                    "endpoint_url": self._lhm_endpoint_url,
                    "cpu_temp_c": lhm_temp.value if lhm_temp else None,
                    "cpu_temp_status": lhm_temp.status if lhm_temp else "unavailable",
                    "cpu_package_power_w": lhm_power.value if lhm_power else None,
                    "cpu_power_status": lhm_power.status if lhm_power else "unavailable",
                },
                "tdp_power_fallback": {
                    "value_w": tdp_fallback_measurement.value,
                    "status": tdp_fallback_measurement.status,
                    "source": tdp_fallback_measurement.source,
                },
            },
        )

    def probe_real_tcp_miner_connectors_and_supervisor(
        self,
        settings: AppSettings,
    ) -> ProbeSectionResult:
        """2. Real TCP loopback servers + XMRigApiAdapter, SRBMinerApiAdapter, Kryptex, ThermalSupervisor."""
        t0 = time.perf_counter()
        xmrig_summary_payload = {
            "id": "live-tcp-worker",
            "worker_id": "ryzen-5600gt-live-test",
            "version": "6.22.2",
            "kind": "miner",
            "uptime": 360,
            "restricted": False,
            "paused": False,
            "algo": "rx/0",
            "connection": {"pool": "rx.unmineable.com:3333", "uptime": 358},
            "hashrate": {"total": [1925.5, 1910.0, 1895.2], "highest": 1980.0},
            "results": {"shares_good": 14, "shares_total": 14, "hashes_total": 680000},
        }
        srbminer_payload = {
            "miner_version": "2.6.8",
            "algorithm_total": 1,
            "mining_time": 240,
            "algorithms": [
                {
                    "name": "randomx",
                    "hashrate": {"now": 1840.25},
                    "shares": {"accepted": 9, "rejected": 0, "total": 9},
                    "pool": {"pool": "rx.unmineable.com:3333"},
                }
            ],
        }

        with (
            EphemeralLoopbackJsonServer(
                {
                    ("GET", "/2/summary"): (200, xmrig_summary_payload),
                }
            ) as xmrig_srv,
            EphemeralLoopbackJsonServer(
                {
                    ("GET", "/"): (200, srbminer_payload),
                }
            ) as srb_srv,
        ):
            # Real httpx.Client over TCP loopback (no MockTransport)
            xmrig_adapter = XMRigApiAdapter(
                base_url=xmrig_srv.base_url,
                access_token="live-loopback-token",
                timeout_seconds=2.0,
            )
            xmrig_snap = xmrig_adapter.get_snapshot()
            xmrig_caps = xmrig_adapter.get_capabilities()
            xmrig_pause_cmd = xmrig_adapter.pause()

            supervisor = ThermalSupervisor(
                xmrig_adapter,
                critical_temp_c=settings.thermal_critical_temp_c,
                recovery_temp_c=settings.thermal_recovery_temp_c,
                stability_window_seconds=float(settings.thermal_stability_window_seconds),
                max_staleness_seconds=float(settings.thermal_max_staleness_seconds),
            )
            now_iso = normalize_utc_timestamp(datetime.now(UTC))
            crit_temp_m = Measurement(
                metric_name="cpu_temp_c",
                value=settings.thermal_critical_temp_c + 3.5,
                unit="°C",
                status="measured",
                source="lhm_http",
                observed_at_utc=now_iso,
            )
            eval_res = supervisor.step(crit_temp_m)

            srb_adapter = SRBMinerApiAdapter(base_url=srb_srv.base_url, timeout_seconds=2.0)
            srb_snap = srb_adapter.get_snapshot()
            srb_caps = srb_adapter.get_capabilities()

        # Passive OS process inspection via KryptexProcessAdapter
        kryptex_adapter = KryptexProcessAdapter()
        kryptex_snap = kryptex_adapter.get_snapshot()
        kryptex_pause_cmd = kryptex_adapter.pause()

        passed = (
            xmrig_snap.connection_status == "REACHABLE"
            and xmrig_snap.operational_state == "RUNNING"
            and xmrig_snap.hashrate_10s_hs.value == 1925.5
            and xmrig_snap.shares_good.value == 14
            and xmrig_caps.status == "READ_ONLY"
            and xmrig_pause_cmd.delivery == "NOT_SENT"
            and eval_res.mode == "THERMAL_ALERT_UNCONTROLLED"
            and eval_res.is_critical_thermal is True
            and eval_res.alert_edge_triggered is True
            and srb_snap.connection_status == "REACHABLE"
            and srb_snap.operational_state == "RUNNING"
            and srb_snap.hashrate_10s_hs.value == 1840.25
            and srb_caps.status == "READ_ONLY"
            and kryptex_pause_cmd.delivery == "NOT_SENT"
        )
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return ProbeSectionResult(
            section="real_tcp_miner_connectors_and_supervisor",
            passed=passed,
            latency_ms=latency_ms,
            details={
                "xmrig_tcp_snapshot": {
                    "connection_status": xmrig_snap.connection_status,
                    "operational_state": xmrig_snap.operational_state,
                    "hashrate_10s_hs": xmrig_snap.hashrate_10s_hs.value,
                    "shares_good": xmrig_snap.shares_good.value,
                    "algorithm": xmrig_snap.algorithm,
                    "capabilities_status": xmrig_caps.status,
                },
                "thermal_supervisor_over_tcp": {
                    "mode": eval_res.mode,
                    "is_critical_thermal": eval_res.is_critical_thermal,
                    "alert_edge_triggered": eval_res.alert_edge_triggered,
                    "cpu_temp_c": eval_res.cpu_temp_c,
                },
                "srbminer_tcp_snapshot": {
                    "connection_status": srb_snap.connection_status,
                    "operational_state": srb_snap.operational_state,
                    "hashrate_10s_hs": srb_snap.hashrate_10s_hs.value,
                    "shares_good": srb_snap.shares_good.value,
                    "capabilities_status": srb_caps.status,
                },
                "kryptex_passive_os_scan": {
                    "connection_status": kryptex_snap.connection_status,
                    "operational_state": kryptex_snap.operational_state,
                    "pause_delivery": kryptex_pause_cmd.delivery,
                },
            },
        )

    def probe_live_binance_public_apis(
        self,
        settings: AppSettings,
        repo: MineOpsRepository,
    ) -> ProbeSectionResult:
        """3. Live HTTPS calls to https://api.binance.com/api/v3/ticker/24hr and /ticker/price."""
        t0 = time.perf_counter()
        public_client = BinancePublicMarketClient(
            base_url="https://api.binance.com",
            timeout_seconds=5.0,
        )
        btc_ticker, btc_snap = public_client.fetch_ticker_24h(asset="BTC", quote_asset="USDT")
        xmr_ticker, xmr_snap = public_client.fetch_ticker_24h(asset="XMR", quote_asset="USDT")

        price_adapter = MarketPriceAdapter(
            ticker_url="https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
            source_name="binance_live_spot",
            timeout_seconds=5.0,
            usd_to_bob_rate=self._fx_usd_to_bob,
        )
        spot_snapshots = price_adapter.fetch_prices(include_bob=True)

        for snap in [btc_snap, xmr_snap, *spot_snapshots]:
            repo.insert_price_snapshot(snap)

        usd_snap = next((s for s in spot_snapshots if s.quote_asset == "USD"), None)
        bob_snap = next((s for s in spot_snapshots if s.quote_asset == "BOB"), None)

        passed = (
            btc_ticker.status == "measured"
            and btc_ticker.last_price is not None
            and Decimal(btc_ticker.last_price) > Decimal("0")
            and usd_snap is not None
            and usd_snap.status == "measured"
            and usd_snap.price is not None
            and bob_snap is not None
            and bob_snap.status in ("measured", "estimated")
            and bob_snap.price is not None
        )
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return ProbeSectionResult(
            section="live_binance_public_apis",
            passed=passed,
            latency_ms=latency_ms,
            details={
                "btc_usdt_24h": {
                    "symbol": btc_ticker.symbol,
                    "last_price": btc_ticker.last_price,
                    "weighted_avg_price": btc_ticker.weighted_avg_price,
                    "price_change_pct": btc_ticker.price_change_pct,
                    "status": btc_ticker.status,
                },
                "xmr_usdt_24h": {
                    "symbol": xmr_ticker.symbol,
                    "last_price": xmr_ticker.last_price,
                    "price_change_pct": xmr_ticker.price_change_pct,
                    "status": xmr_ticker.status,
                },
                "btc_usd_spot": {
                    "price": usd_snap.price if usd_snap else None,
                    "status": usd_snap.status if usd_snap else "unavailable",
                },
                "btc_bob_converted": {
                    "price": bob_snap.price if bob_snap else None,
                    "status": bob_snap.status if bob_snap else "unavailable",
                    "fx_usd_to_bob": str(self._fx_usd_to_bob),
                },
            },
        )

    def probe_real_local_http_server(
        self,
        settings: AppSettings,
        db: SQLiteDatabase,
        repo: MineOpsRepository,
    ) -> ProbeSectionResult:
        """4. Spin up real LocalHttpServer on 127.0.0.1:0 and exercise REST endpoints via httpx.Client."""
        t0 = time.perf_counter()
        simulator = SimulatedMinerPoolAdapter(seed=42, scenario_name="live_env_validation")
        host_adapter = HostResourceSensorAdapter()
        host_adapter.collect()
        collector = TelemetryCollectorService(
            repository=repo,
            adapters=[host_adapter],
            settings=settings,
            simulator=simulator,
            enable_tdp_fallback=True,
        )
        api_service = MineOpsApiService(
            database=db,
            repository=repo,
            settings=settings,
            collector=collector,
            simulator=simulator,
        )
        server = LocalHttpServer(api_service=api_service, host="127.0.0.1", port=0)
        server.start()
        try:
            with httpx.Client(base_url=server.base_url, timeout=5.0) as client:
                health_resp = client.get("/health")
                collect_resp = client.post("/api/v1/collect")
                sup_resp = client.get("/api/v1/supervisor/status")
                prices_resp = client.get("/api/v1/prices")
                openapi_resp = client.get("/openapi.json")

            health_json = health_resp.json()
            collect_json = collect_resp.json()
            sup_json = sup_resp.json()
            prices_json = prices_resp.json()
            openapi_json = openapi_resp.json()

            kpi = compute_profitability_kpi(
                pending_pool_balance="0.00025000",
                market_price_usd="95000.00",
                electricity_cost_usd="0.18",
                estimated_fees_usd="0.02",
                is_simulated=False,
            )

            passed = (
                health_resp.status_code == 200
                and health_json.get("status") == "ok"
                and collect_resp.status_code == 200
                and collect_json.get("measurements_persisted", 0) > 0
                and sup_resp.status_code == 200
                and "payout" in sup_json
                and "profitability_kpi" in sup_json
                and prices_resp.status_code == 200
                and openapi_resp.status_code == 200
                and openapi_json.get("openapi", "").startswith("3.1")
                and kpi.status == "estimated"
            )
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return ProbeSectionResult(
                section="real_local_http_server",
                passed=passed,
                latency_ms=latency_ms,
                details={
                    "bound_url": server.base_url,
                    "health_status": health_json.get("status"),
                    "measurements_persisted_on_collect": collect_json.get("measurements_persisted"),
                    "supervisor_mode": sup_json.get("mode"),
                    "payout_configured": sup_json.get("payout", {}).get("is_configured"),
                    "persisted_price_items": len(prices_json.get("items", [])),
                    "openapi_version": openapi_json.get("openapi"),
                    "sample_profitability_net_margin_usd": kpi.net_margin_usd,
                },
            )
        finally:
            server.stop()

    def probe_optional_configured_endpoints(self, settings: AppSettings) -> ProbeSectionResult:
        """5. Passively inspect configured XMRig port, unMineable pool adapter, and Binance SAPI."""
        t0 = time.perf_counter()
        xmrig_live = XMRigApiAdapter(
            base_url=settings.xmrig_api_url,
            access_token=settings.xmrig_access_token,
            timeout_seconds=1.5,
        ).get_snapshot()

        pool_adapter = UnmineablePoolBalanceAdapter(
            payout_coin=settings.payout_coin,
            payout_address=settings.payout_address,
            payout_network=settings.payout_network,
            timeout_seconds=4.0,
        )
        payout_progress = pool_adapter.fetch_payout_progress()

        binance_ro = BinanceDepositReadOnlyAdapter(
            api_key=settings.binance_read_only_api_key,
            api_secret=settings.binance_read_only_api_secret,
            base_url="https://api.binance.com",
            timeout_seconds=4.0,
        )
        binance_res = binance_ro.fetch_deposit_history(coin=settings.payout_coin or "BTC")

        # Valid whether external daemons/credentials are active or safely inhibited/offline
        passed = (
            xmrig_live.connection_status in ("REACHABLE", "UNREACHABLE", "DEGRADED")
            and payout_progress.status in ("measured", "unavailable")
            and binance_res.connection_status
            in ("connected", "disconnected", "auth_error", "network_error")
        )
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return ProbeSectionResult(
            section="optional_configured_endpoints",
            passed=passed,
            latency_ms=latency_ms,
            details={
                "local_xmrig_probe": {
                    "url": settings.xmrig_api_url,
                    "connection_status": xmrig_live.connection_status,
                    "operational_state": xmrig_live.operational_state,
                    "hashrate_10s_hs": xmrig_live.hashrate_10s_hs.value,
                },
                "unmineable_pool_probe": {
                    "is_payout_configured": pool_adapter.is_payout_configured,
                    "status": payout_progress.status,
                    "pending_balance": payout_progress.pending_balance,
                    "quality_note": payout_progress.quality_note,
                },
                "binance_sapi_readonly_probe": {
                    "is_configured": binance_ro.is_configured,
                    "connection_status": binance_res.connection_status,
                    "deposits_count": len(binance_res.deposits),
                },
            },
        )


def main() -> int:
    """Run the isolated real-API test environment from the CLI and print a JSON report."""
    env = LiveApiTestEnvironment(include_external_internet=True)
    report = env.run_all()
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    return 0 if report.all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
