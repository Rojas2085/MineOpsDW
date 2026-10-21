import React, { useEffect, useMemo, useState } from "react";
import {
  Measurement,
  PaymentEvent,
  PriceSnapshot,
  QualityStatus,
  RewardSnapshot,
  deduplicateMeasurements,
  formatMeasurementValue,
} from "./types/api";

export const App: React.FC = () => {
  const [measurements, setMeasurements] = useState<Measurement[]>([]);
  const [rewards, setRewards] = useState<RewardSnapshot[]>([]);
  const [payments, setPayments] = useState<PaymentEvent[]>([]);
  const [prices, setPrices] = useState<PriceSnapshot[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<QualityStatus | "all">("all");
  const [metricFilter, setMetricFilter] = useState<string>("all");

  useEffect(() => {
    let active = true;
    const fetchDashboardData = async () => {
      try {
        const [mRes, rRes, pRes, prRes] = await Promise.all([
          fetch("/api/v1/measurements?limit=200"),
          fetch("/api/v1/rewards"),
          fetch("/api/v1/payments"),
          fetch("/api/v1/prices?quote_asset=USD"),
        ]);
        if (!mRes.ok || !rRes.ok || !pRes.ok || !prRes.ok) {
          throw new Error("Error al consultar la API local en 127.0.0.1");
        }
        const [mJson, rJson, pJson, prJson] = await Promise.all([
          mRes.json(),
          rRes.json(),
          pRes.json(),
          prRes.json(),
        ]);
        if (!active) return;
        setMeasurements(deduplicateMeasurements(mJson.items ?? []));
        setRewards(rJson.items ?? []);
        setPayments(pJson.items ?? []);
        setPrices(prJson.items ?? []);
        setError(null);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Error desconocido");
      } finally {
        if (active) setLoading(false);
      }
    };

    void fetchDashboardData();
    const timer = window.setInterval(() => void fetchDashboardData(), 10000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const latestByMetric = useMemo(() => {
    const map = new Map<string, Measurement>();
    for (const m of measurements) {
      map.set(m.metric_name, m);
    }
    return map;
  }, [measurements]);

  const filteredMeasurements = useMemo(() => {
    return measurements.filter((m) => {
      if (statusFilter !== "all" && m.status !== statusFilter) return false;
      if (metricFilter !== "all" && m.metric_name !== metricFilter) return false;
      return true;
    });
  }, [measurements, statusFilter, metricFilter]);

  const latestEstimatedReward = rewards.filter((r) => r.reward_stage === "estimated").at(-1);
  const latestPoolBalance = rewards.filter((r) => r.reward_stage === "pool_reported").at(-1);
  const payoutsIssued = payments.filter((p) => p.event_type === "payout_issued");
  const depositsDetected = payments.filter((p) => p.event_type === "deposit_detected");

  return (
    <main className="dashboard-layout" aria-live="polite">
      {loading && <div role="status">Cargando telemetría local...</div>}
      {error && <div role="alert" className="alert-error">{error}</div>}

      <div className="dashboard-grid">
        {/* Panel Izquierdo: Recursos del PC (unidades estrictamente separadas) */}
        <section id="panel-resources" aria-label="Panel izquierdo: Recursos del PC">
          <h2>Recursos del PC</h2>
          <div className="unit-group" data-unit="%">
            <h3>Utilización (%) — Gráfico circular solo para porcentajes</h3>
            <p>CPU Total: {formatMeasurementValue(latestByMetric.get("cpu_percent_total"))}</p>
            <p>RAM Uso: {formatMeasurementValue(latestByMetric.get("ram_usage_percent"))}</p>
            <p>iGPU Radeon: {formatMeasurementValue(latestByMetric.get("gpu_util_percent"))}</p>
          </div>
          <div className="unit-group" data-unit="°C">
            <h3>Temperatura (°C)</h3>
            <p>CPU Tctl/Tdie: {formatMeasurementValue(latestByMetric.get("cpu_temp_c"))}</p>
            <p>iGPU Temp: {formatMeasurementValue(latestByMetric.get("gpu_temp_c"))}</p>
          </div>
          <div className="unit-group" data-unit="W-Wh">
            <h3>Potencia (W) y Energía (Wh) — Separadas de porcentajes</h3>
            <p>Potencia Paquete: {formatMeasurementValue(latestByMetric.get("cpu_package_power_w"))}</p>
            <p>Energía Ventana: {formatMeasurementValue(latestByMetric.get("energy_consumed_wh"))}</p>
          </div>
        </section>

        {/* Panel Central: Estado de Sesión/Minería y 4 Estados Financieros */}
        <section id="panel-mining-session" aria-label="Panel central: Estado de sesión y minería">
          <h2>Estado de Sesión y Conciliación (4 Estados Separados)</h2>
          <p>Hashrate: {formatMeasurementValue(latestByMetric.get("hashrate_hs"))}</p>
          <ul>
            <li>1. Recompensa Estimada (Local): {latestEstimatedReward?.amount_btc ?? "0"} BTC ({latestEstimatedReward?.status ?? "unavailable"})</li>
            <li>2. Saldo Pendiente en Pool: {latestPoolBalance?.amount_btc ?? "0"} BTC ({latestPoolBalance?.status ?? "unavailable"})</li>
            <li>3. Pagos Emitidos por Pool: {payoutsIssued.length} eventos</li>
            <li>4. Depósitos Confirmados en Binance: {depositsDetected.length} eventos</li>
          </ul>
        </section>

        {/* Panel Derecho: Precio BTC, Variación e Historial con Filtros */}
        <section id="panel-market-price" aria-label="Panel derecho: Precio BTC e historial">
          <h2>Precio BTC y Variación</h2>
          {prices.length === 0 ? (
            <p className="empty-state">Sin cotizaciones registradas (empty)</p>
          ) : (
            <p>BTC/USD: {prices.at(-1)?.price ?? "unavailable"} ({prices.at(-1)?.status})</p>
          )}

          <h3>Historial y Filtros de Calidad</h3>
          <label>
            Estado de calidad:
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as QualityStatus | "all")}>
              <option value="all">Todos</option>
              <option value="measured">measured</option>
              <option value="estimated">estimated</option>
              <option value="unavailable">unavailable</option>
              <option value="simulated">simulated</option>
            </select>
          </label>
          <label>
            Métrica:
            <input value={metricFilter} onChange={(e) => setMetricFilter(e.target.value)} />
          </label>
          <p>Muestras visibles (sin duplicados): {filteredMeasurements.length}</p>
        </section>
      </div>
    </main>
  );
};
export default App;
