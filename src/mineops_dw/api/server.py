"""Local REST API service, OpenAPI 3.1 generator, and loopback HTTP server."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import threading
from typing import Any
from urllib.parse import parse_qs, urlparse

from mineops_dw import __version__
from mineops_dw.api.dashboard_ui import DASHBOARD_HTML, DASHBOARD_JS
from mineops_dw.collector.service import TelemetryCollectorService
from mineops_dw.config import LOOPBACK_HOSTS, AppSettings
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
from mineops_dw.storage.repositories import MineOpsRepository

logger = logging.getLogger("mineops_dw.api")


@dataclass(frozen=True)
class ApiResponse:
    """Structured HTTP response produced by MineOpsApiService."""

    status_code: int
    body: dict[str, Any] | str
    content_type: str = "application/json; charset=utf-8"


class MineOpsApiService:
    """Transport-independent REST API dispatcher with OpenAPI 3.1 schema generation."""

    def __init__(
        self,
        database: SQLiteDatabase,
        repository: MineOpsRepository,
        settings: AppSettings,
        collector: TelemetryCollectorService | None = None,
        api_token: str | None = None,
    ) -> None:
        self._db = database
        self._repo = repository
        self._settings = settings
        self._collector = collector
        self._api_token = api_token.strip() if api_token else None

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
            if method == "GET" and path.startswith("/api/v1/sessions/"):
                session_id = path.removeprefix("/api/v1/sessions/").strip()
                return self._get_session(session_id)
            if method == "GET" and path == "/api/v1/shares":
                return self._get_shares(query)
            if method == "GET" and path == "/api/v1/rewards":
                return self._get_rewards(query)
            if method == "GET" and path == "/api/v1/payments":
                return self._get_payments(query)
            if method == "GET" and path == "/api/v1/prices":
                return self._get_prices(query)
            if method == "GET" and path == "/api/v1/reports":
                return self._get_reports(query)
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

    def _get_session(self, session_id: str) -> ApiResponse:
        if not session_id:
            raise ValueError("session_id is required.")
        session = self._repo.get_session(session_id)
        if session is None:
            return ApiResponse(
                status_code=HTTPStatus.NOT_FOUND,
                body={"error": "not_found", "detail": f"Session '{session_id}' not found."},
            )
        return ApiResponse(status_code=HTTPStatus.OK, body={"item": session.model_dump()})

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
                if isinstance(resp.body, str):
                    payload_bytes = resp.body.encode("utf-8")
                else:
                    payload_bytes = json.dumps(resp.body).encode("utf-8")
                self.send_response(resp.status_code)
                self.send_header("Content-Type", resp.content_type)
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
