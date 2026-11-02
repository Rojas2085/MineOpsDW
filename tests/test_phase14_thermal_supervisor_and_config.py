"""Mock-only tests for PARAM-01..PARAM-06 configuration and ThermalSupervisor (A-02..A-06, R-01..R-05)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from mineops_dw.adapters.xmrig import XMRigApiAdapter
from mineops_dw.api import MineOpsApiService
from mineops_dw.config import AppSettings, load_settings
from mineops_dw.domain.miner_connector import (
    CommandResult,
    ControlAuthorization,
    MinerCapabilities,
    MinerOperationalState,
    MinerSnapshot,
    ProcessProgressState,
)
from mineops_dw.domain.models import Measurement, normalize_utc_timestamp
from mineops_dw.domain.thermal_supervisor import ThermalSupervisor
from mineops_dw.storage import MineOpsRepository, SQLiteDatabase


def _temp_measurement(
    temp_c: float | None,
    observed_dt: datetime,
    *,
    status: str = "measured",
) -> Measurement:
    return Measurement(
        metric_name="cpu_temp_c",
        value=temp_c,
        unit="°C",
        status=status,  # type: ignore[arg-type]
        source="lhm_http",
        observed_at_utc=normalize_utc_timestamp(observed_dt),
        quality_note=None if status == "measured" else "sensor offline",
    )


class _FakeControllableConnector:
    """Deterministic in-memory controllable MinerConnector for testing R-01..R-05."""

    def __init__(
        self,
        clock: callable,
        *,
        state: MinerOperationalState = "RUNNING",
        progress: ProcessProgressState = "ADVANCING",
        uncertain_pause: bool = False,
    ) -> None:
        self._clock = clock
        self.state: MinerOperationalState = state
        self.progress: ProcessProgressState = progress
        self.uncertain_pause = uncertain_pause
        self.pause_calls = 0
        self.resume_calls = 0

    def get_snapshot(self) -> MinerSnapshot:
        return MinerSnapshot(
            observed_at_utc=normalize_utc_timestamp(self._clock()),
            connection_status="REACHABLE",
            operational_state=self.state,
            state_confidence="CONFIRMED",
            operational_state_quality="VALID",
            process_progress=self.progress,
            data_origin="REAL",
        )

    def get_capabilities(self) -> MinerCapabilities:
        return MinerCapabilities(
            evaluated_at_utc=normalize_utc_timestamp(self._clock()),
            status="AVAILABLE",
            connection_status="REACHABLE",
            local_readiness="TOKEN_CONFIGURED",
            observe="CONFIRMED_AVAILABLE",
            state_verification="CONFIRMED_AVAILABLE",
            pause="CONFIRMED_AVAILABLE",
            resume="CONFIRMED_AVAILABLE",
        )

    def pause(self) -> CommandResult:
        self.pause_calls += 1
        pre = self.get_snapshot()
        now_utc = normalize_utc_timestamp(self._clock())
        if self.uncertain_pause:
            return CommandResult(
                command_id=f"fake-pause-{self.pause_calls}",
                action="PAUSE",
                requested_at_utc=now_utc,
                completed_at_utc=now_utc,
                delivery="UNKNOWN",
                acceptance="UNKNOWN",
                postcondition="UNKNOWN",
                pre_snapshot=pre,
                post_snapshot=pre,
                authorization_generation=1,
                revoked_during_execution=False,
                causal_attribution="UNDETERMINED",
            )
        self.state = "PAUSED"
        post = self.get_snapshot()
        return CommandResult(
            command_id=f"fake-pause-{self.pause_calls}",
            action="PAUSE",
            requested_at_utc=now_utc,
            completed_at_utc=now_utc,
            delivery="RESPONSE_RECEIVED",
            acceptance="ACCEPTED",
            postcondition="VERIFIED",
            pre_snapshot=pre,
            post_snapshot=post,
            authorization_generation=1,
            revoked_during_execution=False,
            causal_attribution="UNDETERMINED",
        )

    def resume(self) -> CommandResult:
        self.resume_calls += 1
        pre = self.get_snapshot()
        self.state = "RUNNING"
        post = self.get_snapshot()
        now_utc = normalize_utc_timestamp(self._clock())
        return CommandResult(
            command_id=f"fake-resume-{self.resume_calls}",
            action="RESUME",
            requested_at_utc=now_utc,
            completed_at_utc=now_utc,
            delivery="RESPONSE_RECEIVED",
            acceptance="ACCEPTED",
            postcondition="VERIFIED",
            pre_snapshot=pre,
            post_snapshot=post,
            authorization_generation=1,
            revoked_during_execution=False,
            causal_attribution="UNDETERMINED",
        )


def test_approved_param_01_to_06_defaults_and_validation() -> None:
    settings = load_settings(environ={})
    assert settings.thermal_critical_temp_c == 75.0
    assert settings.thermal_recovery_temp_c == 60.0
    assert settings.thermal_stability_window_seconds == 120
    assert settings.thermal_max_staleness_seconds == 30
    assert settings.xmrig_api_url == "http://127.0.0.1:18080"
    assert settings.payout_coin == ""
    assert settings.payout_address == ""
    assert settings.payout_network == ""
    assert settings.is_payout_configured is False

    configured = AppSettings(
        PAYOUT_COIN="BTC",
        PAYOUT_ADDRESS="bc1qexample",
        PAYOUT_NETWORK="BTC",
        XMRIG_ACCESS_TOKEN="secret_xmrig_tok",
    )
    assert configured.is_payout_configured is True
    assert "secret_xmrig_tok" in configured.secret_values()

    with pytest.raises(ValidationError):
        AppSettings(THERMAL_CRITICAL_TEMP_C=70.0, THERMAL_RECOVERY_TEMP_C=70.0)
    with pytest.raises(ValidationError):
        AppSettings(XMRIG_API_URL="http://example.com:18080")


def test_xmrig_passive_observation_and_thermal_alert_uncontrolled_edge_trigger() -> None:
    now = datetime(2026, 11, 2, 13, 0, 0, tzinfo=UTC)
    paused_flag = {"paused": False}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "version": "6.24.0",
                "kind": "miner",
                "paused": paused_flag["paused"],
                "uptime": 50,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = XMRigApiAdapter(http_client=client, clock=lambda: now)
        sup = ThermalSupervisor(adapter, clock=lambda: now)

        # Safe temperature (55 °C) while XMRig is RUNNING -> OBSERVING_UNCONTROLLED
        e1 = sup.step(_temp_measurement(55.0, now))
        assert e1.mode == "OBSERVING_UNCONTROLLED"
        assert e1.alert_edge_triggered is False

        # Critical temperature (76 °C >= 75 °C) under NOT_GRANTED -> THERMAL_ALERT_UNCONTROLLED (edge=True)
        now += timedelta(seconds=10)
        e2 = sup.step(_temp_measurement(76.0, now))
        assert e2.mode == "THERMAL_ALERT_UNCONTROLLED"
        assert e2.alert_edge_triggered is True
        assert e2.dispatched_command is None

        # Next tick still critical -> THERMAL_ALERT_UNCONTROLLED (edge=False, no duplicate edge alert)
        now += timedelta(seconds=10)
        e3 = sup.step(_temp_measurement(77.0, now))
        assert e3.mode == "THERMAL_ALERT_UNCONTROLLED"
        assert e3.alert_edge_triggered is False

        # When XMRig is paused and temp is safe -> PASSIVE_IDLE
        paused_flag["paused"] = True
        now += timedelta(seconds=10)
        e4 = sup.step(_temp_measurement(55.0, now))
        assert e4.mode == "PASSIVE_IDLE"


def test_controllable_connector_thermal_pause_hysteresis_120s_and_manual_resume() -> None:
    now = datetime(2026, 11, 2, 13, 0, 0, tzinfo=UTC)
    connector = _FakeControllableConnector(lambda: now)
    auth = ControlAuthorization()
    sup = ThermalSupervisor(connector, auth, clock=lambda: now)

    assert sup.request_control_authorization(
        explicit_user_action=True,
        temp_measurement=_temp_measurement(58.0, now),
    )
    assert auth.state == "GRANTED"
    assert auth.authorization_generation == 1

    # Normal tick at 65 °C -> ACTIVE_SUPERVISION, no pause
    e1 = sup.step(_temp_measurement(65.0, now))
    assert e1.mode == "ACTIVE_SUPERVISION"
    assert connector.pause_calls == 0

    # Spike to 75.0 °C -> automatic thermal pause verified
    now += timedelta(seconds=10)
    e2 = sup.step(_temp_measurement(75.0, now))
    assert connector.pause_calls == 1
    assert connector.state == "PAUSED"
    assert e2.mode == "ACTIVE_SUPERVISION"
    assert e2.dispatched_command is not None
    assert e2.dispatched_command.postcondition == "VERIFIED"

    # Cool down to 59.0 °C for 60s -> not yet 120s, manual resume must be rejected
    now += timedelta(seconds=10)
    sup.step(_temp_measurement(59.0, now))
    now += timedelta(seconds=60)
    e_mid = sup.step(_temp_measurement(59.0, now))
    assert e_mid.cooldown_elapsed_seconds == 60.0
    assert e_mid.cooldown_ready is False
    early_resume = sup.user_resume(
        explicit_user_action=True,
        temp_measurement=_temp_measurement(59.0, now),
    )
    assert early_resume.delivery == "NOT_SENT"
    assert connector.resume_calls == 0

    # Bounce to 61.0 °C (> 60.0 °C) resets the stability window to 0s
    now += timedelta(seconds=10)
    e_bounce = sup.step(_temp_measurement(61.0, now))
    assert e_bounce.cooldown_elapsed_seconds == 0.0
    assert e_bounce.cooldown_ready is False

    # Continuous 120s at <= 60.0 °C -> cooldown_ready=True, but NO automatic resume
    now += timedelta(seconds=5)
    sup.step(_temp_measurement(58.0, now))
    now += timedelta(seconds=120)
    e_ready = sup.step(_temp_measurement(58.0, now))
    assert e_ready.cooldown_elapsed_seconds == 120.0
    assert e_ready.cooldown_ready is True
    assert connector.state == "PAUSED"
    assert connector.resume_calls == 0

    # Explicit user resume succeeds after 120s stability window
    ok_resume = sup.user_resume(
        explicit_user_action=True,
        temp_measurement=_temp_measurement(58.0, now),
    )
    assert ok_resume.postcondition == "VERIFIED"
    assert connector.state == "RUNNING"
    assert connector.resume_calls == 1


def test_uncertain_pause_transitions_to_degraded_wait_without_automatic_retry_and_precedence_on_revoke() -> None:
    now = datetime(2026, 11, 2, 13, 0, 0, tzinfo=UTC)
    connector = _FakeControllableConnector(lambda: now, uncertain_pause=True)
    auth = ControlAuthorization()
    sup = ThermalSupervisor(connector, auth, clock=lambda: now)

    assert sup.request_control_authorization(
        explicit_user_action=True,
        temp_measurement=_temp_measurement(55.0, now),
    )

    # Stale sensor (> 30s old) triggers thermal pause, which returns UNKNOWN
    stale_sample = _temp_measurement(55.0, now - timedelta(seconds=45))
    e1 = sup.step(stale_sample)
    assert connector.pause_calls == 1
    assert e1.mode == "DEGRADED_WAIT"
    assert e1.degraded_reason == "UNCERTAIN_PAUSE_STILL_RUNNING_CRITICAL_THERMAL"

    # Subsequent tick while still critical must NOT automatically retry pause() (R-01)
    now += timedelta(seconds=10)
    e2 = sup.step(_temp_measurement(78.0, now))
    assert connector.pause_calls == 1
    assert e2.mode == "DEGRADED_WAIT"
    assert e2.degraded_reason == "UNCERTAIN_PAUSE_STILL_RUNNING_CRITICAL_THERMAL"

    # If authorization is REVOKED, THERMAL_ALERT_UNCONTROLLED takes precedence over DEGRADED_WAIT
    sup.revoke_control_authorization()
    now += timedelta(seconds=10)
    e3 = sup.step(_temp_measurement(78.0, now))
    assert e3.authorization_state == "REVOKED"
    assert e3.mode == "THERMAL_ALERT_UNCONTROLLED"
    assert e3.alert_edge_triggered is True


def test_r05_external_override_conflict_detected_when_miner_resumes_externally() -> None:
    now = datetime(2026, 11, 2, 13, 0, 0, tzinfo=UTC)
    connector = _FakeControllableConnector(lambda: now)
    sup = ThermalSupervisor(connector, clock=lambda: now)

    sup.request_control_authorization(
        explicit_user_action=True,
        temp_measurement=_temp_measurement(55.0, now),
    )
    now += timedelta(seconds=10)
    sup.step(_temp_measurement(76.0, now))
    assert connector.state == "PAUSED"

    # External actor resumes the miner outside MineOps DW
    connector.state = "RUNNING"
    now += timedelta(seconds=10)
    e_conflict = sup.step(_temp_measurement(58.0, now))
    assert e_conflict.mode == "EXTERNAL_OVERRIDE_CONFLICT"
    assert e_conflict.degraded_reason == "EXTERNAL_RESUME_DETECTED_DURING_SUPERVISED_PAUSE"


def test_cp04_api_and_dashboard_expose_supervisor_status_and_payout_config_with_mocks(
    tmp_path: Path,
) -> None:
    db = SQLiteDatabase(tmp_path / "phase14_api.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)
    settings = AppSettings()

    # 1. Without attached connector: zero network I/O, PASSIVE_IDLE, payout unconfigured
    api_unattached = MineOpsApiService(db, repo, settings)
    resp_idle = api_unattached.handle_request("GET", "/api/v1/supervisor/status")
    assert resp_idle.status_code == 200
    assert resp_idle.body["connector_configured"] is False
    assert resp_idle.body["mode"] == "PASSIVE_IDLE"
    assert resp_idle.body["authorization_state"] == "NOT_GRANTED"
    assert resp_idle.body["payout"]["is_configured"] is False
    assert resp_idle.body["payout"]["status_label"] == "Pendiente de definición por el usuario"

    # Dashboard HTML & JS expose the new supervisor and payout elements
    html_body = api_unattached.handle_request("GET", "/").body
    js_body = api_unattached.handle_request("GET", "/dashboard.js").body
    assert 'id="supervisor-connector-card"' in html_body
    assert 'id="payout-config-status"' in html_body
    assert "Pendiente de definición por el usuario" in html_body
    assert 'fetch("/api/v1/supervisor/status")' in js_body

    # 2. With mocked XMRigApiAdapter attached: transitions from OBSERVING_UNCONTROLLED to THERMAL_ALERT_UNCONTROLLED
    now = datetime(2026, 11, 2, 13, 30, 0, tzinfo=UTC)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"version": "6.24.0", "kind": "miner", "paused": False, "uptime": 120},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = XMRigApiAdapter(http_client=client, clock=lambda: now)
        sup = ThermalSupervisor(adapter, clock=lambda: now)
        api_attached = MineOpsApiService(db, repo, settings, supervisor=sup)

        repo.insert_measurement(_temp_measurement(55.0, now))
        r1 = api_attached.handle_request("GET", "/api/v1/supervisor/status")
        assert r1.status_code == 200
        assert r1.body["connector_configured"] is True
        assert r1.body["mode"] == "OBSERVING_UNCONTROLLED"
        assert r1.body["capabilities"]["status"] == "READ_ONLY"
        assert r1.body["snapshot"]["operational_state"] == "RUNNING"

        now += timedelta(seconds=10)
        repo.insert_measurement(_temp_measurement(76.5, now))
        r2 = api_attached.handle_request("GET", "/api/v1/supervisor/status")
        assert r2.status_code == 200
        assert r2.body["mode"] == "THERMAL_ALERT_UNCONTROLLED"
        assert r2.body["thermal"]["alert_edge_triggered"] is True

