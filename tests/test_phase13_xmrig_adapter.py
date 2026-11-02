"""Mock-only tests for XMRigApiAdapter, MinerConnector, and ControlAuthorization (CP-01-A, CP-02)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from mineops_dw.adapters.xmrig import (
    ShareDelta,
    XMRigApiAdapter,
    XMRigApiError,
    XMRigShareCounter,
    XMRigSummary,
)
from mineops_dw.domain.miner_connector import (
    ControlAuthorization,
    MinerCapabilities,
    MinerConnector,
)


def _summary_payload(
    *,
    version: Any = "6.24.0",
    kind: Any = "miner",
    paused: Any = False,
    uptime: Any = 42,
    include_uptime: bool = True,
    rates: Any = None,
    restricted: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": version,
        "kind": kind,
        "algo": "rx/0",
        "paused": paused,
        "restricted": restricted,
        "hashrate": {"total": [120.0, 110.0, 100.0] if rates is None else rates},
        "results": {"shares_good": 5, "shares_total": 7, "hashes_total": 900},
        "connection": {"pool": "pool.example:3333"},
    }
    if include_uptime:
        payload["uptime"] = uptime
    return payload


def test_xmrig_adapter_implements_miner_connector_protocol() -> None:
    adapter = XMRigApiAdapter()
    assert isinstance(adapter, MinerConnector)


def test_get_snapshot_running_and_paused_with_confirmed_confidence() -> None:
    state = {"paused": False}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/2/summary"
        return httpx.Response(200, json=_summary_payload(paused=state["paused"]))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = XMRigApiAdapter(http_client=client)
        snap_running = adapter.get_snapshot()
        state["paused"] = True
        snap_paused = adapter.get_snapshot()

    assert snap_running.connection_status == "REACHABLE"
    assert snap_running.operational_state == "RUNNING"
    assert snap_running.state_confidence == "CONFIRMED"
    assert snap_running.operational_state_quality == "VALID"
    assert snap_running.hashrate_10s_hs.value == 120.0
    assert snap_running.hashrate_10s_hs.quality == "VALID"
    assert snap_running.hashrate_10s_hs.source_freshness == "UNVERIFIABLE_NO_SOURCE_TIMESTAMP"
    assert snap_running.hashrate_10s_hs.source_updated_at_utc is None

    assert snap_paused.operational_state == "PAUSED"
    assert snap_paused.state_confidence == "CONFIRMED"
    assert snap_paused.operational_state_quality == "VALID"


def test_unreachable_and_timeout_produce_unknown_never_stopped_and_unverified_capabilities() -> None:
    def connect_error_handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    def timeout_handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out")

    for handler in (connect_error_handler, timeout_handler):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            adapter = XMRigApiAdapter(http_client=client)
            snap = adapter.get_snapshot()
            caps = adapter.get_capabilities()

        assert snap.connection_status == "UNREACHABLE"
        assert snap.operational_state == "UNKNOWN"
        assert snap.state_confidence == "UNKNOWN"
        assert snap.operational_state_quality == "UNAVAILABLE"
        assert snap.process_progress == "UNKNOWN"

        assert caps.status == "UNAVAILABLE"
        assert caps.connection_status == "UNREACHABLE"
        assert caps.observe == "UNVERIFIED_PASSIVELY"
        assert caps.state_verification == "UNVERIFIED_PASSIVELY"
        assert caps.pause == "UNVERIFIED_PASSIVELY"
        assert caps.resume == "UNVERIFIED_PASSIVELY"


def test_get_401_403_marks_read_auth_rejected_and_keeps_server_capabilities_unverified() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = XMRigApiAdapter(access_token=SecretStr("wrong-token"), http_client=client)
        snap = adapter.get_snapshot()
        caps = adapter.get_capabilities()

    assert snap.connection_status == "REACHABLE"
    assert snap.operational_state == "UNKNOWN"
    assert snap.operational_state_quality == "UNAVAILABLE"

    assert caps.status == "UNAVAILABLE"
    assert caps.connection_status == "REACHABLE"
    assert caps.local_readiness == "READ_AUTH_REJECTED"
    assert caps.observe == "UNVERIFIED_PASSIVELY"
    assert caps.pause == "UNVERIFIED_PASSIVELY"
    assert caps.resume == "UNVERIFIED_PASSIVELY"


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"version": "6.24.0", "kind": "miner"},  # paused missing
        {"version": "6.24.0", "kind": "miner", "paused": "false"},  # paused wrong type (str)
        {"version": "6.24.0", "kind": "miner", "paused": 1},  # paused wrong type (int)
        {"version": "6.24.0", "kind": "proxy", "paused": False},  # kind != "miner"
        {"version": "   ", "kind": "miner", "paused": False},  # empty version
        {"version": None, "kind": "miner", "paused": False},  # non-string version
    ],
)
def test_cp02_conservative_schema_rejection_never_infers_state_from_hashrate(
    bad_payload: dict[str, Any],
) -> None:
    payload_with_hashrate = {**bad_payload, "hashrate": {"total": [5000.0, 5000.0, 5000.0]}}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload_with_hashrate)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = XMRigApiAdapter(http_client=client)
        snap = adapter.get_snapshot()
        caps = adapter.get_capabilities()

    assert snap.connection_status == "DEGRADED"
    assert snap.operational_state == "UNKNOWN"
    assert snap.state_confidence == "UNKNOWN"
    assert snap.operational_state_quality == "INVALID"
    assert caps.status == "UNAVAILABLE"
    assert caps.state_verification == "CONFIRMED_UNAVAILABLE"


def test_cp02_missing_uptime_keeps_operational_state_valid_and_process_progress_unknown() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_summary_payload(paused=False, include_uptime=False))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = XMRigApiAdapter(http_client=client)
        snap = adapter.get_snapshot()

    assert snap.operational_state == "RUNNING"
    assert snap.state_confidence == "CONFIRMED"
    assert snap.operational_state_quality == "VALID"
    assert snap.process_progress == "UNKNOWN"
    assert snap.uptime_seconds.quality == "UNAVAILABLE"


def test_http_5xx_and_invalid_json_produce_degraded_unknown_state() -> None:
    def http_502_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="Bad Gateway")

    def malformed_json_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{truncated-json")

    for handler in (http_502_handler, malformed_json_handler):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            adapter = XMRigApiAdapter(http_client=client)
            snap = adapter.get_snapshot()
            caps = adapter.get_capabilities()

        assert snap.connection_status == "DEGRADED"
        assert snap.operational_state == "UNKNOWN"
        assert snap.state_confidence == "UNKNOWN"
        assert caps.status == "UNAVAILABLE"


def test_cp02_invalid_secondary_metrics_preserve_operational_state_and_isolate_metric_quality() -> None:
    payload = _summary_payload(paused=False, rates=[-50.0, None, "bad_rate"])
    payload["results"] = {"shares_good": 10, "shares_total": 5, "hashes_total": -1}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = XMRigApiAdapter(http_client=client)
        snap = adapter.get_snapshot()

    assert snap.operational_state == "RUNNING"
    assert snap.state_confidence == "CONFIRMED"
    assert snap.operational_state_quality == "VALID"
    assert snap.hashrate_10s_hs.quality == "INVALID"
    assert snap.hashrate_10s_hs.value is None
    assert snap.hashrate_60s_hs.quality == "UNAVAILABLE"
    assert snap.hashrate_15m_hs.quality == "INVALID"
    assert snap.shares_good.quality == "INVALID"
    assert snap.shares_total.quality == "INVALID"
    assert snap.hashes_total.quality == "INVALID"


def test_update_credentials_invalidates_cached_evidence_and_progress_baseline() -> None:
    current_time = datetime(2026, 11, 2, 12, 0, 0, tzinfo=UTC)
    uptime = {"val": 10}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_summary_payload(paused=False, uptime=uptime["val"]))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = XMRigApiAdapter(
            access_token=SecretStr("token-1"),
            http_client=client,
            clock=lambda: current_time,
        )
        adapter.get_snapshot()
        current_time += timedelta(seconds=2)
        uptime["val"] = 12
        s2 = adapter.get_snapshot()
        assert s2.process_progress == "ADVANCING"

        # Rotating credentials must reset baseline -> next single sample has process_progress == UNKNOWN
        adapter.update_credentials(SecretStr("token-2"))
        current_time += timedelta(seconds=2)
        uptime["val"] = 14
        s3 = adapter.get_snapshot()
        assert s3.process_progress == "UNKNOWN"


def test_xmr03_process_progress_transitions_without_corrupting_individual_metric_quality() -> None:
    current_time = datetime(2026, 11, 2, 12, 0, 0, tzinfo=UTC)
    current_uptime = {"val": 100}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_summary_payload(paused=False, uptime=current_uptime["val"]))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = XMRigApiAdapter(
            http_client=client,
            stall_threshold_seconds=30.0,
            clock=lambda: current_time,
        )
        # 1st sample establishes baseline -> UNKNOWN
        s1 = adapter.get_snapshot()
        assert s1.process_progress == "UNKNOWN"

        # 2nd sample 0.5s later with same integer uptime -> UNCHANGED_WITHIN_RESOLUTION
        current_time += timedelta(milliseconds=500)
        s2 = adapter.get_snapshot()
        assert s2.process_progress == "UNCHANGED_WITHIN_RESOLUTION"

        # 3rd sample 2s later with advancing uptime -> ADVANCING
        current_time += timedelta(seconds=2)
        current_uptime["val"] = 102
        s3 = adapter.get_snapshot()
        assert s3.process_progress == "ADVANCING"

        # 4th sample 35s later with frozen uptime -> STALLED_SUSPECTED, but metrics remain VALID
        current_time += timedelta(seconds=35)
        s4 = adapter.get_snapshot()
        assert s4.process_progress == "STALLED_SUSPECTED"
        assert s4.operational_state == "RUNNING"
        assert s4.operational_state_quality == "VALID"
        assert s4.hashrate_10s_hs.quality == "VALID"


def test_cp01a_passive_read_only_capabilities_and_local_rejection_of_pause_resume() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json=_summary_payload(paused=False, restricted=False))

    auth = ControlAuthorization()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = XMRigApiAdapter(
            access_token=SecretStr("any-token"),
            http_client=client,
            authorization=auth,
        )
        caps = adapter.get_capabilities()
        snap = adapter.get_snapshot()
        pause_res = adapter.pause()
        resume_res = adapter.resume()

        # R-03 must reject granting ControlAuthorization to XMRig because status == READ_ONLY
        granted = auth.try_grant(
            explicit_user_action=True,
            has_in_flight_or_unreconciled_command=False,
            snapshot=snap,
            capabilities=caps,
            mandatory_thermal_metrics_valid=True,
        )

    assert caps.status == "READ_ONLY"
    assert caps.observe == "CONFIRMED_AVAILABLE"
    assert caps.state_verification == "CONFIRMED_AVAILABLE"
    assert caps.pause == "UNVERIFIED_PASSIVELY"
    assert caps.resume == "UNVERIFIED_PASSIVELY"
    assert granted is False
    assert auth.state == "NOT_GRANTED"

    # pause() and resume() must not perform any HTTP calls
    assert calls == [("GET", "/2/summary"), ("GET", "/2/summary")]
    for res in (pause_res, resume_res):
        assert res.delivery == "NOT_SENT"
        assert res.acceptance == "UNKNOWN"
        assert res.postcondition == "NOT_ATTEMPTED"
        assert res.authorization_generation == 0


def test_r03_blocks_when_process_progress_is_stalled_or_unknown_even_if_capabilities_available() -> None:
    now_str = "2026-11-02T12:00:00Z"
    available_caps = MinerCapabilities(
        evaluated_at_utc=now_str,
        status="AVAILABLE",
        connection_status="REACHABLE",
        local_readiness="TOKEN_CONFIGURED",
        observe="CONFIRMED_AVAILABLE",
        state_verification="CONFIRMED_AVAILABLE",
        pause="CONFIRMED_AVAILABLE",
        resume="CONFIRMED_AVAILABLE",
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_summary_payload(paused=False, uptime=10))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = XMRigApiAdapter(http_client=client)
        first_snap = adapter.get_snapshot()  # process_progress == UNKNOWN on 1st sample

    auth = ControlAuthorization()
    assert (
        auth.try_grant(
            explicit_user_action=True,
            has_in_flight_or_unreconciled_command=False,
            snapshot=first_snap,
            capabilities=available_caps,
            mandatory_thermal_metrics_valid=True,
        )
        is False
    )
    assert auth.state == "NOT_GRANTED"
    assert auth.authorization_generation == 0


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:18080",
        "http://example.com:18080",
        "http://127.0.0.1",
        "http://user:pass@127.0.0.1:18080",
        "http://127.0.0.1:18080/path",
        "http://127.0.0.1:18080?token=secret",
    ],
)
def test_rejects_non_loopback_or_ambiguous_base_urls(url: str) -> None:
    with pytest.raises(ValueError):
        XMRigApiAdapter(base_url=url)


def test_api_failure_never_echoes_secret_in_logs_or_errors(caplog: pytest.LogCaptureFixture) -> None:
    secret = "xmrig-test-secret-5678"

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed with token={secret}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = XMRigApiAdapter(access_token=secret, http_client=client)
        snap = adapter.get_snapshot()
        with pytest.raises(XMRigApiError) as error:
            adapter.fetch_summary()

    assert snap.connection_status == "UNREACHABLE"
    assert secret not in str(error.value)
    assert all(secret not in record.getMessage() for record in caplog.records)


def test_share_counter_reports_session_deltas_and_detects_process_reset() -> None:
    counter = XMRigShareCounter()
    first = XMRigSummary("6.24", "rx/0", False, 1, 1, 1, 10, 12, 1000, None, 1)
    counter.start_session(first)
    second = XMRigSummary("6.24", "rx/0", False, 1, 1, 1, 13, 16, 1500, None, 2)
    assert counter.update(second) == ShareDelta(3, 4, 500)
    restarted = XMRigSummary("6.24", "rx/0", False, 1, 1, 1, 1, 1, 10, None, 1)
    assert counter.update(restarted) == ShareDelta(0, 0, 0, baseline_reset=True)
    later = XMRigSummary("6.24", "rx/0", False, 1, 1, 1, 2, 3, 20, None, 2)
    assert counter.update(later) == ShareDelta(1, 2, 10)
