"""Phase 7 tests: Responsive dashboard UI, unit separation, quality badges, and React/TS contracts."""

from __future__ import annotations

from pathlib import Path

import httpx

from mineops_dw.api import LocalHttpServer, MineOpsApiService
from mineops_dw.config import AppSettings
from mineops_dw.storage import MineOpsRepository, SQLiteDatabase


def test_dashboard_html_and_js_served_with_separated_units_and_accessibility(
    tmp_path: Path,
) -> None:
    """Verify GET / and GET /dashboard.js render 3 panels, separate units, and handle states."""
    db = SQLiteDatabase(tmp_path / "phase7.sqlite3")
    db.apply_migrations()
    repo = MineOpsRepository(db)
    settings = AppSettings()
    api = MineOpsApiService(db, repo, settings)

    server = LocalHttpServer(api, host="127.0.0.1", port=0)
    server.start()
    try:
        with httpx.Client(timeout=2.0) as client:
            html_resp = client.get(f"{server.base_url}/")
            js_resp = client.get(f"{server.base_url}/dashboard.js")

        assert html_resp.status_code == 200
        assert "text/html" in html_resp.headers.get("content-type", "")
        html_text = html_resp.text

        # Three panels: Left (resources), Center (session/mining), Right (BTC price & history)
        assert 'id="panel-left-resources"' in html_text
        assert 'id="panel-center-session"' in html_text
        assert 'id="panel-right-market"' in html_text

        # Responsive CSS grid for desktop & mobile
        assert "@media (max-width: 960px)" in html_text

        # Accessibility attributes
        assert 'aria-live="polite"' in html_text
        assert 'role="status"' in html_text

        # Separate unit groups (never mix % with W)
        assert 'data-unit-group="percent"' in html_text
        assert 'data-unit-group="memory-mib"' in html_text
        assert 'data-unit-group="temperature-c"' in html_text
        assert 'data-unit-group="power-energy"' in html_text

        # Four financial states explicitly separated in center panel
        assert "fin-estimated" in html_text
        assert "fin-pool-reported" in html_text
        assert "fin-payout-issued" in html_text
        assert "fin-deposit-detected" in html_text

        # JS bundle includes deduplication, quality badges, and empty/error states
        assert js_resp.status_code == 200
        assert "application/javascript" in js_resp.headers.get("content-type", "")
        js_text = js_resp.text
        assert "function deduplicateMeasurements" in js_text
        assert "No disponible" in js_text
        assert "Sin registros para el filtro actual (empty)" in js_text
    finally:
        server.stop()


def test_react_typescript_source_files_match_api_contracts() -> None:
    """Verify React + TypeScript source files exist and define strict quality and unit types."""
    root = Path(__file__).resolve().parents[1]
    pkg_json = root / "frontend" / "package.json"
    ts_config = root / "frontend" / "tsconfig.json"
    api_types = root / "frontend" / "src" / "types" / "api.ts"
    app_tsx = root / "frontend" / "src" / "App.tsx"

    assert pkg_json.is_file()
    assert ts_config.is_file()
    assert api_types.is_file()
    assert app_tsx.is_file()

    types_content = api_types.read_text(encoding="utf-8")
    assert '"measured" | "estimated" | "unavailable" | "simulated"' in types_content
    assert "export function deduplicateMeasurements" in types_content
    assert "export function formatMeasurementValue" in types_content

    app_content = app_tsx.read_text(encoding="utf-8")
    assert "panel-resources" in app_content
    assert "panel-mining-session" in app_content
    assert "panel-market-price" in app_content
