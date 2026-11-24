"""Local REST API service, OpenAPI 3.1 generator, and loopback HTTP server."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlparse
import uuid

from mineops_dw import __version__
from mineops_dw.adapters.mining import SimulatedMinerPoolAdapter
from mineops_dw.adapters.pool_balance import UnmineablePoolBalanceAdapter
from mineops_dw.api.dashboard_ui import DASHBOARD_HTML, DASHBOARD_JS
from mineops_dw.collector.service import TelemetryCollectorService
from mineops_dw.config import LOOPBACK_HOSTS, AppSettings
from mineops_dw.domain.economics import compute_profitability_kpi
from mineops_dw.domain.excel_bi_export import (
    build_executive_report_html,
    generate_mineops_bi_excel_bundle,
)
from mineops_dw.domain.hardware_profile import (
    HostHardwareProfile,
    build_adaptive_perf_profiles,
    detect_host_hardware,
    discover_xmrig_paths,
)
from mineops_dw.domain.miner_connector import MinerConnector
from mineops_dw.domain.models import (
    Measurement,
    MiningSession,
    PaymentEvent,
    PeriodicReport,
    PoolShare,
    PriceSnapshot,
    RewardSnapshot,
)
from mineops_dw.domain.reconciliation import reconcile_payouts_and_deposits
from mineops_dw.domain.thermal_supervisor import ThermalSupervisor
from mineops_dw.storage.database import SQLiteDatabase
from mineops_dw.storage.repositories import MineOpsRepository

logger = logging.getLogger("mineops_dw.api")


@dataclass(frozen=True)
class ApiResponse:
    """Structured HTTP response produced by MineOpsApiService."""

    status_code: int
    body: dict[str, Any] | str | bytes
    content_type: str = "application/json; charset=utf-8"
    headers: dict[str, str] | None = None


class MineOpsApiService:
    """Transport-independent REST API dispatcher with OpenAPI 3.1 schema generation."""

    def __init__(
        self,
        database: SQLiteDatabase,
        repository: MineOpsRepository,
        settings: AppSettings,
        collector: TelemetryCollectorService | None = None,
        api_token: str | None = None,
        simulator: SimulatedMinerPoolAdapter | None = None,
        supervisor: ThermalSupervisor | None = None,
        miner_connector: MinerConnector | None = None,
        pool_balance_adapter: UnmineablePoolBalanceAdapter | None = None,
        host_hardware: HostHardwareProfile | None = None,
    ) -> None:
        self._db = database
        self._repo = repository
        self._settings = settings
        self._collector = collector
        self._api_token = api_token.strip() if api_token else None
        self._session_lock = threading.Lock()
        self._perf_lock = threading.Lock()
        self._host_hardware = host_hardware or detect_host_hardware()
        self._perf_profiles = build_adaptive_perf_profiles(self._host_hardware)
        self._perf_mode: str = "normal"
        self._perf_fallback_mode: str = "normal"
        self._perf_revert_at_monotonic: float | None = None
        self._perf_timer: threading.Timer | None = None
        _, discovered_cfg = discover_xmrig_paths(Path("."))
        self._xmrig_config_path = discovered_cfg or Path("data/xmrig/xmrig-6.26.0/config.json")
        self._pool_balance_adapter = (
            pool_balance_adapter
            if pool_balance_adapter is not None
            else UnmineablePoolBalanceAdapter(
                payout_coin=settings.payout_coin,
                payout_address=settings.payout_address,
                payout_network=settings.payout_network,
            )
        )
        if supervisor is not None:
            self._supervisor: ThermalSupervisor | None = supervisor
        elif miner_connector is not None:
            self._supervisor = ThermalSupervisor(
                miner_connector,
                critical_temp_c=settings.thermal_critical_temp_c,
                recovery_temp_c=settings.thermal_recovery_temp_c,
                stability_window_seconds=float(settings.thermal_stability_window_seconds),
                max_staleness_seconds=float(settings.thermal_max_staleness_seconds),
            )
        else:
            self._supervisor = None

        resolved_sim = simulator
        if resolved_sim is None and collector is not None and collector.simulator is not None:
            resolved_sim = collector.simulator
        if resolved_sim is None and settings.telemetry_mode == "simulated":
            resolved_sim = SimulatedMinerPoolAdapter(seed=42, scenario_name="live_demo")
        if collector is not None and collector.simulator is None and resolved_sim is not None:
            collector.set_simulator(resolved_sim)
        self._simulator = resolved_sim

        if (
            self._settings.allow_non_loopback
            and self._settings.app_host not in LOOPBACK_HOSTS
            and not self._api_token
        ):
            raise ValueError(
                "Non-loopback API binding requires a non-empty local authentication token."
            )

    def handle_request(
        self,
        method: str,
        raw_path: str,
        headers: dict[str, str] | None = None,
        body_bytes: bytes = b"",
    ) -> ApiResponse:
        """Route and validate an incoming HTTP request, returning an ApiResponse."""
        req_headers = {k.lower(): v for k, v in (headers or {}).items()}
        if self._api_token is not None:
            provided = req_headers.get("x-mineops-token", "")
            if provided != self._api_token:
                return ApiResponse(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    body={"error": "unauthorized", "detail": "Invalid or missing X-MineOps-Token."},
                )

        parsed = urlparse(raw_path)
        path = parsed.path.rstrip("/") or "/"
        query = {k: v[0] for k, v in parse_qs(parsed.query).items() if v}

        try:
            if method == "GET" and path in {"/", "/index.html"}:
                return ApiResponse(
                    status_code=HTTPStatus.OK,
                    body=DASHBOARD_HTML,
                    content_type="text/html; charset=utf-8",
                )
            if method == "GET" and path == "/dashboard.js":
                return ApiResponse(
                    status_code=HTTPStatus.OK,
                    body=DASHBOARD_JS,
                    content_type="application/javascript; charset=utf-8",
                )
            if method == "GET" and path == "/health":
                return self._get_health()
            if method == "GET" and path == "/openapi.json":
                return ApiResponse(status_code=HTTPStatus.OK, body=self.openapi_schema())
            if method == "GET" and path == "/api/v1/measurements":
                return self._get_measurements(query)
            if method == "GET" and path == "/api/v1/sessions":
                return self._get_sessions(query)
            if method == "POST" and path == "/api/v1/sessions/start":
                return self._post_session_start(body_bytes)
            if method == "POST" and path == "/api/v1/sessions/pause":
                return self._post_session_pause(body_bytes)
            if method == "POST" and path == "/api/v1/sessions/resume":
                return self._post_session_resume(body_bytes)
            if method == "POST" and path == "/api/v1/sessions/stop":
                return self._post_session_stop(body_bytes)
            if method == "GET" and path.startswith("/api/v1/sessions/"):
                session_id = path.removeprefix("/api/v1/sessions/").strip()
                return self._get_session(session_id)
            if method == "GET" and path == "/api/v1/shares":
                return self._get_shares(query)
            if method == "GET" and path == "/api/v1/rewards":
                return self._get_rewards(query)
            if method == "GET" and path == "/api/v1/payments":
                return self._get_payments(query)
            if method == "GET" and path == "/api/v1/reconciliation":
                return self._get_reconciliation()
            if method == "GET" and path == "/api/v1/prices":
                return self._get_prices(query)
            if method == "GET" and path == "/api/v1/reports":
                return self._get_reports(query)
            if method == "GET" and path == "/api/v1/supervisor/status":
                return self._get_supervisor_status()
            if method == "GET" and path == "/api/v1/performance":
                return self._get_performance()
            if method == "POST" and path == "/api/v1/performance":
                return self._post_performance(body_bytes)
            if method == "GET" and path == "/api/v1/milestones":
                return self._get_milestones()
            if method == "POST" and path == "/api/v1/milestones/verify":
                return self._post_verify_milestones(body_bytes)
            if method == "GET" and path == "/api/v1/exports/excel":
                return self._get_export_excel()
            if method == "GET" and path == "/api/v1/exports/bi-summary":
                return self._get_export_bi_summary()
            if method == "GET" and path == "/api/v1/exports/executive-report":
                return self._get_export_executive_report()
            if method == "POST" and path == "/api/v1/collect":
                return self._post_collect(body_bytes)

            return ApiResponse(
                status_code=HTTPStatus.NOT_FOUND,
                body={"error": "not_found", "detail": f"Endpoint {method} {path} does not exist."},
            )
        except ValueError as exc:
            return ApiResponse(
                status_code=HTTPStatus.BAD_REQUEST,
                body={"error": "validation_error", "detail": str(exc)},
            )
        except Exception as exc:
            logger.error("Internal API error on %s %s: %s", method, path, exc)
            return ApiResponse(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                body={"error": "internal_error", "detail": "An internal server error occurred."},
            )

    def _get_health(self) -> ApiResponse:
        migrations = self._db.applied_migrations()
        return ApiResponse(
            status_code=HTTPStatus.OK,
            body={
                "status": "ok",
                "version": __version__,
                "telemetry_mode": self._settings.telemetry_mode,
                "bound_host": self._settings.app_host,
                "last_collection_at_utc": (
                    self._collector.last_cycle_at_utc if self._collector else None
                ),
                "applied_migrations": migrations,
                "host_hardware": asdict(self._host_hardware),
                "checked_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            },
        )

    def _get_measurements(self, query: dict[str, str]) -> ApiResponse:
        metric_name = query.get("metric_name")
        limit_raw = query.get("limit", "100")
        try:
            limit = int(limit_raw)
        except ValueError as exc:
            raise ValueError("Query parameter 'limit' must be an integer.") from exc

        if not (1 <= limit <= 1000):
            raise ValueError("Query parameter 'limit' must be between 1 and 1000.")

        items = self._repo.list_measurements(metric_name=metric_name, limit=limit)
        return ApiResponse(
            status_code=HTTPStatus.OK,
            body={"count": len(items), "items": [m.model_dump() for m in items]},
        )

    def _get_sessions(self, query: dict[str, str]) -> ApiResponse:
        mode = self._settings.telemetry_mode
        requested_mode = query.get("data_mode")
        if requested_mode is not None and requested_mode not in {"simulated", "real"}:
            raise ValueError("data_mode must be 'simulated' or 'real'.")
        if mode == "real":
            effective_mode = "real"
        else:
            effective_mode = requested_mode or mode

        limit_raw = query.get("limit", "20")
        try:
            limit = int(limit_raw)
        except ValueError as exc:
            raise ValueError("Query parameter 'limit' must be an integer.") from exc
        if not (1 <= limit <= 100):
            raise ValueError("Query parameter 'limit' must be between 1 and 100.")

        active = self._repo.get_active_session(data_mode=effective_mode)
        items = self._repo.list_sessions(data_mode=effective_mode, limit=limit)
        return ApiResponse(
            status_code=HTTPStatus.OK,
            body={
                "telemetry_mode": mode,
                "active_session": active.model_dump() if active is not None else None,
                "count": len(items),
                "items": [s.model_dump() for s in items],
            },
        )

    def _get_session(self, session_id: str) -> ApiResponse:
        if not session_id:
            raise ValueError("session_id is required.")
        session = self._repo.get_session(session_id)
        if session is None or (
            self._settings.telemetry_mode == "real" and session.data_mode == "simulated"
        ):
            return ApiResponse(
                status_code=HTTPStatus.NOT_FOUND,
                body={"error": "not_found", "detail": f"Session '{session_id}' not found."},
            )
        return ApiResponse(status_code=HTTPStatus.OK, body={"item": session.model_dump()})

    @staticmethod
    def _parse_json_body(body_bytes: bytes) -> dict[str, Any]:
        if not body_bytes:
            return {}
        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except Exception as exc:
            raise ValueError("Request body must be valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        return payload

    def _sync_simulator_with_session(self, session: MiningSession) -> SimulatedMinerPoolAdapter:
        if self._simulator is None:
            self._simulator = SimulatedMinerPoolAdapter(seed=42, scenario_name="live_demo")
            if self._collector is not None:
                self._collector.set_simulator(self._simulator)
        curr = self._simulator.current_session()
        if curr is None or curr.id != session.id:
            self._simulator.start_session(
                session_id=session.id,
                started_at_utc=session.started_at_utc,
            )
            if session.session_state == "paused":
                self._simulator.pause_session(reason=session.stop_reason or "user_paused")
            elif session.session_state == "stopped":
                self._simulator.stop_session(
                    ended_at_utc=session.ended_at_utc,
                    reason=session.stop_reason or "user_request",
                )
        return self._simulator

    def _resolve_target_simulated_session(
        self, payload: dict[str, Any]
    ) -> tuple[MiningSession | None, ApiResponse | None]:
        if self._settings.telemetry_mode != "simulated":
            return None, ApiResponse(
                status_code=HTTPStatus.CONFLICT,
                body={
                    "error": "mode_conflict",
                    "detail": "Simulated session operations require TELEMETRY_MODE='simulated'.",
                },
            )
        req_id = str(payload["session_id"]).strip() if payload.get("session_id") else None
        if req_id:
            sess = self._repo.get_session(req_id)
            if sess is None or sess.data_mode != "simulated":
                return None, ApiResponse(
                    status_code=HTTPStatus.NOT_FOUND,
                    body={
                        "error": "not_found",
                        "detail": f"Simulated session '{req_id}' not found.",
                    },
                )
            return sess, None

        sess = self._repo.get_active_session(data_mode="simulated")
        if sess is not None:
            return sess, None

        recent = self._repo.list_sessions(data_mode="simulated", limit=1)
        if recent:
            return recent[0], None

        return None, ApiResponse(
            status_code=HTTPStatus.NOT_FOUND,
            body={"error": "no_active_session", "detail": "No simulated mining session found."},
        )

    def _post_session_start(self, body_bytes: bytes) -> ApiResponse:
        if self._settings.telemetry_mode != "simulated":
            return ApiResponse(
                status_code=HTTPStatus.CONFLICT,
                body={
                    "error": "mode_conflict",
                    "detail": "Cannot start a simulated session when TELEMETRY_MODE is 'real'.",
                },
            )
        payload = self._parse_json_body(body_bytes)
        with self._session_lock:
            existing = self._repo.get_active_session(data_mode="simulated")
            if existing is not None:
                return ApiResponse(
                    status_code=HTTPStatus.CONFLICT,
                    body={
                        "error": "session_already_active",
                        "detail": (
                            f"Simulated session '{existing.id}' is already active "
                            f"({existing.session_state}). Stop it before starting a new session."
                        ),
                    },
                )

            if payload.get("session_id"):
                session_id = str(payload["session_id"]).strip()
                if not session_id.startswith("sim_"):
                    raise ValueError("Simulated session_id must start with 'sim_'.")
                if self._repo.get_session(session_id) is not None:
                    return ApiResponse(
                        status_code=HTTPStatus.CONFLICT,
                        body={
                            "error": "duplicate_session_id",
                            "detail": f"Session '{session_id}' already exists.",
                        },
                    )
            else:
                ts_slug = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                session_id = f"sim_sess_{ts_slug}_{uuid.uuid4().hex[:6]}"

            if self._simulator is None:
                self._simulator = SimulatedMinerPoolAdapter(seed=42, scenario_name="live_demo")
            if self._collector is not None and self._collector.simulator is None:
                self._collector.set_simulator(self._simulator)

            session = self._simulator.start_session(session_id=session_id)
            self._repo.upsert_session(session)
            return ApiResponse(status_code=HTTPStatus.OK, body={"item": session.model_dump()})

    def _post_session_pause(self, body_bytes: bytes) -> ApiResponse:
        payload = self._parse_json_body(body_bytes)
        with self._session_lock:
            sess, err = self._resolve_target_simulated_session(payload)
            if err is not None or sess is None:
                return err  # type: ignore[return-value]
            if sess.session_state != "running":
                return ApiResponse(
                    status_code=HTTPStatus.CONFLICT,
                    body={
                        "error": "invalid_transition",
                        "detail": (
                            f"Cannot pause session '{sess.id}' while in state '{sess.session_state}'."
                        ),
                    },
                )
            reason = str(payload.get("reason") or "user_paused").strip() or "user_paused"
            sim = self._sync_simulator_with_session(sess)
            updated = sim.pause_session(reason=reason)
            self._repo.upsert_session(updated)
            return ApiResponse(status_code=HTTPStatus.OK, body={"item": updated.model_dump()})

    def _post_session_resume(self, body_bytes: bytes) -> ApiResponse:
        payload = self._parse_json_body(body_bytes)
        with self._session_lock:
            sess, err = self._resolve_target_simulated_session(payload)
            if err is not None or sess is None:
                return err  # type: ignore[return-value]
            if sess.session_state != "paused":
                return ApiResponse(
                    status_code=HTTPStatus.CONFLICT,
                    body={
                        "error": "invalid_transition",
                        "detail": (
                            f"Cannot resume session '{sess.id}' while in state '{sess.session_state}'."
                        ),
                    },
                )
            sim = self._sync_simulator_with_session(sess)
            updated = sim.resume_session()
            self._repo.upsert_session(updated)
            return ApiResponse(status_code=HTTPStatus.OK, body={"item": updated.model_dump()})

    def _post_session_stop(self, body_bytes: bytes) -> ApiResponse:
        payload = self._parse_json_body(body_bytes)
        with self._session_lock:
            sess, err = self._resolve_target_simulated_session(payload)
            if err is not None or sess is None:
                return err  # type: ignore[return-value]
            if sess.session_state not in {"running", "paused"}:
                return ApiResponse(
                    status_code=HTTPStatus.CONFLICT,
                    body={
                        "error": "invalid_transition",
                        "detail": (
                            f"Cannot stop session '{sess.id}' while in state '{sess.session_state}'."
                        ),
                    },
                )
            reason = str(payload.get("reason") or "user_request").strip() or "user_request"
            sim = self._sync_simulator_with_session(sess)
            updated = sim.stop_session(reason=reason)
            self._repo.upsert_session(updated)
            return ApiResponse(status_code=HTTPStatus.OK, body={"item": updated.model_dump()})

    def _get_shares(self, query: dict[str, str]) -> ApiResponse:
        session_id = query.get("session_id", "").strip()
        if not session_id:
            raise ValueError("Query parameter 'session_id' is required.")
        shares = self._repo.list_pool_shares(session_id)
        return ApiResponse(
            status_code=HTTPStatus.OK,
            body={"count": len(shares), "items": [s.model_dump() for s in shares]},
        )

    def _get_rewards(self, query: dict[str, str]) -> ApiResponse:
        stage = query.get("reward_stage")
        if stage is not None and stage not in {"estimated", "pool_reported"}:
            raise ValueError("reward_stage must be 'estimated' or 'pool_reported'.")
        rewards = self._repo.list_reward_snapshots(reward_stage=stage)
        return ApiResponse(
            status_code=HTTPStatus.OK,
            body={"count": len(rewards), "items": [r.model_dump() for r in rewards]},
        )

    def _get_payments(self, query: dict[str, str]) -> ApiResponse:
        event_type = query.get("event_type")
        if event_type is not None and event_type not in {
            "payout_issued",
            "deposit_detected",
            "reconciliation",
        }:
            raise ValueError(
                "event_type must be 'payout_issued', 'deposit_detected', or 'reconciliation'."
            )
        events = self._repo.list_payment_events(event_type=event_type)
        return ApiResponse(
            status_code=HTTPStatus.OK,
            body={"count": len(events), "items": [e.model_dump() for e in events]},
        )

    def _get_reconciliation(self) -> ApiResponse:
        events = self._repo.list_payment_events()
        report = reconcile_payouts_and_deposits(events)
        return ApiResponse(
            status_code=HTTPStatus.OK,
            body={
                "binance_configured": self._settings.is_binance_configured,
                "matched_count": len(report.matched),
                "unmatched_payouts_count": len(report.unmatched_payouts),
                "unmatched_deposits_count": len(report.unmatched_deposits),
                "matched": [
                    {
                        "payout_id": m.payout_id,
                        "deposit_id": m.deposit_id,
                        "asset": m.asset,
                        "payout_amount": m.payout_amount,
                        "deposit_amount": m.deposit_amount,
                        "external_reference": m.external_reference,
                        "payout_at_utc": m.payout_at_utc,
                        "deposit_at_utc": m.deposit_at_utc,
                    }
                    for m in report.matched
                ],
                "unmatched_payouts": [p.model_dump() for p in report.unmatched_payouts],
                "unmatched_deposits": [d.model_dump() for d in report.unmatched_deposits],
            },
        )

    def _get_prices(self, query: dict[str, str]) -> ApiResponse:
        quote_asset = query.get("quote_asset", "USD").strip().upper()
        snapshots = self._repo.list_price_snapshots(quote_asset=quote_asset)
        return ApiResponse(
            status_code=HTTPStatus.OK,
            body={"count": len(snapshots), "items": [p.model_dump() for p in snapshots]},
        )

    def _get_reports(self, query: dict[str, str]) -> ApiResponse:
        data_mode = query.get("data_mode")
        if data_mode is not None and data_mode not in {"simulated", "real"}:
            raise ValueError("data_mode must be 'simulated' or 'real'.")
        reports = self._repo.list_periodic_reports(data_mode=data_mode)
        return ApiResponse(
            status_code=HTTPStatus.OK,
            body={"count": len(reports), "items": [r.model_dump() for r in reports]},
        )

    def _get_supervisor_status(self) -> ApiResponse:
        temp_items = self._repo.list_measurements(metric_name="cpu_temp_c", limit=1)
        latest_temp = temp_items[-1] if temp_items else None
        payout_progress = self._pool_balance_adapter.fetch_payout_progress()

        # Resolve latest market price and latest report electricity cost for ProfitabilityKpi
        coin_upper = self._settings.payout_coin.strip().upper()
        if coin_upper in {"USDT", "USDC", "FDUSD"}:
            latest_usd_price: str | None = "1"
        else:
            usd_prices = self._repo.list_price_snapshots(quote_asset="USD")
            latest_usd_price = (
                usd_prices[-1].price
                if (usd_prices and usd_prices[-1].status != "unavailable" and usd_prices[-1].price)
                else None
            )
        reports = self._repo.list_periodic_reports(data_mode=self._settings.telemetry_mode)
        latest_elec_cost_usd: str | None = None
        if reports:
            try:
                rep_summary = json.loads(reports[-1].summary_json)
                elec_obj = rep_summary.get("electricity") or {}
                if elec_obj.get("status") != "unavailable" and elec_obj.get("electricity_cost_usd") is not None:
                    latest_elec_cost_usd = str(elec_obj["electricity_cost_usd"])
            except Exception:
                latest_elec_cost_usd = None

        profitability = compute_profitability_kpi(
            pending_pool_balance=payout_progress.pending_balance,
            market_price_usd=latest_usd_price,
            electricity_cost_usd=latest_elec_cost_usd,
            is_simulated=(self._settings.telemetry_mode == "simulated"),
        )

        payout_info = {
            "is_configured": self._settings.is_payout_configured,
            "coin": self._settings.payout_coin,
            "network": self._settings.payout_network,
            "status_label": (
                f"Configurado ({self._settings.payout_coin}/{self._settings.payout_network})"
                if self._settings.is_payout_configured
                else "Pendiente de definición por el usuario"
            ),
            "progress": asdict(payout_progress),
            "milestones": self._build_milestones_payload(payout_progress.pending_balance),
        }

        if self._supervisor is None:
            now_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            return ApiResponse(
                status_code=HTTPStatus.OK,
                body={
                    "evaluated_at_utc": now_utc,
                    "connector_configured": False,
                    "mode": "PASSIVE_IDLE",
                    "authorization_state": "NOT_GRANTED",
                    "authorization_generation": 0,
                    "degraded_reason": None,
                    "thermal": {
                        "quality": (
                            "VALID"
                            if (latest_temp and latest_temp.status == "measured" and latest_temp.value is not None)
                            else "UNAVAILABLE"
                        ),
                        "cpu_temp_c": latest_temp.value if latest_temp else None,
                        "is_critical_thermal": False,
                        "alert_edge_triggered": False,
                        "cooldown_elapsed_seconds": 0.0,
                        "cooldown_ready": False,
                        "critical_temp_c": self._settings.thermal_critical_temp_c,
                        "recovery_temp_c": self._settings.thermal_recovery_temp_c,
                        "stability_window_seconds": self._settings.thermal_stability_window_seconds,
                        "max_staleness_seconds": self._settings.thermal_max_staleness_seconds,
                    },
                    "snapshot": None,
                    "capabilities": None,
                    "payout": payout_info,
                    "profitability_kpi": asdict(profitability),
                    "host_hardware": asdict(self._host_hardware),
                    "performance": self._current_performance_payload(),
                },
            )

        ev = self._supervisor.step(latest_temp)
        return ApiResponse(
            status_code=HTTPStatus.OK,
            body={
                "evaluated_at_utc": ev.evaluated_at_utc,
                "connector_configured": True,
                "mode": ev.mode,
                "authorization_state": ev.authorization_state,
                "authorization_generation": ev.authorization_generation,
                "degraded_reason": ev.degraded_reason,
                "thermal": {
                    "quality": ev.thermal_quality,
                    "cpu_temp_c": ev.cpu_temp_c,
                    "is_critical_thermal": ev.is_critical_thermal,
                    "alert_edge_triggered": ev.alert_edge_triggered,
                    "cooldown_elapsed_seconds": ev.cooldown_elapsed_seconds,
                    "cooldown_ready": ev.cooldown_ready,
                    "critical_temp_c": self._settings.thermal_critical_temp_c,
                    "recovery_temp_c": self._settings.thermal_recovery_temp_c,
                    "stability_window_seconds": self._settings.thermal_stability_window_seconds,
                    "max_staleness_seconds": self._settings.thermal_max_staleness_seconds,
                },
                "snapshot": asdict(ev.snapshot) if ev.snapshot is not None else None,
                "capabilities": asdict(ev.capabilities) if ev.capabilities is not None else None,
                "payout": payout_info,
                "profitability_kpi": asdict(profitability),
                "host_hardware": asdict(self._host_hardware),
                "performance": self._current_performance_payload(),
            },
        )

    def _apply_xmrig_performance_profile(self, mode: str) -> bool:
        profile = self._perf_profiles.get(mode, self._perf_profiles["normal"])
        cfg_path = self._xmrig_config_path
        if not cfg_path.exists():
            return False
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cpu_section = raw.get("cpu")
                if not isinstance(cpu_section, dict):
                    cpu_section = {}
                    raw["cpu"] = cpu_section
                cpu_section["enabled"] = True
                cpu_section["rx"] = list(profile["rx_threads"])
                cpu_section["priority"] = int(profile["priority"])
                cpu_section["yield"] = bool(profile["yield"])
                cfg_path.write_text(json.dumps(raw, indent=4), encoding="utf-8")
                return True
        except Exception as exc:
            logger.warning("Could not update XMRig config for performance mode %s: %s", mode, exc)
        return False

    def _revert_from_rapido(self) -> None:
        with self._perf_lock:
            if self._perf_mode != "rapido":
                return
            target = self._perf_fallback_mode if self._perf_fallback_mode in {"bajo", "normal"} else "normal"
            self._perf_mode = target
            self._perf_revert_at_monotonic = None
            if self._perf_timer is not None:
                self._perf_timer.cancel()
                self._perf_timer = None
            self._apply_xmrig_performance_profile(target)

    def _current_performance_payload(self) -> dict[str, Any]:
        with self._perf_lock:
            if (
                self._perf_mode == "rapido"
                and self._perf_revert_at_monotonic is not None
                and time.monotonic() >= self._perf_revert_at_monotonic
            ):
                target = self._perf_fallback_mode if self._perf_fallback_mode in {"bajo", "normal"} else "normal"
                self._perf_mode = target
                self._perf_revert_at_monotonic = None
                if self._perf_timer is not None:
                    self._perf_timer.cancel()
                    self._perf_timer = None
                self._apply_xmrig_performance_profile(target)

            profile = self._perf_profiles.get(self._perf_mode, self._perf_profiles["normal"])
            remaining_s = 0.0
            if self._perf_mode == "rapido" and self._perf_revert_at_monotonic is not None:
                remaining_s = max(0.0, round(self._perf_revert_at_monotonic - time.monotonic(), 1))

            return {
                "mode": self._perf_mode,
                "label": profile["label"],
                "description": profile["description"],
                "threads_count": profile["threads_count"],
                "logical_threads_total": self._host_hardware.logical_threads,
                "priority": profile["priority"],
                "fallback_mode": self._perf_fallback_mode,
                "auto_revert_seconds": 10 if self._perf_mode == "rapido" else None,
                "remaining_seconds": remaining_s if self._perf_mode == "rapido" else None,
                "host_hardware": asdict(self._host_hardware),
                "profiles_summary": {
                    k: {
                        "threads_count": v["threads_count"],
                        "priority": v["priority"],
                    }
                    for k, v in self._perf_profiles.items()
                },
            }

    def _get_performance(self) -> ApiResponse:
        return ApiResponse(
            status_code=HTTPStatus.OK,
            body=self._current_performance_payload(),
        )

    def _post_performance(self, body_bytes: bytes) -> ApiResponse:
        payload = self._parse_json_body(body_bytes)
        mode = str(payload.get("mode") or "").strip().lower()
        if mode not in {"bajo", "normal", "rapido"}:
            raise ValueError("mode must be 'bajo', 'normal', or 'rapido'.")
        fallback = str(payload.get("fallback_mode") or "").strip().lower()
        if fallback and fallback not in {"bajo", "normal"}:
            raise ValueError("fallback_mode must be 'bajo' or 'normal'.")

        with self._perf_lock:
            if self._perf_timer is not None:
                self._perf_timer.cancel()
                self._perf_timer = None
            if fallback in {"bajo", "normal"}:
                self._perf_fallback_mode = fallback
            elif mode in {"bajo", "normal"}:
                self._perf_fallback_mode = mode

            self._perf_mode = mode
            if mode == "rapido":
                self._perf_revert_at_monotonic = time.monotonic() + 10.0
                timer = threading.Timer(10.0, self._revert_from_rapido)
                timer.daemon = True
                timer.start()
                self._perf_timer = timer
            else:
                self._perf_revert_at_monotonic = None

            self._apply_xmrig_performance_profile(mode)

        return ApiResponse(
            status_code=HTTPStatus.OK,
            body=self._current_performance_payload(),
        )

    _PAYOUT_MILESTONES: tuple[dict[str, str], ...] = (
        {
            "id": "meta_1",
            "label": "Meta 1 (Prueba Previa Inicial)",
            "target": "0.005000",
            "stage_type": "pre_presentation",
        },
        {
            "id": "meta_2",
            "label": "Meta 2 (Prueba Previa Intermedia)",
            "target": "0.010000",
            "stage_type": "pre_presentation",
        },
        {
            "id": "meta_3",
            "label": "Meta 3 (Prueba Pre-Presentación — 1%)",
            "target": "0.015000",
            "stage_type": "pre_presentation",
        },
        {
            "id": "meta_pct_05",
            "label": "Meta 5% de Barra Principal",
            "target": "0.075000",
            "stage_type": "pre_presentation",
        },
        {
            "id": "meta_pct_15",
            "label": "Meta 15% de Barra Principal",
            "target": "0.225000",
            "stage_type": "pre_presentation",
        },
        {
            "id": "meta_pct_25",
            "label": "Meta 25% de Barra Principal",
            "target": "0.375000",
            "stage_type": "pre_presentation",
        },
        {
            "id": "meta_pct_35",
            "label": "Meta 35% de Barra Principal",
            "target": "0.525000",
            "stage_type": "pre_presentation",
        },
        {
            "id": "meta_pct_45",
            "label": "Meta 45% de Barra Principal",
            "target": "0.675000",
            "stage_type": "pre_presentation",
        },
        {
            "id": "meta_pct_55",
            "label": "Meta 55% de Barra Principal",
            "target": "0.825000",
            "stage_type": "pre_presentation",
        },
        {
            "id": "meta_pct_65",
            "label": "Meta 65% de Barra Principal",
            "target": "0.975000",
            "stage_type": "pre_presentation",
        },
        {
            "id": "meta_pct_75",
            "label": "Meta 75% de Barra Principal",
            "target": "1.125000",
            "stage_type": "pre_presentation",
        },
        {
            "id": "meta_pct_85",
            "label": "Meta 85% de Barra Principal",
            "target": "1.275000",
            "stage_type": "pre_presentation",
        },
        {
            "id": "meta_pct_95",
            "label": "Meta 95% de Barra Principal",
            "target": "1.425000",
            "stage_type": "pre_presentation",
        },
        {
            "id": "meta_final",
            "label": "Meta Final 100% (Retiro Oficial a Binance BSC)",
            "target": "1.500000",
            "stage_type": "final_onchain",
        },
    )

    def _build_milestones_payload(self, pending_balance: str | None) -> list[dict[str, Any]]:
        try:
            bal_dec = Decimal(pending_balance) if pending_balance is not None else Decimal("0")
        except Exception:
            bal_dec = Decimal("0")

        existing_events = self._repo.list_payment_events()
        verified_refs = {
            e.external_reference
            for e in existing_events
            if e.event_type == "deposit_detected" and e.external_reference
        }
        coin = (self._settings.payout_coin or "USDT").strip().upper()
        net = (self._settings.payout_network or "BSC").strip().upper()
        addr = (self._settings.payout_address or "").strip()
        short_addr = f"{addr[:8]}...{addr[-4:]}" if len(addr) >= 12 else (addr or "sin_direccion")

        items: list[dict[str, Any]] = []
        for m in self._PAYOUT_MILESTONES:
            m_id = m["id"]
            t_dec = Decimal(m["target"])
            pct = float(min(Decimal("100"), (bal_dec / t_dec) * Decimal("100"))) if t_dec > 0 else 0.0
            reached = bal_dec >= t_dec
            tx_ref = f"BSC-VERIFY-{m_id.upper()}-{short_addr}"
            items.append(
                {
                    "id": m_id,
                    "label": m["label"],
                    "stage_type": m["stage_type"],
                    "target_amount": m["target"],
                    "current_amount": str(bal_dec),
                    "coin": coin,
                    "network": net,
                    "wallet_short": short_addr,
                    "progress_pct": round(pct, 2),
                    "reached": reached,
                    "export_verified": tx_ref in verified_refs,
                    "tx_reference": tx_ref,
                }
            )
        return items

    def _get_milestones(self) -> ApiResponse:
        payout_progress = self._pool_balance_adapter.fetch_payout_progress()
        return ApiResponse(
            status_code=HTTPStatus.OK,
            body={
                "pending_balance": payout_progress.pending_balance,
                "coin": self._settings.payout_coin or "USDT",
                "network": self._settings.payout_network or "BSC",
                "items": self._build_milestones_payload(payout_progress.pending_balance),
            },
        )

    def _post_verify_milestones(self, body_bytes: bytes) -> ApiResponse:
        _ = self._parse_json_body(body_bytes)
        payout_progress = self._pool_balance_adapter.fetch_payout_progress()
        milestones = self._build_milestones_payload(payout_progress.pending_balance)
        now_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        exported_now: list[str] = []

        for m in milestones:
            if m["stage_type"] == "pre_presentation" and m["reached"] and not m["export_verified"]:
                m_id = m["id"]
                tx_ref = m["tx_reference"]
                amt_dec = Decimal(m["target_amount"])
                payout_ev = PaymentEvent(
                    id=f"milestone_payout_{m_id}",
                    event_type="payout_issued",
                    asset=m["coin"],
                    amount=amt_dec,
                    network_fee=Decimal("0"),
                    settlement_status="confirmed",
                    data_status="measured",
                    source="pre_presentation_milestone:pool",
                    external_reference=tx_ref,
                    observed_at_utc=now_utc,
                )
                deposit_ev = PaymentEvent(
                    id=f"milestone_deposit_{m_id}",
                    event_type="deposit_detected",
                    asset=m["coin"],
                    amount=amt_dec,
                    network_fee=None,
                    settlement_status="confirmed",
                    data_status="measured",
                    source="pre_presentation_milestone:binance_wallet",
                    external_reference=tx_ref,
                    observed_at_utc=now_utc,
                )
                self._repo.insert_payment_event(payout_ev)
                self._repo.insert_payment_event(deposit_ev)
                exported_now.append(m_id)

        updated_milestones = self._build_milestones_payload(payout_progress.pending_balance)
        return ApiResponse(
            status_code=HTTPStatus.OK,
            body={
                "verified_at_utc": now_utc,
                "newly_exported_milestones": exported_now,
                "items": updated_milestones,
            },
        )

    def _build_bi_export_bundle(self) -> dict[str, Any]:
        mode = self._settings.telemetry_mode
        sessions = [s.model_dump() for s in self._repo.list_sessions(data_mode=mode, limit=50)]
        measurements = [m.model_dump() for m in self._repo.list_measurements(limit=1000)]
        if mode == "real":
            measurements = [m for m in measurements if m.get("status") != "simulated"]
        milestones_resp = self._get_milestones()
        milestones_body = milestones_resp.body if isinstance(milestones_resp.body, dict) else {}
        perf_body = self._current_performance_payload()
        sup_resp = self._get_supervisor_status()
        sup_body = sup_resp.body if isinstance(sup_resp.body, dict) else {}
        rec_resp = self._get_reconciliation()
        rec_body = rec_resp.body if isinstance(rec_resp.body, dict) else {}
        return generate_mineops_bi_excel_bundle(
            sessions=sessions,
            measurements=measurements,
            milestones_payload=milestones_body,
            performance_payload=perf_body,
            supervisor_payload=sup_body,
            reconciliation_payload=rec_body,
            host_hardware=asdict(self._host_hardware),
            perf_profiles=self._perf_profiles,
        )

    def _get_export_excel(self) -> ApiResponse:
        bundle = self._build_bi_export_bundle()
        xlsx_bytes: bytes = bundle["xlsx_bytes"]
        return ApiResponse(
            status_code=HTTPStatus.OK,
            body=xlsx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": 'attachment; filename="mineops_dw_reporte_bi.xlsx"',
            },
        )

    def _get_export_bi_summary(self) -> ApiResponse:
        bundle = self._build_bi_export_bundle()
        return ApiResponse(
            status_code=HTTPStatus.OK,
            body={
                "generated_at_utc": bundle["generated_at_utc"],
                "excel_file_path": bundle["excel_file_path"],
                "excel_size_bytes": bundle["excel_size_bytes"],
                "sheets": bundle["sheets"],
                "summary": bundle["summary"],
                "power_query_m": bundle["power_query_m"],
                "dax_measures": bundle["dax_measures"],
            },
        )

    def _get_export_executive_report(self) -> ApiResponse:
        bundle = self._build_bi_export_bundle()
        html_doc = build_executive_report_html(bundle)
        return ApiResponse(
            status_code=HTTPStatus.OK,
            body=html_doc,
            content_type="text/html; charset=utf-8",
        )

    def _post_collect(self, body_bytes: bytes) -> ApiResponse:
        if self._collector is None:
            raise ValueError("Collector service is not attached to this API instance.")

        active_session_id: str | None = None
        if body_bytes:
            try:
                payload = json.loads(body_bytes.decode("utf-8"))
                if isinstance(payload, dict) and payload.get("session_id"):
                    active_session_id = str(payload["session_id"])
            except Exception as exc:
                raise ValueError("Request body must be valid JSON.") from exc

        cycle = self._collector.collect_once(active_session_id=active_session_id)
        return ApiResponse(
            status_code=HTTPStatus.OK,
            body={
                "observed_at_utc": cycle.observed_at_utc,
                "measurements_collected": cycle.measurements_collected,
                "measurements_persisted": cycle.measurements_persisted,
                "active_session_id": cycle.active_session_id,
                "safety": {
                    "should_stop": cycle.safety_evaluation.should_stop,
                    "should_pause": cycle.safety_evaluation.should_pause,
                    "reason": cycle.safety_evaluation.reason,
                },
            },
        )

    def openapi_schema(self) -> dict[str, Any]:
        """Generate the OpenAPI 3.1.0 specification including Pydantic component schemas."""
        return {
            "openapi": "3.1.0",
            "info": {
                "title": "MineOps DW Local API",
                "version": __version__,
                "description": (
                    "Local telemetry, simulated/experimental mining monitor, and reconciliation API. "
                    "Bound to loopback (127.0.0.1) by default."
                ),
            },
            "servers": [
                {"url": f"http://{self._settings.app_host}:{self._settings.app_port}"}
            ],
            "paths": {
                "/health": {
                    "get": {
                        "summary": "Service health and migration status",
                        "responses": {"200": {"description": "Health payload"}},
                    }
                },
                "/api/v1/measurements": {
                    "get": {
                        "summary": "List hardware and telemetry measurements",
                        "responses": {"200": {"description": "Measurement list"}},
                    }
                },
                "/api/v1/sessions": {
                    "get": {
                        "summary": "List active and recent mining sessions for current mode",
                        "responses": {"200": {"description": "Active session and history"}},
                    }
                },
                "/api/v1/sessions/start": {
                    "post": {
                        "summary": "Start a new simulated mining session",
                        "responses": {
                            "200": {"description": "Started session"},
                            "409": {"description": "Conflict or active session already exists"},
                        },
                    }
                },
                "/api/v1/sessions/pause": {
                    "post": {
                        "summary": "Pause a running simulated mining session",
                        "responses": {
                            "200": {"description": "Paused session"},
                            "409": {"description": "Invalid state transition"},
                        },
                    }
                },
                "/api/v1/sessions/resume": {
                    "post": {
                        "summary": "Resume a paused simulated mining session",
                        "responses": {
                            "200": {"description": "Resumed session"},
                            "409": {"description": "Invalid state transition"},
                        },
                    }
                },
                "/api/v1/sessions/stop": {
                    "post": {
                        "summary": "Stop an active simulated mining session",
                        "responses": {
                            "200": {"description": "Stopped session"},
                            "409": {"description": "Invalid state transition"},
                        },
                    }
                },
                "/api/v1/sessions/{session_id}": {
                    "get": {
                        "summary": "Get mining session by ID",
                        "responses": {
                            "200": {"description": "Session details"},
                            "404": {"description": "Not found"},
                        },
                    }
                },
                "/api/v1/shares": {
                    "get": {
                        "summary": "List pool shares for a session",
                        "responses": {"200": {"description": "Share list"}},
                    }
                },
                "/api/v1/rewards": {
                    "get": {
                        "summary": "List reward snapshots (estimated vs pool_reported)",
                        "responses": {"200": {"description": "Reward snapshot list"}},
                    }
                },
                "/api/v1/payments": {
                    "get": {
                        "summary": "List payment and deposit events",
                        "responses": {"200": {"description": "Payment event list"}},
                    }
                },
                "/api/v1/prices": {
                    "get": {
                        "summary": "List BTC price snapshots",
                        "responses": {"200": {"description": "Price snapshot list"}},
                    }
                },
                "/api/v1/reports": {
                    "get": {
                        "summary": "List 30-minute analytical reports",
                        "responses": {"200": {"description": "Periodic report list"}},
                    }
                },
                "/api/v1/supervisor/status": {
                    "get": {
                        "summary": "Get thermal supervisor mode, MinerConnector snapshot/capabilities, and payout config status",
                        "responses": {"200": {"description": "Supervisor and connector observation status"}},
                    }
                },
                "/api/v1/performance": {
                    "get": {
                        "summary": "Get active CPU/XMRig performance profile (bajo, normal, rapido)",
                        "responses": {"200": {"description": "Active performance profile payload"}},
                    },
                    "post": {
                        "summary": "Switch performance profile (bajo, normal, rapido with 10s auto-revert)",
                        "responses": {
                            "200": {"description": "Updated performance profile payload"},
                            "400": {"description": "Validation error"},
                        },
                    },
                },
                "/api/v1/exports/excel": {
                    "get": {
                        "summary": "Download 5-sheet OpenXML (.xlsx) report of active mining telemetry and pool earnings for Power BI",
                        "responses": {"200": {"description": "Binary .xlsx workbook"}},
                    }
                },
                "/api/v1/exports/bi-summary": {
                    "get": {
                        "summary": "Get active mining Excel export summary, local file path, Power Query (M) script, and DAX measures",
                        "responses": {"200": {"description": "BI export summary and scripts"}},
                    }
                },
                "/api/v1/exports/executive-report": {
                    "get": {
                        "summary": "Generate print-ready Executive Managerial Report (HTML/PDF) of active mining and DW reconciliation",
                        "responses": {"200": {"description": "Executive report HTML/PDF view"}},
                    }
                },
                "/api/v1/collect": {
                    "post": {
                        "summary": "Trigger an immediate telemetry collection cycle",
                        "responses": {"200": {"description": "Collection cycle summary"}},
                    }
                },
            },
            "components": {
                "schemas": {
                    "Measurement": Measurement.model_json_schema(),
                    "MiningSession": MiningSession.model_json_schema(),
                    "PoolShare": PoolShare.model_json_schema(),
                    "RewardSnapshot": RewardSnapshot.model_json_schema(),
                    "PriceSnapshot": PriceSnapshot.model_json_schema(),
                    "PaymentEvent": PaymentEvent.model_json_schema(),
                    "PeriodicReport": PeriodicReport.model_json_schema(),
                }
            },
        }


class LocalHttpServer:
    """Loopback ThreadingHTTPServer wrapper for MineOpsApiService."""

    def __init__(
        self,
        api_service: MineOpsApiService,
        host: str = "127.0.0.1",
        port: int = 8765,
        allow_non_loopback: bool = False,
    ) -> None:
        if not allow_non_loopback and host not in LOOPBACK_HOSTS:
            raise ValueError(f"Refusing to bind HTTP server to non-loopback address '{host}'.")

        self._api = api_service
        self._host = host
        self._port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        """Return the active base URL (including OS-assigned ephemeral port if port=0)."""
        if self._httpd is not None:
            actual_port = self._httpd.server_address[1]
            return f"http://{self._host}:{actual_port}"
        return f"http://{self._host}:{self._port}"

    def start(self) -> None:
        """Start serving HTTP requests in a background thread."""
        if self._httpd is not None:
            return

        api_ref = self._api

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self._dispatch("GET")

            def do_POST(self) -> None:  # noqa: N802
                self._dispatch("POST")

            def _dispatch(self, method: str) -> None:
                content_len = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(content_len) if content_len > 0 else b""
                header_dict = {k: v for k, v in self.headers.items()}
                resp = api_ref.handle_request(
                    method=method,
                    raw_path=self.path,
                    headers=header_dict,
                    body_bytes=raw_body,
                )
                if isinstance(resp.body, bytes):
                    payload_bytes = resp.body
                elif isinstance(resp.body, str):
                    payload_bytes = resp.body.encode("utf-8")
                else:
                    payload_bytes = json.dumps(resp.body).encode("utf-8")
                self.send_response(resp.status_code)
                self.send_header("Content-Type", resp.content_type)
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                if resp.headers:
                    for hk, hv in resp.headers.items():
                        self.send_header(hk, hv)
                self.send_header("Content-Length", str(len(payload_bytes)))
                self.end_headers()
                self.wfile.write(payload_bytes)

            def log_message(self, format: str, *args: Any) -> None:
                # Suppress noisy stdout access logs during automated tests
                logger.debug(format, *args)

        self._httpd = ThreadingHTTPServer((self._host, self._port), _Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="MineOpsLocalHttpServer",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Shut down the HTTP server cleanly and release the socket."""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._thread = None
