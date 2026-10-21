/**
 * Shared TypeScript contracts matching MineOps DW OpenAPI 3.1.0 schemas.
 * Enforces explicit handling of nullable values and quality statuses.
 */

export type QualityStatus = "measured" | "estimated" | "unavailable" | "simulated";
export type SessionState = "idle" | "running" | "paused" | "stopped" | "error";
export type DataMode = "simulated" | "real";
export type RewardStage = "estimated" | "pool_reported";
export type PaymentEventType = "payout_issued" | "deposit_detected" | "reconciliation";
export type SettlementStatus = "pending" | "confirmed" | "failed" | "unknown";

export interface Measurement {
  id: number | null;
  session_id: string | null;
  metric_name: string;
  value: number | null;
  unit: "%" | "MiB" | "MHz" | "°C" | "W" | "Wh" | "H/s" | string;
  status: QualityStatus;
  source: string;
  observed_at_utc: string;
  quality_note: string | null;
}

export interface MiningSession {
  id: string;
  started_at_utc: string;
  ended_at_utc: string | null;
  session_state: SessionState;
  data_mode: DataMode;
  miner_name: string | null;
  pool_name: string | null;
  stop_reason: string | null;
}

export interface PoolShare {
  id: string;
  session_id: string;
  accepted: boolean;
  difficulty: number | null;
  reject_reason: string | null;
  status: "measured" | "simulated";
  source: string;
  observed_at_utc: string;
}

export interface RewardSnapshot {
  id: string;
  session_id: string | null;
  amount_btc: string;
  reward_stage: RewardStage;
  status: QualityStatus;
  source: string;
  observed_at_utc: string;
}

export interface PriceSnapshot {
  id: string;
  asset: string;
  quote_asset: string;
  price: string | null;
  status: "measured" | "unavailable" | "simulated";
  source: string;
  observed_at_utc: string;
}

export interface PaymentEvent {
  id: string;
  event_type: PaymentEventType;
  asset: string;
  amount: string;
  network_fee: string | null;
  settlement_status: SettlementStatus;
  data_status: "measured" | "simulated";
  source: string;
  external_reference: string | null;
  observed_at_utc: string;
}

/**
 * Format a Measurement without ever turning null/unavailable into 0.
 */
export function formatMeasurementValue(m: Measurement | undefined): string {
  if (!m || m.status === "unavailable" || m.value === null) {
    return "No disponible (unavailable)";
  }
  return `${m.value} ${m.unit}`;
}

/**
 * Deduplicate measurements by natural key (metric_name + source + observed_at_utc).
 */
export function deduplicateMeasurements(items: readonly Measurement[]): Measurement[] {
  const seen = new Set<string>();
  const result: Measurement[] = [];
  for (const item of items) {
    const key = `${item.metric_name}|${item.source}|${item.observed_at_utc}`;
    if (!seen.has(key)) {
      seen.add(key);
      result.push(item);
    }
  }
  return result;
}
