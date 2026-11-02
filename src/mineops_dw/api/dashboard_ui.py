"""Responsive localhost Cyberpunk Mining Operations Center HTML/JS assets served by MineOpsApiService."""

from __future__ import annotations

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>MineOps DW — Mining Operations Center</title>
  <style>
    :root {
      --bg: #060a12;
      --bg-panel: #0b1220;
      --card: #101a2e;
      --border: #1e2d4a;
      --text: #f0f6fc;
      --muted: #8b9bb4;
      --neon-green: #00ff9d;
      --electric-blue: #00d2ff;
      --btc-gold: #f7931a;
      --measured: #00ff9d;
      --estimated: #00d2ff;
      --simulated: #ffb800;
      --unavailable: #64748b;
      --danger: #ff3b5c;
      --font-sans: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
      --font-mono: "JetBrains Mono", "Cascadia Code", "Consolas", monospace;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--font-sans);
      background: radial-gradient(circle at 50% 18%, #0e1b33 0%, var(--bg) 65%);
      color: var(--text);
      line-height: 1.5;
      min-height: 100vh;
    }
    header.ops-header {
      padding: 0.9rem 1.5rem;
      background: rgba(6, 10, 18, 0.92);
      border-bottom: 1px solid var(--border);
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 1rem;
      position: sticky;
      top: 0;
      z-index: 20;
      backdrop-filter: blur(8px);
    }
    .brand-block {
      display: flex;
      align-items: center;
      gap: 0.85rem;
    }
    .brand-emblem {
      width: 2.2rem;
      height: 2.2rem;
      border-radius: 50%;
      border: 2px solid var(--neon-green);
      box-shadow: 0 0 12px rgba(0, 255, 157, 0.35);
      display: grid;
      place-items: center;
      font-family: var(--font-mono);
      font-weight: 800;
      color: var(--neon-green);
      font-size: 0.9rem;
    }
    h1 {
      font-size: 1.2rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      margin: 0;
      color: var(--text);
    }
    .brand-subtitle {
      font-size: 0.76rem;
      color: var(--muted);
      font-family: var(--font-mono);
    }
    nav.ops-nav {
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
    }
    .nav-btn {
      background: rgba(16, 26, 46, 0.75);
      color: var(--muted);
      border: 1px solid var(--border);
      padding: 0.35rem 0.75rem;
      border-radius: 0.375rem;
      font-size: 0.78rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .nav-btn:hover, .nav-btn.active {
      color: var(--neon-green);
      border-color: var(--neon-green);
      box-shadow: 0 0 8px rgba(0, 255, 157, 0.2);
    }
    .header-controls {
      display: flex;
      align-items: center;
      gap: 0.55rem;
      flex-wrap: wrap;
    }
    .btn-action {
      background: rgba(0, 210, 255, 0.12);
      color: var(--electric-blue);
      border: 1px solid var(--electric-blue);
      padding: 0.4rem 0.8rem;
      border-radius: 0.375rem;
      font-size: 0.8rem;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .btn-action:hover {
      background: rgba(0, 210, 255, 0.24);
      box-shadow: 0 0 10px rgba(0, 210, 255, 0.35);
    }
    .btn-action.primary-collect {
      background: rgba(0, 255, 157, 0.14);
      color: var(--neon-green);
      border-color: var(--neon-green);
    }
    .btn-action.primary-collect:hover {
      background: rgba(0, 255, 157, 0.26);
      box-shadow: 0 0 12px rgba(0, 255, 157, 0.4);
    }
    .badge {
      display: inline-block;
      padding: 0.14rem 0.52rem;
      border-radius: 999px;
      font-size: 0.7rem;
      font-weight: 700;
      font-family: var(--font-mono);
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }
    .badge-measured {
      background: rgba(0, 255, 157, 0.14);
      color: var(--neon-green);
      border: 1px solid var(--neon-green);
    }
    .badge-estimated {
      background: rgba(0, 210, 255, 0.15);
      color: var(--electric-blue);
      border: 1px solid var(--electric-blue);
    }
    .badge-simulated {
      background: rgba(255, 184, 0, 0.18);
      color: var(--simulated);
      border: 1px solid var(--simulated);
    }
    .badge-unavailable {
      background: rgba(100, 116, 139, 0.2);
      color: #cbd5e1;
      border: 1px solid var(--unavailable);
    }
    .badge-danger {
      background: rgba(255, 59, 92, 0.2);
      color: var(--danger);
      border: 1px solid var(--danger);
    }
    .state-banner {
      margin: 0.75rem 1.25rem 0;
      padding: 0.6rem 1rem;
      border-radius: 0.5rem;
      background: rgba(0, 210, 255, 0.1);
      border: 1px solid rgba(0, 210, 255, 0.4);
      font-family: var(--font-mono);
      font-size: 0.82rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.5rem;
    }
    .state-banner.error {
      background: rgba(255, 59, 92, 0.16);
      border-color: var(--danger);
      color: #ffd1d9;
    }
    .dashboard-grid {
      display: grid;
      grid-template-columns: 1fr 1.38fr 1fr;
      gap: 1.15rem;
      padding: 1rem 1.25rem;
      align-items: start;
    }
    .bottom-analytics-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1.15rem;
      padding: 0 1.25rem 1.25rem;
    }
    @media (max-width: 960px) {
      .dashboard-grid {
        grid-template-columns: 1fr;
      }
      .bottom-analytics-grid {
        grid-template-columns: 1fr;
      }
      #panel-center-session {
        order: -1;
      }
    }
    section.panel {
      background: var(--bg-panel);
      border: 1px solid var(--border);
      border-radius: 0.75rem;
      padding: 1.05rem;
      box-shadow: 0 8px 28px rgba(0, 0, 0, 0.45);
    }
    section.panel.panel-hardware {
      border-top: 2px solid var(--electric-blue);
    }
    section.panel.panel-core {
      border-top: 2px solid var(--neon-green);
      background: linear-gradient(180deg, rgba(16, 28, 52, 0.95) 0%, var(--bg-panel) 100%);
    }
    section.panel.panel-economics {
      border-top: 2px solid var(--btc-gold);
    }
    h2 {
      font-size: 0.98rem;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      margin-top: 0;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.5rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    h3 {
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--muted);
      margin: 0.6rem 0 0.45rem;
    }
    .unit-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 0.5rem;
      padding: 0.75rem;
      margin-bottom: 0.75rem;
    }
    .metric-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0.35rem 0;
      border-bottom: 1px dashed rgba(139, 155, 180, 0.16);
      font-size: 0.85rem;
      gap: 0.5rem;
    }
    .metric-row:last-child {
      border-bottom: none;
    }
    .metric-val {
      font-family: var(--font-mono);
      font-weight: 700;
    }
    .metric-source {
      font-size: 0.68rem;
      color: var(--muted);
      font-family: var(--font-mono);
      display: block;
    }
    .bar-track {
      width: 100%;
      height: 6px;
      background: rgba(6, 10, 18, 0.85);
      border-radius: 999px;
      overflow: hidden;
      margin: 0.2rem 0 0.35rem;
      border: 1px solid rgba(30, 45, 74, 0.8);
    }
    .bar-fill {
      height: 100%;
      background: linear-gradient(90deg, var(--electric-blue), var(--neon-green));
      border-radius: 999px;
      transition: width 0.3s ease;
    }
    /* Mining Core Centerpiece */
    .mining-core-stage {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 1rem 0.5rem;
      position: relative;
    }
    .core-svg-wrapper {
      position: relative;
      width: 230px;
      height: 230px;
      display: grid;
      place-items: center;
    }
    .core-ring-outer {
      transform-origin: 115px 115px;
      animation: core-spin 18s linear infinite;
    }
    .core-ring-inner {
      transform-origin: 115px 115px;
      animation: core-spin-rev 12s linear infinite;
    }
    .core-pulse-circle {
      animation: core-pulse 3s ease-in-out infinite;
    }
    @keyframes core-spin {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }
    @keyframes core-spin-rev {
      from { transform: rotate(360deg); }
      to { transform: rotate(0deg); }
    }
    @keyframes core-pulse {
      0%, 100% { opacity: 0.35; }
      50% { opacity: 0.8; }
    }
    @media (prefers-reduced-motion: reduce) {
      .core-ring-outer, .core-ring-inner, .core-pulse-circle {
        animation: none !important;
      }
    }
    .core-center-readout {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      pointer-events: none;
      padding: 1.5rem;
    }
    .core-mode-tag {
      font-size: 0.68rem;
      font-family: var(--font-mono);
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 0.2rem;
    }
    .core-hashrate-big {
      font-family: var(--font-mono);
      font-size: 1.55rem;
      font-weight: 800;
      color: var(--neon-green);
      text-shadow: 0 0 14px rgba(0, 255, 157, 0.35);
      line-height: 1.15;
    }
    .core-hashrate-unit {
      font-family: var(--font-mono);
      font-size: 0.78rem;
      color: var(--muted);
      margin-top: 0.15rem;
    }
    .core-telemetry-strip {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 0.5rem;
      width: 100%;
      margin-top: 0.85rem;
    }
    .core-stat-pill {
      background: rgba(6, 10, 18, 0.75);
      border: 1px solid var(--border);
      border-radius: 0.45rem;
      padding: 0.45rem 0.55rem;
      text-align: center;
    }
    .core-stat-pill small {
      display: block;
      font-size: 0.68rem;
      color: var(--muted);
      text-transform: uppercase;
    }
    .core-stat-pill strong {
      font-family: var(--font-mono);
      font-size: 0.82rem;
    }
    .price-ticker-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.6rem;
    }
    .price-card {
      background: rgba(247, 147, 26, 0.08);
      border: 1px solid rgba(247, 147, 26, 0.38);
      border-radius: 0.45rem;
      padding: 0.6rem;
    }
    .price-card .pair-label {
      font-size: 0.72rem;
      color: var(--btc-gold);
      font-weight: 700;
      font-family: var(--font-mono);
    }
    .price-card .pair-value {
      font-size: 1.1rem;
      font-weight: 800;
      font-family: var(--font-mono);
      color: var(--text);
      margin: 0.15rem 0;
    }
    .svg-chart-box {
      width: 100%;
      height: 150px;
      background: rgba(6, 10, 18, 0.75);
      border: 1px solid var(--border);
      border-radius: 0.45rem;
      padding: 0.4rem;
    }
    .activity-log {
      max-height: 125px;
      overflow-y: auto;
      font-family: var(--font-mono);
      font-size: 0.75rem;
      background: rgba(6, 10, 18, 0.8);
      border: 1px solid var(--border);
      border-radius: 0.4rem;
      padding: 0.5rem;
      margin: 0;
      list-style: none;
    }
    .activity-log li {
      padding: 0.2rem 0;
      border-bottom: 1px solid rgba(30, 45, 74, 0.5);
    }
    .secondary-details-wrapper {
      padding: 0 1.25rem 2rem;
    }
    details.telemetry-drawer {
      background: var(--bg-panel);
      border: 1px solid var(--border);
      border-radius: 0.75rem;
      padding: 0.85rem 1.1rem;
    }
    details.telemetry-drawer summary {
      cursor: pointer;
      font-weight: 700;
      color: var(--electric-blue);
      font-family: var(--font-mono);
      font-size: 0.88rem;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.8rem;
      font-family: var(--font-mono);
      margin-top: 0.6rem;
    }
    th, td {
      text-align: left;
      padding: 0.42rem;
      border-bottom: 1px solid var(--border);
    }
    .filter-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 0.6rem;
      margin: 0.75rem 0;
      align-items: center;
    }
    select, button {
      background: var(--bg);
      color: var(--text);
      border: 1px solid var(--border);
      padding: 0.35rem 0.6rem;
      border-radius: 0.375rem;
    }
    .hidden-view {
      display: none !important;
    }
  </style>
</head>
<body>
  <header class="ops-header">
    <div class="brand-block">
      <div class="brand-emblem" aria-hidden="true">DW</div>
      <div>
        <h1>MineOps DW — Mining Operations Center</h1>
        <div class="brand-subtitle">AMD Ryzen 5 5600GT + Radeon Graphics · Loopback 127.0.0.1 · Telemetría y Análisis BTC</div>
      </div>
    </div>

    <nav class="ops-nav" aria-label="Navegación de consola">
      <button type="button" class="nav-btn active" data-nav-view="overview">Inicio</button>
      <button type="button" class="nav-btn" data-nav-view="mining">Minería</button>
      <button type="button" class="nav-btn" data-nav-view="hardware">Hardware</button>
      <button type="button" class="nav-btn" data-nav-view="economics">Economía BTC</button>
      <button type="button" class="nav-btn" data-nav-view="reports">Reportes e Historial</button>
    </nav>

    <div class="header-controls">
      <span id="global-mode-badge" class="badge badge-simulated" aria-live="polite">MODO: CARGANDO</span>
      <button id="btn-collect" class="btn-action primary-collect" type="button" aria-label="Recolectar telemetría ahora">Recolectar telemetría</button>
      <button id="btn-refresh" class="btn-action" type="button" aria-label="Actualizar datos ahora">Actualizar</button>
    </div>
  </header>

  <div id="status-banner" class="state-banner" role="status" aria-live="polite">
    <span id="status-banner-text">Cargando datos desde la API local...</span>
    <span id="status-banner-meta"></span>
  </div>

  <main class="dashboard-grid" role="main">
    <!-- Lateral Izquierdo: Hardware y Telemetría del PC -->
    <section id="panel-left-resources" class="panel panel-hardware" aria-labelledby="heading-resources">
      <h2 id="heading-resources">
        <span>Hardware &amp; Sensores</span>
        <span class="badge badge-estimated">TELEMETRÍA PC</span>
      </h2>

      <!-- Grupo exclusivo de porcentajes (nunca mezcla W ni °C) -->
      <div class="unit-card" data-unit-group="percent" aria-label="Indicadores de porcentaje">
        <h3>Carga de Cómputo y Memoria (Unidad: %)</h3>
        <div id="resources-percent-list"></div>
      </div>

      <!-- Grupo exclusivo de Memoria en MiB -->
      <div class="unit-card" data-unit-group="memory-mib" aria-label="Indicadores de memoria en MiB">
        <h3>Memoria Física y Frecuencia (MiB / MHz)</h3>
        <div id="resources-mib-list"></div>
      </div>

      <!-- Grupo exclusivo Térmico (°C) -->
      <div class="unit-card" data-unit-group="temperature-c" aria-label="Indicadores térmicos en grados Celsius">
        <h3>Sensores Térmicos (Unidad: °C)</h3>
        <div id="resources-temp-list"></div>
      </div>

      <!-- Grupo exclusivo Eléctrico (W y Wh separados de %) -->
      <div class="unit-card" data-unit-group="power-energy" aria-label="Indicadores de potencia y energía">
        <h3>Potencia (W) y Energía Medida/Estimada (Wh)</h3>
        <div id="resources-power-list"></div>
      </div>
    </section>

    <!-- Centro: Mining Core Protagonista -->
    <section id="panel-center-session" class="panel panel-core" aria-labelledby="heading-session">
      <h2 id="heading-session">
        <span>Mining Core — Núcleo de Operaciones</span>
        <span id="core-activity-badge" class="badge badge-unavailable">VERIFICANDO</span>
      </h2>

      <div class="unit-card mining-core-stage">
        <div class="core-svg-wrapper" aria-label="Indicador visual del núcleo de minería">
          <svg id="mining-core-svg" width="230" height="230" viewBox="0 0 230 230" role="img" aria-label="Reactor de estado MineOps DW">
            <circle cx="115" cy="115" r="102" fill="none" stroke="#1e2d4a" stroke-width="2" />
            <circle id="core-svg-outer" class="core-ring-outer" cx="115" cy="115" r="94" fill="none" stroke="#00ff9d" stroke-width="4" stroke-dasharray="60 28 20 28" stroke-linecap="round" />
            <circle id="core-svg-inner" class="core-ring-inner" cx="115" cy="115" r="76" fill="none" stroke="#00d2ff" stroke-width="2.5" stroke-dasharray="36 24" />
            <circle id="core-svg-pulse" class="core-pulse-circle" cx="115" cy="115" r="60" fill="rgba(0, 255, 157, 0.07)" stroke="#00ff9d" stroke-width="1.2" />
          </svg>
          <div class="core-center-readout">
            <span id="core-mode-pill" class="core-mode-tag">--</span>
            <div id="core-hashrate-value" class="core-hashrate-big">N/D</div>
            <div id="core-hashrate-unit" class="core-hashrate-unit">Sin fuente activa</div>
          </div>
        </div>

        <div id="session-hashrate-box" style="width:100%; margin-top:0.5rem;"></div>

        <div class="core-telemetry-strip">
          <div class="core-stat-pill">
            <small>Estado / Sesión</small>
            <strong id="core-session-state">N/D</strong>
          </div>
          <div class="core-stat-pill">
            <small>Tiempo Sesión</small>
            <strong id="core-session-time">N/D</strong>
          </div>
          <div class="core-stat-pill">
            <small>Hashes Procesados</small>
            <strong id="core-hashes-processed" title="No existe fuente verificable de conteo acumulado de hashes">N/D (Sin fuente)</strong>
          </div>
        </div>

        <div id="sim-session-controls-card" style="width:100%; margin-top:0.75rem; padding-top:0.65rem; border-top:1px dashed var(--border);">
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
            <span id="sim-session-id-label" style="font-family:var(--font-mono); font-size:0.75rem; color:var(--muted);">Sesión simulada: verificando...</span>
            <div style="display:flex; gap:0.4rem; flex-wrap:wrap;" role="group" aria-label="Controles de sesión simulada">
              <button id="btn-sim-start" class="btn-action" type="button" aria-label="Iniciar sesión simulada">Iniciar simulación</button>
              <button id="btn-sim-pause" class="btn-action" type="button" aria-label="Pausar sesión simulada">Pausar</button>
              <button id="btn-sim-resume" class="btn-action" type="button" aria-label="Reanudar sesión simulada">Reanudar</button>
              <button id="btn-sim-stop" class="btn-action" type="button" aria-label="Detener sesión simulada" style="border-color:rgba(255,59,92,0.5); color:#ff8fa3;">Detener</button>
            </div>
          </div>
        </div>
      </div>

      <div class="unit-card">
        <h3>Guardia de Seguridad Térmica y CPU</h3>
        <div id="core-safety-box" class="metric-row">
          <span>Estado Guardia (Límites CPU / Temp):</span>
          <strong id="core-safety-status" class="metric-val">En espera de ciclo</strong>
        </div>
      </div>

      <div id="supervisor-connector-card" class="unit-card" aria-label="Supervisor térmico y conector de minería">
        <h3>Supervisor Térmico y Conector (`CP-01-A` / `CP-02` / `R-03`)</h3>
        <div class="metric-row">
          <span>Modo Supervisor:</span>
          <strong id="sup-mode-badge" class="metric-val">PASSIVE_IDLE</strong>
        </div>
        <div class="metric-row">
          <span>Autorización Control (`ControlAuthorization`):</span>
          <strong id="sup-auth-state" class="metric-val">NOT_GRANTED (gen 0)</strong>
        </div>
        <div class="metric-row">
          <span>Capacidades (`MinerCapabilities`):</span>
          <strong id="sup-capabilities-status" class="metric-val">UNAVAILABLE</strong>
        </div>
        <div class="metric-row">
          <span>Estado Conector / Avance (`process_progress`):</span>
          <strong id="sup-connector-state" class="metric-val">UNKNOWN · UNKNOWN</strong>
        </div>
      </div>

      <div class="unit-card">
        <h3>Registro de Actividad Reciente</h3>
        <ul id="activity-log-list" class="activity-log" aria-label="Registros recientes de actividad">
          <li>Inicializando consola MineOps DW...</li>
        </ul>
      </div>
    </section>

    <!-- Lateral Derecho: Economía Bitcoin y Conciliación (4 Estados) -->
    <section id="panel-right-market" class="panel panel-economics" aria-labelledby="heading-market">
      <h2 id="heading-market">
        <span>Economía Bitcoin</span>
        <span class="badge badge-simulated" style="color:var(--btc-gold);border-color:var(--btc-gold);">BTC / FIAT</span>
      </h2>

      <div class="unit-card">
        <h3>Cotización de Mercado BTC (USD &amp; BOB)</h3>
        <div id="market-price-box">Sin datos de precio (empty)</div>
      </div>

      <div class="unit-card" aria-label="Cuatro estados financieros desacoplados">
        <h3>Separación Estricta de 4 Etapas Financieras (BTC)</h3>
        <div class="metric-row">
          <span>1. Recompensa Estimada (No confirmada):</span>
          <strong id="fin-estimated" class="metric-val">No disponible</strong>
        </div>
        <div class="metric-row">
          <span>2. Saldo Reportado por el Pool:</span>
          <strong id="fin-pool-reported" class="metric-val">No disponible</strong>
        </div>
        <div class="metric-row">
          <span>3. Pagos Emitidos por Pool (payout_issued):</span>
          <strong id="fin-payout-issued" class="metric-val">0 eventos</strong>
        </div>
        <div class="metric-row">
          <span>4. Depósitos Confirmados en Binance (Read-Only):</span>
          <strong id="fin-deposit-detected" class="metric-val">0 eventos</strong>
        </div>
        <div id="fin-reconciliation-summary" class="metric-row" style="margin-top:0.35rem; font-size:0.78rem; color:var(--muted);">
          <span>Conciliación Pool ↔ Binance:</span>
          <span id="fin-reconciliation-val">Verificando...</span>
        </div>
        <div id="payout-config-card" class="metric-row" style="margin-top:0.25rem; font-size:0.78rem; color:var(--muted);">
          <span>Configuración de pago:</span>
          <span id="payout-config-status" class="metric-val">Pendiente de definición por el usuario</span>
        </div>
      </div>

      <div class="unit-card">
        <h3>Coste Eléctrico y Rentabilidad Operativa</h3>
        <div id="econ-electricity-box">
          <div class="metric-row">
            <span>Energía / Coste Ventana (30m):</span>
            <span class="metric-val">N/D <span class="badge badge-unavailable">unavailable</span></span>
          </div>
        </div>
      </div>
    </section>
  </main>

  <!-- Zona Inferior: Gráficas de Actividad y Reportes de 30 Minutos -->
  <section id="panel-bottom-analytics" class="bottom-analytics-grid" aria-label="Actividad temporal y reportes de 30 minutos">
    <div class="panel">
      <h2>
        <span>Evolución Temporal — CPU &amp; RAM (%) vs Hashrate (H/s)</span>
        <span id="charts-mode-badge" class="badge badge-unavailable">MODO AISLADO</span>
      </h2>
      <div class="unit-card">
        <h3>Gráfica de Rendimiento CPU % y RAM % (Solo modo activo)</h3>
        <div id="chart-hardware-container" class="svg-chart-box" aria-label="Gráfica SVG de CPU y RAM"></div>
      </div>
      <div class="unit-card">
        <h3>Evolución Temporal del Hashrate (H/s — Sin mezclar modos)</h3>
        <div id="chart-hashrate-container" class="svg-chart-box" aria-label="Gráfica SVG de Hashrate"></div>
      </div>
    </div>

    <div class="panel">
      <h2>
        <span>Reportes Analíticos de 30 Minutos</span>
        <span class="badge badge-estimated">SQLITE DW</span>
      </h2>
      <div class="unit-card">
        <h3>Ventanas Periódicas Registradas (/api/v1/reports)</h3>
        <div id="reports-30m-box">Cargando reportes de 30 minutos...</div>
      </div>
    </div>
  </section>

  <!-- Sección Secundaria: Tabla Técnica de Telemetría Detallada -->
  <div id="panel-secondary-telemetry" class="secondary-details-wrapper">
    <details id="telemetry-details-drawer" class="telemetry-drawer">
      <summary>Abrir Vista Secundaria: Historial Técnico de Muestras y Filtros de Calidad</summary>
      <div class="unit-card" style="margin-top:0.75rem;">
        <h3>Historial de Muestras Recientes (Deduplicado y Aislado por Modo)</h3>
        <div class="filter-bar">
          <label for="filter-status">Calidad:</label>
          <select id="filter-status" aria-label="Filtrar por estado de calidad">
            <option value="all">Todos (del modo activo)</option>
            <option value="measured">measured</option>
            <option value="estimated">estimated</option>
            <option value="unavailable">unavailable</option>
            <option value="simulated">simulated</option>
          </select>

          <label for="filter-metric">Métrica:</label>
          <select id="filter-metric" aria-label="Filtrar por nombre de métrica">
            <option value="all">Todas</option>
            <option value="cpu_percent_total">cpu_percent_total</option>
            <option value="ram_usage_percent">ram_usage_percent</option>
            <option value="ram_used_mib">ram_used_mib</option>
            <option value="ram_available_mib">ram_available_mib</option>
            <option value="cpu_temp_c">cpu_temp_c</option>
            <option value="cpu_package_power_w">cpu_package_power_w</option>
            <option value="energy_consumed_wh">energy_consumed_wh</option>
            <option value="hashrate_hs">hashrate_hs</option>
          </select>
        </div>
        <table aria-label="Tabla de historial de telemetría">
          <thead>
            <tr>
              <th>Métrica</th>
              <th>Valor y Unidad</th>
              <th>Calidad</th>
              <th>Fuente</th>
              <th>Hora (UTC)</th>
            </tr>
          </thead>
          <tbody id="history-table-body">
            <tr><td colspan="5">Sin registros (empty)</td></tr>
          </tbody>
        </table>
      </div>
    </details>
  </div>

  <script src="/dashboard.js"></script>
</body>
</html>
"""

DASHBOARD_JS = """(function () {
  "use strict";

  var state = {
    telemetryMode: "simulated",
    boundHost: "127.0.0.1",
    lastCollectionAtUtc: null,
    measurements: [],
    rewards: [],
    payments: [],
    reconciliation: null,
    pricesUsd: [],
    pricesBob: [],
    reports: [],
    activeSession: null,
    sessions: [],
    supervisorStatus: null,
    lastSafety: null,
    statusFilter: "all",
    metricFilter: "all",
    activityLogs: []
  };

  function pushLog(msg) {
    var ts = new Date().toISOString().slice(11, 19) + "Z";
    state.activityLogs.unshift("[" + ts + "] " + msg);
    if (state.activityLogs.length > 25) {
      state.activityLogs.pop();
    }
    var logEl = document.getElementById("activity-log-list");
    if (logEl) {
      logEl.innerHTML = state.activityLogs.map(function (line) {
        return "<li>" + line + "</li>";
      }).join("");
    }
  }

  function deduplicateMeasurements(items) {
    var seen = Object.create(null);
    var out = [];
    for (var i = 0; i < items.length; i++) {
      var m = items[i];
      var key = m.metric_name + "|" + m.source + "|" + m.observed_at_utc;
      if (!seen[key]) {
        seen[key] = true;
        out.push(m);
      }
    }
    return out;
  }

  function isStatusAllowedInMode(statusOrDataStatus, telemetryMode) {
    if (telemetryMode === "real") {
      return statusOrDataStatus !== "simulated";
    }
    return true;
  }

  function filterByTelemetryMode(items, telemetryMode) {
    var out = [];
    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      var st = item.status || item.data_status || "unavailable";
      if (isStatusAllowedInMode(st, telemetryMode)) {
        out.push(item);
      }
    }
    return out;
  }

  function badgeHtml(status, customLabel) {
    var safeStatus = status || "unavailable";
    var text = customLabel || safeStatus;
    return '<span class="badge badge-' + safeStatus + '">' + text + "</span>";
  }

  function formatMetricRow(label, m, showProgressBar) {
    if (!m || m.status === "unavailable" || m.value === null) {
      var note = (m && m.quality_note) ? m.quality_note : "Sensor no disponible";
      var srcUnavailable = (m && m.source) ? m.source : "sin_fuente";
      return (
        '<div class="metric-row">' +
        '<div><span>' + label + '</span><small class="metric-source">fuente: ' + srcUnavailable + "</small></div>" +
        '<span class="metric-val" title="' + note + '">N/D (No disponible) ' + badgeHtml("unavailable") + "</span>" +
        "</div>"
      );
    }
    var pctBar = "";
    if (showProgressBar && m.unit === "%") {
      var clamped = Math.max(0, Math.min(100, Number(m.value) || 0));
      pctBar = '<div class="bar-track"><div class="bar-fill" style="width:' + clamped + '%;"></div></div>';
    }
    var statusLabel = m.status === "simulated" ? "SIMULADO" : m.status;
    return (
      '<div style="padding: 0.25rem 0; border-bottom: 1px dashed rgba(139,155,180,0.16);">' +
      '<div class="metric-row" style="border-bottom:none; padding: 0.15rem 0;">' +
      '<div><span>' + label + '</span><small class="metric-source">fuente: ' + m.source + "</small></div>" +
      '<span class="metric-val"><strong>' + m.value + " " + m.unit + "</strong> " + badgeHtml(m.status, statusLabel) + "</span>" +
      "</div>" +
      pctBar +
      "</div>"
    );
  }

  function buildSvgLineChart(points, maxVal, strokeColor, unitLabel, emptyMessage) {
    if (!points || points.length === 0) {
      return (
        '<div style="height:100%;display:grid;place-items:center;color:var(--muted);font-family:var(--font-mono);font-size:0.78rem;">' +
        emptyMessage +
        "</div>"
      );
    }
    var w = 460;
    var h = 130;
    var padX = 28;
    var padY = 18;
    var usableW = w - padX * 2;
    var usableH = h - padY * 2;

    var computedMax = maxVal;
    if (!computedMax || computedMax <= 0) {
      computedMax = 1;
      for (var i = 0; i < points.length; i++) {
        if (points[i].value > computedMax) computedMax = points[i].value;
      }
      computedMax = computedMax * 1.15;
    }

    var coords = [];
    for (var j = 0; j < points.length; j++) {
      var x = points.length === 1 ? (w / 2) : (padX + (j / (points.length - 1)) * usableW);
      var ratio = Math.max(0, Math.min(1, points[j].value / computedMax));
      var y = padY + usableH - ratio * usableH;
      coords.push(x.toFixed(1) + "," + y.toFixed(1));
    }
    var lastPt = points[points.length - 1];
    return (
      '<svg width="100%" height="100%" viewBox="0 0 ' + w + " " + h + '" preserveAspectRatio="none">' +
      '<line x1="' + padX + '" y1="' + (padY + usableH) + '" x2="' + (w - padX) + '" y2="' + (padY + usableH) + '" stroke="#1e2d4a" stroke-width="1" />' +
      '<line x1="' + padX + '" y1="' + padY + '" x2="' + (w - padX) + '" y2="' + padY + '" stroke="#1e2d4a" stroke-dasharray="4 4" stroke-width="1" />' +
      '<polyline fill="none" stroke="' + strokeColor + '" stroke-width="2.4" points="' + coords.join(" ") + '" />' +
      '<text x="' + padX + '" y="13" fill="#8b9bb4" font-size="10" font-family="monospace">Último: ' + lastPt.value + " " + unitLabel + " (" + lastPt.status.toUpperCase() + ')</text>' +
      '<text x="' + (w - padX) + '" y="13" text-anchor="end" fill="#8b9bb4" font-size="10" font-family="monospace">Muestras: ' + points.length + "</text>" +
      "</svg>"
    );
  }

  function renderMiningCore(latestByMetric) {
    var hsMetric = latestByMetric["hashrate_hs"];
    var coreValEl = document.getElementById("core-hashrate-value");
    var coreUnitEl = document.getElementById("core-hashrate-unit");
    var coreModePill = document.getElementById("core-mode-pill");
    var coreBadge = document.getElementById("core-activity-badge");
    var outerRing = document.getElementById("core-svg-outer");
    var pulseCircle = document.getElementById("core-svg-pulse");

    if (state.telemetryMode === "simulated") {
      coreModePill.textContent = "MODO SIMULADO";
      coreModePill.style.color = "var(--simulated)";
      outerRing.setAttribute("stroke", "#ffb800");
      pulseCircle.setAttribute("stroke", "#ffb800");
    } else {
      coreModePill.textContent = "MODO REAL (LOCAL)";
      coreModePill.style.color = "var(--neon-green)";
      outerRing.setAttribute("stroke", "#00ff9d");
      pulseCircle.setAttribute("stroke", "#00ff9d");
    }

    if (!hsMetric || hsMetric.status === "unavailable" || hsMetric.value === null) {
      coreValEl.textContent = "N/D";
      coreValEl.style.color = "var(--electric-blue)";
      coreUnitEl.textContent = state.telemetryMode === "real" ? "Sin fuente real de H/s" : "Hashrate no disponible";
      coreBadge.className = "badge badge-unavailable";
      coreBadge.textContent = state.telemetryMode === "real" ? "SOLO TELEMETRÍA PC" : "SIN HASHRATE";
    } else {
      coreValEl.textContent = hsMetric.value + " " + hsMetric.unit;
      coreValEl.style.color = hsMetric.status === "simulated" ? "var(--simulated)" : "var(--neon-green)";
      coreUnitEl.textContent = hsMetric.status === "simulated" ? "HASHRATE SIMULADO (" + hsMetric.source + ")" : "HASHRATE MEDIDO (" + hsMetric.source + ")";
      coreBadge.className = "badge badge-" + hsMetric.status;
      coreBadge.textContent = hsMetric.status === "simulated" ? "SIMULACIÓN ACTIVA" : "ACTIVO";
    }

    document.getElementById("session-hashrate-box").innerHTML =
      formatMetricRow("Hashrate Experimental", hsMetric, false);

    var sessStateEl = document.getElementById("core-session-state");
    var sessTimeEl = document.getElementById("core-session-time");
    var controlsCard = document.getElementById("sim-session-controls-card");
    var simIdLabel = document.getElementById("sim-session-id-label");
    var btnStart = document.getElementById("btn-sim-start");
    var btnPause = document.getElementById("btn-sim-pause");
    var btnResume = document.getElementById("btn-sim-resume");
    var btnStop = document.getElementById("btn-sim-stop");

    if (state.telemetryMode === "real") {
      if (controlsCard) controlsCard.classList.add("hidden-view");
      if (state.activeSession && state.activeSession.data_mode === "real") {
        sessStateEl.textContent = state.activeSession.session_state.toUpperCase();
        sessTimeEl.textContent = state.activeSession.started_at_utc.slice(11, 19) + " UTC";
      } else {
        sessStateEl.textContent = "Sin minero activo";
        sessTimeEl.textContent = "N/D";
      }
    } else {
      if (controlsCard) controlsCard.classList.remove("hidden-view");
      if (state.activeSession && state.activeSession.data_mode === "simulated") {
        var stLabel = state.activeSession.session_state.toUpperCase() + " (SIMULADO)";
        sessStateEl.textContent = stLabel;
        sessTimeEl.textContent = state.activeSession.started_at_utc.slice(11, 19) + " UTC";
        if (simIdLabel) {
          simIdLabel.textContent = "ID: " + state.activeSession.id + " · " + stLabel;
        }
        if (state.activeSession.session_state === "paused") {
          coreBadge.className = "badge badge-simulated";
          coreBadge.textContent = "SIMULACIÓN PAUSADA";
        }
      } else if (state.sessions && state.sessions.length > 0 && state.sessions[0].data_mode === "simulated") {
        var lastSess = state.sessions[0];
        var lastLabel = lastSess.session_state.toUpperCase() + " (SIMULADO)";
        sessStateEl.textContent = lastLabel;
        sessTimeEl.textContent = lastSess.started_at_utc.slice(11, 19) + " UTC";
        if (simIdLabel) {
          simIdLabel.textContent = "Última: " + lastSess.id + " (" + lastSess.session_state.toUpperCase() + ")";
        }
        coreBadge.className = "badge badge-unavailable";
        coreBadge.textContent = "SIMULACIÓN DETENIDA";
      } else {
        sessStateEl.textContent = "SIN SESIÓN SIMULADA";
        sessTimeEl.textContent = "N/D";
        if (simIdLabel) {
          simIdLabel.textContent = "Sin sesión simulada activa";
        }
      }

      var hasActiveSim = Boolean(state.activeSession && state.activeSession.data_mode === "simulated");
      var simState = hasActiveSim ? state.activeSession.session_state : null;
      if (btnStart) btnStart.disabled = hasActiveSim;
      if (btnPause) btnPause.disabled = simState !== "running";
      if (btnResume) btnResume.disabled = simState !== "paused";
      if (btnStop) btnStop.disabled = (simState !== "running" && simState !== "paused");
    }

    var safetyEl = document.getElementById("core-safety-status");
    if (state.lastSafety) {
      if (state.lastSafety.should_stop) {
        safetyEl.innerHTML = "PARADA SEGURIDAD (" + (state.lastSafety.reason || "límite") + ") " + badgeHtml("danger", "STOP");
      } else if (state.lastSafety.should_pause) {
        safetyEl.innerHTML = "PAUSA PREVENTIVA (" + (state.lastSafety.reason || "límite") + ") " + badgeHtml("simulated", "PAUSE");
      } else {
        safetyEl.innerHTML = "Dentro de límites seguros " + badgeHtml("measured", "OK");
      }
    } else {
      safetyEl.innerHTML = "Vigilancia pasiva activa " + badgeHtml("measured", "OK");
    }
  }

  function renderPriceTicker() {
    var priceBox = document.getElementById("market-price-box");
    var modeUsd = filterByTelemetryMode(state.pricesUsd, state.telemetryMode);
    var modeBob = filterByTelemetryMode(state.pricesBob, state.telemetryMode);

    if (modeUsd.length === 0 && modeBob.length === 0) {
      priceBox.textContent = "Sin cotizaciones registradas para el modo actual (empty)";
      return;
    }

    function formatPairCard(list, pairTitle) {
      if (!list || list.length === 0) {
        return (
          '<div class="price-card">' +
          '<div class="pair-label">' + pairTitle + "</div>" +
          '<div class="pair-value">N/D</div>' +
          badgeHtml("unavailable", "No disponible") +
          "</div>"
        );
      }
      var last = list[list.length - 1];
      var prev = list.length > 1 ? list[list.length - 2] : null;
      var deltaText = "0.00%";
      if (prev && prev.price && last.price) {
        var p0 = parseFloat(prev.price);
        var p1 = parseFloat(last.price);
        if (p0 > 0) {
          var diff = ((p1 - p0) / p0) * 100;
          deltaText = (diff >= 0 ? "+" : "") + diff.toFixed(2) + "%";
        }
      }
      var stTag = last.status === "simulated" ? "SIMULADO" : last.status;
      return (
        '<div class="price-card">' +
        '<div class="pair-label">' + pairTitle + " (" + deltaText + ")</div>" +
        '<div class="pair-value">' + (last.price || "N/D") + "</div>" +
        '<div style="display:flex;justify-content:space-between;align-items:center;gap:0.25rem;">' +
        badgeHtml(last.status, stTag) +
        '<small class="metric-source">' + last.source + "</small>" +
        "</div>" +
        "</div>"
      );
    }

    priceBox.innerHTML =
      '<div class="price-ticker-grid">' +
      formatPairCard(modeUsd, "BTC / USD") +
      formatPairCard(modeBob, "BTC / BOB") +
      "</div>";
  }

  function renderChartsAndReports(modeMeasurements) {
    var chartModeBadge = document.getElementById("charts-mode-badge");
    chartModeBadge.className = "badge " + (state.telemetryMode === "real" ? "badge-measured" : "badge-simulated");
    chartModeBadge.textContent = state.telemetryMode === "real" ? "SERIES REALES (SIN SIMULACIÓN)" : "SERIES SIMULADAS";

    var cpuPts = modeMeasurements.filter(function (m) {
      return m.metric_name === "cpu_percent_total" && m.status !== "unavailable" && m.value !== null;
    });
    var hsPts = modeMeasurements.filter(function (m) {
      return m.metric_name === "hashrate_hs" && m.status !== "unavailable" && m.value !== null;
    });

    document.getElementById("chart-hardware-container").innerHTML = buildSvgLineChart(
      cpuPts.slice(-30),
      100,
      "#00d2ff",
      "%",
      "N/D — Sin muestras válidas de CPU (%) en el modo activo"
    );

    document.getElementById("chart-hashrate-container").innerHTML = buildSvgLineChart(
      hsPts.slice(-30),
      0,
      state.telemetryMode === "real" ? "#00ff9d" : "#ffb800",
      "H/s",
      state.telemetryMode === "real"
        ? "N/D — Sin fuente real de hashrate activa (datos simulados excluidos)"
        : "N/D — Sin muestras de hashrate simulado"
    );

    var modeReports = state.reports.filter(function (r) {
      return r.data_mode === state.telemetryMode;
    });
    var repBox = document.getElementById("reports-30m-box");
    var elecBox = document.getElementById("econ-electricity-box");

    if (modeReports.length === 0) {
      repBox.innerHTML = '<div class="metric-row"><span>Reportes (' + state.telemetryMode + '):</span><span>Sin reportes generados aún</span></div>';
      elecBox.innerHTML = '<div class="metric-row"><span>Coste Eléctrico:</span><span>N/D (No disponible) ' + badgeHtml("unavailable") + "</span></div>";
      return;
    }

    var latestRep = modeReports[modeReports.length - 1];
    var summaryObj = null;
    try {
      summaryObj = JSON.parse(latestRep.summary_json);
    } catch (_e) {
      summaryObj = null;
    }

    if (summaryObj && summaryObj.electricity) {
      var el = summaryObj.electricity;
      if (el.status === "unavailable" || el.electricity_cost_usd === null) {
        elecBox.innerHTML =
          '<div class="metric-row"><span>Energía Ventana (30m):</span><span class="metric-val">N/D ' + badgeHtml("unavailable") + "</span></div>" +
          '<div class="metric-row"><span>Coste Eléctrico (USD):</span><span class="metric-val" title="' + (el.quality_note || "") + '">No disponible (Sin sensor W)</span></div>';
      } else {
        elecBox.innerHTML =
          '<div class="metric-row"><span>Energía Ventana (30m):</span><span class="metric-val">' + el.total_energy_wh + " Wh " + badgeHtml(el.status) + "</span></div>" +
          '<div class="metric-row"><span>Coste Eléctrico (USD):</span><span class="metric-val">$' + el.electricity_cost_usd + " USD " + badgeHtml(el.status, "ESTIMADO") + "</span></div>";
      }
    }

    repBox.innerHTML =
      '<div class="metric-row"><span>ID Ventana:</span><span class="metric-val">' + latestRep.id + "</span></div>" +
      '<div class="metric-row"><span>Modo del Reporte:</span><span>' + badgeHtml(latestRep.data_mode === "real" ? "measured" : "simulated", latestRep.data_mode.toUpperCase()) + "</span></div>" +
      '<div class="metric-row"><span>Cobertura Muestreo:</span><span class="metric-val">' + latestRep.sample_coverage_pct + "% (Huecos: " + latestRep.gaps_count + ")</span></div>" +
      '<div class="metric-row"><span>Intervalo UTC:</span><span class="metric-val">' + latestRep.window_start_utc.slice(11, 16) + " → " + latestRep.window_end_utc.slice(11, 16) + " UTC</span></div>";
  }

  function renderDashboard() {
    var modeMeasurements = filterByTelemetryMode(state.measurements, state.telemetryMode);
    var latest = Object.create(null);
    for (var i = 0; i < modeMeasurements.length; i++) {
      var item = modeMeasurements[i];
      latest[item.metric_name] = item;
    }

    document.getElementById("resources-percent-list").innerHTML =
      formatMetricRow("CPU Total", latest["cpu_percent_total"], true) +
      formatMetricRow("RAM Uso", latest["ram_usage_percent"], true) +
      formatMetricRow("iGPU Radeon", latest["gpu_util_percent"], true);

    document.getElementById("resources-mib-list").innerHTML =
      formatMetricRow("RAM Usada", latest["ram_used_mib"], false) +
      formatMetricRow("RAM Disponible", latest["ram_available_mib"], false) +
      formatMetricRow("CPU Frecuencia", latest["cpu_freq_mhz"], false);

    document.getElementById("resources-temp-list").innerHTML =
      formatMetricRow("CPU Tctl/Tdie", latest["cpu_temp_c"], false) +
      formatMetricRow("iGPU Temp", latest["gpu_temp_c"], false);

    document.getElementById("resources-power-list").innerHTML =
      formatMetricRow("Potencia Paquete", latest["cpu_package_power_w"], false) +
      formatMetricRow("Energía Acumulada", latest["energy_consumed_wh"], false);

    renderMiningCore(latest);

    var modeRewards = filterByTelemetryMode(state.rewards, state.telemetryMode);
    var modePayments = filterByTelemetryMode(state.payments, state.telemetryMode);

    var estRewards = modeRewards.filter(function (r) { return r.reward_stage === "estimated"; });
    var poolRewards = modeRewards.filter(function (r) { return r.reward_stage === "pool_reported"; });
    var payouts = modePayments.filter(function (p) { return p.event_type === "payout_issued"; });
    var deposits = modePayments.filter(function (p) { return p.event_type === "deposit_detected"; });

    var lastEst = estRewards.length ? estRewards[estRewards.length - 1] : null;
    var lastPool = poolRewards.length ? poolRewards[poolRewards.length - 1] : null;

    document.getElementById("fin-estimated").innerHTML = lastEst
      ? (lastEst.amount_btc + " BTC " + badgeHtml("estimated", "ESTIMADO") + (lastEst.status === "simulated" ? " " + badgeHtml("simulated", "SIMULADO") : ""))
      : ("No disponible " + badgeHtml("unavailable"));

    document.getElementById("fin-pool-reported").innerHTML = lastPool
      ? (lastPool.amount_btc + " BTC " + badgeHtml(lastPool.status, lastPool.status === "simulated" ? "SIMULADO" : lastPool.status))
      : ("No disponible " + badgeHtml("unavailable"));

    document.getElementById("fin-payout-issued").innerHTML =
      payouts.length + " eventos emitidos " + (payouts.length ? badgeHtml(payouts[payouts.length - 1].data_status) : "");

    document.getElementById("fin-deposit-detected").innerHTML =
      deposits.length + " depósitos en Binance " + (deposits.length ? badgeHtml(deposits[deposits.length - 1].data_status) : "");

    var reconEl = document.getElementById("fin-reconciliation-val");
    if (state.reconciliation) {
      var cfgText = state.reconciliation.binance_configured ? "API Read-Only Configurada" : "Modo Desconectado";
      reconEl.textContent = cfgText + " · Conciliados: " + state.reconciliation.matched_count;
    }

    var sup = state.supervisorStatus;
    if (sup) {
      var supModeEl = document.getElementById("sup-mode-badge");
      var supAuthEl = document.getElementById("sup-auth-state");
      var supCapsEl = document.getElementById("sup-capabilities-status");
      var supConnEl = document.getElementById("sup-connector-state");
      var payoutCfgEl = document.getElementById("payout-config-status");
      if (supModeEl) {
        var modeBadgeKind = sup.mode === "THERMAL_ALERT_UNCONTROLLED" || sup.mode === "EXTERNAL_OVERRIDE_CONFLICT"
          ? "danger"
          : (sup.mode === "ACTIVE_SUPERVISION" ? "measured" : "estimated");
        supModeEl.innerHTML = badgeHtml(modeBadgeKind, sup.mode);
      }
      if (supAuthEl) {
        supAuthEl.textContent = sup.authorization_state + " (gen " + sup.authorization_generation + ")";
      }
      if (supCapsEl) {
        var capSt = sup.capabilities ? sup.capabilities.status : "UNAVAILABLE";
        supCapsEl.textContent = capSt;
      }
      if (supConnEl) {
        var opSt = sup.snapshot ? sup.snapshot.operational_state : "UNKNOWN";
        var progSt = sup.snapshot ? sup.snapshot.process_progress : "UNKNOWN";
        supConnEl.textContent = opSt + " · " + progSt;
      }
      if (payoutCfgEl && sup.payout) {
        payoutCfgEl.textContent = sup.payout.status_label || "Pendiente de definición por el usuario";
      }
    }

    renderPriceTicker();
    renderChartsAndReports(modeMeasurements);

    var filtered = modeMeasurements.filter(function (m) {
      if (state.statusFilter !== "all" && m.status !== state.statusFilter) return false;
      if (state.metricFilter !== "all" && m.metric_name !== state.metricFilter) return false;
      return true;
    });

    var tbody = document.getElementById("history-table-body");
    if (filtered.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5">Sin registros para el filtro actual (empty)</td></tr>';
    } else {
      var rows = filtered.slice(-20).reverse().map(function (m) {
        var valStr = (m.status === "unavailable" || m.value === null) ? "No disponible" : (m.value + " " + m.unit);
        return (
          "<tr>" +
          "<td>" + m.metric_name + "</td>" +
          "<td>" + valStr + "</td>" +
          "<td>" + badgeHtml(m.status, m.status === "simulated" ? "SIMULADO" : m.status) + "</td>" +
          "<td>" + m.source + "</td>" +
          "<td>" + m.observed_at_utc + "</td>" +
          "</tr>"
        );
      });
      tbody.innerHTML = rows.join("");
    }
  }

  function refreshData() {
    var banner = document.getElementById("status-banner");
    var bannerText = document.getElementById("status-banner-text");
    var bannerMeta = document.getElementById("status-banner-meta");

    Promise.all([
      fetch("/health").then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }),
      fetch("/api/v1/measurements?limit=300").then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }),
      fetch("/api/v1/rewards").then(function (r) { return r.ok ? r.json() : { items: [] }; }),
      fetch("/api/v1/payments").then(function (r) { return r.ok ? r.json() : { items: [] }; }),
      fetch("/api/v1/prices?quote_asset=USD").then(function (r) { return r.ok ? r.json() : { items: [] }; }),
      fetch("/api/v1/prices?quote_asset=BOB").then(function (r) { return r.ok ? r.json() : { items: [] }; }),
      fetch("/api/v1/reconciliation").then(function (r) { return r.ok ? r.json() : null; }),
      fetch("/api/v1/reports").then(function (r) { return r.ok ? r.json() : { items: [] }; }),
      fetch("/api/v1/sessions").then(function (r) { return r.ok ? r.json() : { active_session: null, items: [] }; }),
      fetch("/api/v1/supervisor/status").then(function (r) { return r.ok ? r.json() : null; })
    ]).then(function (results) {
      var health = results[0];
      state.telemetryMode = health.telemetry_mode || "simulated";
      state.boundHost = health.bound_host || "127.0.0.1";
      state.lastCollectionAtUtc = health.last_collection_at_utc;
      state.measurements = deduplicateMeasurements(results[1].items || []);
      state.rewards = results[2].items || [];
      state.payments = results[3].items || [];
      state.pricesUsd = results[4].items || [];
      state.pricesBob = results[5].items || [];
      state.reconciliation = results[6];
      state.reports = results[7].items || [];
      var sessionsPayload = results[8] || { active_session: null, items: [] };
      state.activeSession = sessionsPayload.active_session || null;
      state.sessions = sessionsPayload.items || [];
      state.supervisorStatus = results[9] || null;

      var modeBadge = document.getElementById("global-mode-badge");
      var isReal = state.telemetryMode === "real";
      modeBadge.className = "badge " + (isReal ? "badge-measured" : "badge-simulated");
      modeBadge.textContent = "MODO: " + (isReal ? "REAL (TELEMETRÍA LOCAL)" : "SIMULADO (DEMO)");

      banner.className = "state-banner";
      bannerText.textContent = "Conectado a API local (" + state.boundHost + ") · Modo activo: " + state.telemetryMode.toUpperCase();
      bannerMeta.textContent = "Último muestreo: " + (state.lastCollectionAtUtc || "N/D") + " · Muestras en memoria: " + state.measurements.length;

      pushLog("Sincronización completada (modo=" + state.telemetryMode + ", muestras=" + state.measurements.length + ")");
      renderDashboard();
    }).catch(function (err) {
      banner.className = "state-banner error";
      bannerText.textContent = "Error al consultar la API local: " + err.message;
      pushLog("Error de conexión con API local: " + err.message);
    });
  }

  function triggerCollectNow() {
    pushLog("Solicitando recolección manual de telemetría (POST /api/v1/collect)...");
    fetch("/api/v1/collect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
    }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (res) {
      state.lastSafety = res.safety || null;
      pushLog("Ciclo recolectado (" + res.measurements_collected + " métricas en " + res.observed_at_utc + ")");
      refreshData();
    }).catch(function (err) {
      var banner = document.getElementById("status-banner");
      var bannerText = document.getElementById("status-banner-text");
      banner.className = "state-banner error";
      bannerText.textContent = "No se pudo ejecutar la recolección manual: " + err.message;
      pushLog("Fallo en POST /api/v1/collect: " + err.message);
    });
  }

  function triggerSessionAction(action) {
    if (action === "stop" && typeof window !== "undefined" && typeof window.confirm === "function") {
      if (!window.confirm("¿Confirmas que deseas detener la sesión simulada actual?")) {
        return;
      }
    }
    var endpoint = "/api/v1/sessions/" + action;
    pushLog("Ejecutando acción de sesión simulada (" + endpoint + ")...");
    fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
    }).then(function (r) {
      return r.json().then(function (payload) {
        if (!r.ok) {
          throw new Error(payload.detail || ("HTTP " + r.status));
        }
        return payload;
      });
    }).then(function (res) {
      var item = res.item || null;
      if (item) {
        pushLog("Sesión " + item.id + " actualizada a estado: " + item.session_state.toUpperCase());
      }
      refreshData();
    }).catch(function (err) {
      var banner = document.getElementById("status-banner");
      var bannerText = document.getElementById("status-banner-text");
      banner.className = "state-banner error";
      bannerText.textContent = "Operación de sesión rechazada: " + err.message;
      pushLog("Error en " + endpoint + ": " + err.message);
    });
  }

  function setupNavigation() {
    var navBtns = document.querySelectorAll(".nav-btn");
    var leftPanel = document.getElementById("panel-left-resources");
    var centerPanel = document.getElementById("panel-center-session");
    var rightPanel = document.getElementById("panel-right-market");
    var bottomPanel = document.getElementById("panel-bottom-analytics");
    var drawer = document.getElementById("telemetry-details-drawer");

    function applyView(viewName) {
      leftPanel.classList.remove("hidden-view");
      centerPanel.classList.remove("hidden-view");
      rightPanel.classList.remove("hidden-view");
      bottomPanel.classList.remove("hidden-view");

      if (viewName === "mining") {
        leftPanel.classList.add("hidden-view");
        rightPanel.classList.add("hidden-view");
      } else if (viewName === "hardware") {
        centerPanel.classList.add("hidden-view");
        rightPanel.classList.add("hidden-view");
      } else if (viewName === "economics") {
        leftPanel.classList.add("hidden-view");
        centerPanel.classList.add("hidden-view");
      } else if (viewName === "reports") {
        if (drawer) drawer.open = true;
      }
    }

    for (var i = 0; i < navBtns.length; i++) {
      navBtns[i].addEventListener("click", function (ev) {
        for (var j = 0; j < navBtns.length; j++) {
          navBtns[j].classList.remove("active");
        }
        ev.currentTarget.classList.add("active");
        applyView(ev.currentTarget.getAttribute("data-nav-view"));
      });
    }
  }

  document.getElementById("filter-status").addEventListener("change", function (e) {
    state.statusFilter = e.target.value;
    renderDashboard();
  });
  document.getElementById("filter-metric").addEventListener("change", function (e) {
    state.metricFilter = e.target.value;
    renderDashboard();
  });
  document.getElementById("btn-refresh").addEventListener("click", refreshData);
  var btnCollect = document.getElementById("btn-collect");
  if (btnCollect) {
    btnCollect.addEventListener("click", triggerCollectNow);
  }
  var btnSimStart = document.getElementById("btn-sim-start");
  if (btnSimStart) {
    btnSimStart.addEventListener("click", function () { triggerSessionAction("start"); });
  }
  var btnSimPause = document.getElementById("btn-sim-pause");
  if (btnSimPause) {
    btnSimPause.addEventListener("click", function () { triggerSessionAction("pause"); });
  }
  var btnSimResume = document.getElementById("btn-sim-resume");
  if (btnSimResume) {
    btnSimResume.addEventListener("click", function () { triggerSessionAction("resume"); });
  }
  var btnSimStop = document.getElementById("btn-sim-stop");
  if (btnSimStop) {
    btnSimStop.addEventListener("click", function () { triggerSessionAction("stop"); });
  }

  setupNavigation();
  refreshData();
})();
"""

