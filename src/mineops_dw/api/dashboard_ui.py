"""Responsive localhost HTML/JS dashboard assets served by MineOpsApiService."""

from __future__ import annotations

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>MineOps DW — Dashboard Local Experimental</title>
  <style>
    :root {
      --bg: #0f172a;
      --card: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --muted: #94a3b8;
      --measured: #10b981;
      --estimated: #3b82f6;
      --simulated: #f59e0b;
      --unavailable: #64748b;
      --danger: #ef4444;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }
    header {
      padding: 1rem 1.5rem;
      border-bottom: 1px solid var(--border);
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 1rem;
    }
    .badge {
      display: inline-block;
      padding: 0.15rem 0.55rem;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 700;
      text-transform: uppercase;
    }
    .badge-measured { background: rgba(16,185,129,0.2); color: #34d399; border: 1px solid var(--measured); }
    .badge-estimated { background: rgba(59,130,246,0.2); color: #60a5fa; border: 1px solid var(--estimated); }
    .badge-simulated { background: rgba(245,158,11,0.2); color: #fbbf24; border: 1px solid var(--simulated); }
    .badge-unavailable { background: rgba(100,116,139,0.2); color: #cbd5e1; border: 1px solid var(--unavailable); }
    .dashboard-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 1.25rem;
      padding: 1.25rem;
    }
    @media (max-width: 960px) {
      .dashboard-grid {
        grid-template-columns: 1fr;
      }
    }
    section.panel {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 0.75rem;
      padding: 1.1rem;
    }
    h1 { font-size: 1.25rem; margin: 0; }
    h2 { font-size: 1.05rem; margin-top: 0; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }
    h3 { font-size: 0.9rem; color: var(--muted); margin: 0.85rem 0 0.4rem; }
    .unit-card {
      background: rgba(15,23,42,0.55);
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
      border-bottom: 1px dashed rgba(148,163,184,0.15);
    }
    .state-banner {
      margin: 0.75rem 1.25rem 0;
      padding: 0.75rem 1rem;
      border-radius: 0.5rem;
      background: rgba(59,130,246,0.15);
      border: 1px solid var(--estimated);
    }
    .state-banner.error {
      background: rgba(239,68,68,0.18);
      border-color: var(--danger);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
    }
    th, td {
      text-align: left;
      padding: 0.4rem;
      border-bottom: 1px solid var(--border);
    }
    .filter-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin-bottom: 0.75rem;
    }
    select, button {
      background: var(--bg);
      color: var(--text);
      border: 1px solid var(--border);
      padding: 0.35rem 0.6rem;
      border-radius: 0.375rem;
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>MineOps DW — Monitor Experimental de Telemetría y Conciliación</h1>
      <small>Hardware objetivo: AMD Ryzen 5 5600GT + Radeon Graphics (Solo lectura local 127.0.0.1)</small>
    </div>
    <div>
      <span id="global-mode-badge" class="badge badge-simulated" aria-live="polite">MODO: CARGANDO</span>
      <button id="btn-refresh" type="button" aria-label="Actualizar datos ahora">Actualizar</button>
    </div>
  </header>

  <div id="status-banner" class="state-banner" role="status" aria-live="polite">
    Cargando datos desde la API local...
  </div>

  <main class="dashboard-grid" role="main">
    <!-- Panel Izquierdo: Recursos del PC -->
    <section id="panel-left-resources" class="panel" aria-labelledby="heading-resources">
      <h2 id="heading-resources">Panel Izquierdo — Recursos del PC</h2>

      <!-- Gráfico/Grupo exclusivo de porcentajes (nunca mezcla W ni °C) -->
      <div class="unit-card" data-unit-group="percent" aria-label="Indicadores de porcentaje">
        <h3>Carga de Cómputo y Memoria (Unidad: %)</h3>
        <div id="resources-percent-list"></div>
      </div>

      <!-- Grupo exclusivo de Memoria en MiB -->
      <div class="unit-card" data-unit-group="memory-mib" aria-label="Indicadores de memoria en MiB">
        <h3>Memoria Física (Unidad: MiB)</h3>
        <div id="resources-mib-list"></div>
      </div>

      <!-- Grupo exclusivo Térmico (°C) -->
      <div class="unit-card" data-unit-group="temperature-c" aria-label="Indicadores térmicos en grados Celsius">
        <h3>Sensores Térmicos (Unidad: °C)</h3>
        <div id="resources-temp-list"></div>
      </div>

      <!-- Grupo exclusivo Eléctrico (W y Wh separados de %) -->
      <div class="unit-card" data-unit-group="power-energy" aria-label="Indicadores de potencia y energía">
        <h3>Potencia (W) y Energía Estimada (Wh)</h3>
        <div id="resources-power-list"></div>
      </div>
    </section>

    <!-- Panel Central: Estado de Sesión/Minería y 4 Estados Financieros -->
    <section id="panel-center-session" class="panel" aria-labelledby="heading-session">
      <h2 id="heading-session">Panel Central — Sesión de Minería y Conciliación</h2>
      <div class="unit-card">
        <h3>Rendimiento Experimental (Unidad: H/s)</h3>
        <div id="session-hashrate-box"></div>
      </div>

      <div class="unit-card" aria-label="Cuatro estados financieros desacoplados">
        <h3>Separación Estricta de Estados Financieros (BTC)</h3>
        <div class="metric-row">
          <span>1. Recompensa Estimada (Cálculo Local):</span>
          <strong id="fin-estimated">No disponible</strong>
        </div>
        <div class="metric-row">
          <span>2. Saldo Pendiente Informado por Pool:</span>
          <strong id="fin-pool-reported">No disponible</strong>
        </div>
        <div class="metric-row">
          <span>3. Pagos Emitidos por Pool (payout_issued):</span>
          <strong id="fin-payout-issued">0 eventos</strong>
        </div>
        <div class="metric-row">
          <span>4. Depósitos Detectados en Binance (Read-Only):</span>
          <strong id="fin-deposit-detected">0 eventos</strong>
        </div>
      </div>
    </section>

    <!-- Panel Derecho: Precio BTC, Variación e Historial con Filtros -->
    <section id="panel-right-market" class="panel" aria-labelledby="heading-market">
      <h2 id="heading-market">Panel Derecho — Precio BTC, Variación e Historial</h2>
      <div class="unit-card">
        <h3>Cotización de Mercado BTC y Variación</h3>
        <div id="market-price-box">Sin datos de precio (empty)</div>
      </div>

      <div class="unit-card">
        <h3>Historial de Muestras (Deduplicado)</h3>
        <div class="filter-bar">
          <label for="filter-status">Calidad:</label>
          <select id="filter-status" aria-label="Filtrar por estado de calidad">
            <option value="all">Todos</option>
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
              <th>Hora (Local / UTC)</th>
            </tr>
          </thead>
          <tbody id="history-table-body">
            <tr><td colspan="4">Sin registros (empty)</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>

  <script src="/dashboard.js"></script>
</body>
</html>
"""

DASHBOARD_JS = """(function () {
  "use strict";

  var state = {
    measurements: [],
    rewards: [],
    payments: [],
    prices: [],
    statusFilter: "all",
    metricFilter: "all"
  };

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

  function badgeHtml(status) {
    var safeStatus = status || "unavailable";
    return '<span class="badge badge-' + safeStatus + '">' + safeStatus + "</span>";
  }

  function formatMetricRow(label, m) {
    if (!m || m.status === "unavailable" || m.value === null) {
      var note = (m && m.quality_note) ? m.quality_note : "Sensor no disponible";
      return (
        '<div class="metric-row">' +
        "<span>" + label + "</span>" +
        '<span title="' + note + '">No disponible ' + badgeHtml("unavailable") + "</span>" +
        "</div>"
      );
    }
    return (
      '<div class="metric-row">' +
      "<span>" + label + "</span>" +
      "<span><strong>" + m.value + " " + m.unit + "</strong> " + badgeHtml(m.status) + "</span>" +
      "</div>"
    );
  }

  function renderDashboard() {
    var latest = Object.create(null);
    for (var i = 0; i < state.measurements.length; i++) {
      var item = state.measurements[i];
      latest[item.metric_name] = item;
    }

    document.getElementById("resources-percent-list").innerHTML =
      formatMetricRow("CPU Total", latest["cpu_percent_total"]) +
      formatMetricRow("RAM Uso", latest["ram_usage_percent"]) +
      formatMetricRow("iGPU Radeon", latest["gpu_util_percent"]);

    document.getElementById("resources-mib-list").innerHTML =
      formatMetricRow("RAM Usada", latest["ram_used_mib"]) +
      formatMetricRow("RAM Disponible", latest["ram_available_mib"]);

    document.getElementById("resources-temp-list").innerHTML =
      formatMetricRow("CPU Tctl/Tdie", latest["cpu_temp_c"]) +
      formatMetricRow("iGPU Temp", latest["gpu_temp_c"]);

    document.getElementById("resources-power-list").innerHTML =
      formatMetricRow("Potencia Paquete", latest["cpu_package_power_w"]) +
      formatMetricRow("Energía Acumulada", latest["energy_consumed_wh"]);

    document.getElementById("session-hashrate-box").innerHTML =
      formatMetricRow("Hashrate Experimental", latest["hashrate_hs"]);

    var estRewards = state.rewards.filter(function (r) { return r.reward_stage === "estimated"; });
    var poolRewards = state.rewards.filter(function (r) { return r.reward_stage === "pool_reported"; });
    var payouts = state.payments.filter(function (p) { return p.event_type === "payout_issued"; });
    var deposits = state.payments.filter(function (p) { return p.event_type === "deposit_detected"; });

    var lastEst = estRewards.length ? estRewards[estRewards.length - 1] : null;
    var lastPool = poolRewards.length ? poolRewards[poolRewards.length - 1] : null;

    document.getElementById("fin-estimated").innerHTML =
      lastEst ? (lastEst.amount_btc + " BTC " + badgeHtml(lastEst.status)) : ("No disponible " + badgeHtml("unavailable"));
    document.getElementById("fin-pool-reported").innerHTML =
      lastPool ? (lastPool.amount_btc + " BTC " + badgeHtml(lastPool.status)) : ("No disponible " + badgeHtml("unavailable"));
    document.getElementById("fin-payout-issued").textContent = payouts.length + " eventos emitidos";
    document.getElementById("fin-deposit-detected").textContent = deposits.length + " depósitos en Binance";

    var priceBox = document.getElementById("market-price-box");
    if (state.prices.length === 0) {
      priceBox.textContent = "Sin cotizaciones registradas (empty)";
    } else {
      var lastPrice = state.prices[state.prices.length - 1];
      var prevPrice = state.prices.length > 1 ? state.prices[state.prices.length - 2] : null;
      var deltaText = "0.00%";
      if (prevPrice && prevPrice.price && lastPrice.price) {
        var p0 = parseFloat(prevPrice.price);
        var p1 = parseFloat(lastPrice.price);
        if (p0 > 0) {
          deltaText = (((p1 - p0) / p0) * 100).toFixed(2) + "%";
        }
      }
      priceBox.innerHTML =
        '<div class="metric-row"><span>BTC / ' + lastPrice.quote_asset + ':</span>' +
        "<strong>" + (lastPrice.price || "No disponible") + " (" + deltaText + ") " + badgeHtml(lastPrice.status) + "</strong></div>";
    }

    var filtered = state.measurements.filter(function (m) {
      if (state.statusFilter !== "all" && m.status !== state.statusFilter) return false;
      if (state.metricFilter !== "all" && m.metric_name !== state.metricFilter) return false;
      return true;
    });

    var tbody = document.getElementById("history-table-body");
    if (filtered.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4">Sin registros para el filtro actual (empty)</td></tr>';
    } else {
      var rows = filtered.slice(-15).reverse().map(function (m) {
        var valStr = (m.status === "unavailable" || m.value === null) ? "No disponible" : (m.value + " " + m.unit);
        return (
          "<tr>" +
          "<td>" + m.metric_name + "</td>" +
          "<td>" + valStr + "</td>" +
          "<td>" + badgeHtml(m.status) + "</td>" +
          "<td>" + m.observed_at_utc + "</td>" +
          "</tr>"
        );
      });
      tbody.innerHTML = rows.join("");
    }
  }

  function refreshData() {
    var banner = document.getElementById("status-banner");
    Promise.all([
      fetch("/health").then(function (r) { return r.json(); }),
      fetch("/api/v1/measurements?limit=200").then(function (r) { return r.json(); }),
      fetch("/api/v1/rewards").then(function (r) { return r.json(); }),
      fetch("/api/v1/payments").then(function (r) { return r.json(); }),
      fetch("/api/v1/prices?quote_asset=USD").then(function (r) { return r.json(); })
    ]).then(function (results) {
      var health = results[0];
      state.measurements = deduplicateMeasurements(results[1].items || []);
      state.rewards = results[2].items || [];
      state.payments = results[3].items || [];
      state.prices = results[4].items || [];

      var modeBadge = document.getElementById("global-mode-badge");
      modeBadge.textContent = "MODO: " + (health.telemetry_mode || "simulated").toUpperCase();
      banner.className = "state-banner";
      banner.textContent = "Conectado a API local (" + health.bound_host + "). Muestras únicas: " + state.measurements.length;
      renderDashboard();
    }).catch(function (err) {
      banner.className = "state-banner error";
      banner.textContent = "Error al consultar la API local: " + err.message;
    });
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

  refreshData();
})();
"""
