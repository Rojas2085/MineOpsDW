"""Domain entities and quality invariants for MineOps DW."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

QualityStatus = Literal["measured", "estimated", "unavailable", "simulated"]
SessionState = Literal["idle", "running", "paused", "stopped", "error"]
DataMode = Literal["simulated", "real"]
RewardStage = Literal["estimated", "pool_reported"]
PaymentEventType = Literal["payout_issued", "deposit_detected", "reconciliation"]
SettlementStatus = Literal["pending", "confirmed", "failed", "unknown"]


def normalize_utc_timestamp(value: datetime | str) -> str:
    """Normalize a datetime or ISO-8601 string into a canonical UTC ISO-8601 string ('...Z')."""
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        dt = datetime.fromisoformat(cleaned)
    elif isinstance(value, datetime):
        dt = value
    else:
        raise TypeError("Timestamp must be a datetime instance or ISO-8601 string.")

    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError("Timestamp must be timezone-aware (UTC required).")

    utc_dt = dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def normalize_decimal_str(value: Decimal | str | int, *, allow_negative: bool = False) -> str:
    """Validate and format a monetary/crypto amount as an exact decimal string without float."""
    if isinstance(value, float):
        raise ValueError("Binary float is forbidden for financial/crypto amounts; use Decimal or str.")
    try:
        dec = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc

    if not dec.is_finite():
        raise ValueError("Decimal amount must be finite.")
    if not allow_negative and dec < Decimal("0"):
        raise ValueError("Amount cannot be negative.")

    formatted = format(dec.normalize(), "f")
    return formatted if formatted != "-0" else "0"


class Measurement(BaseModel):
    """A single hardware or telemetry sample with mandatory provenance and quality status."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int | None = None
    session_id: str | None = None
    metric_name: str = Field(min_length=1)
    value: float | None = None
    unit: str = Field(min_length=1)
    status: QualityStatus
    source: str = Field(min_length=1)
    observed_at_utc: str
    quality_note: str | None = None

    @field_validator("metric_name", "unit", "source")
    @classmethod
    def _strip_non_empty(cls, val: str) -> str:
        cleaned = val.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace.")
        return cleaned

    @field_validator("observed_at_utc", mode="before")
    @classmethod
    def _validate_utc(cls, val: datetime | str) -> str:
        return normalize_utc_timestamp(val)

    @model_validator(mode="after")
    def _enforce_quality_invariants(self) -> Measurement:
        if self.status == "unavailable":
            if self.value is not None:
                raise ValueError(
                    "When status is 'unavailable', value must be None (never 0 or fake value)."
                )
            if not self.quality_note or not self.quality_note.strip():
                raise ValueError(
                    "When status is 'unavailable', quality_note must explain the cause."
                )
        else:
            if self.value is None:
                raise ValueError(
                    f"When status is '{self.status}', value must be a numeric observation."
                )
            if self.unit == "%" and not (0.0 <= self.value <= 100.0):
                raise ValueError(
                    f"Percentage metric '{self.metric_name}' out of physical range [0, 100]: {self.value}"
                )
            if self.unit in {"W", "Wh", "MiB", "MHz", "H/s"} and self.value < 0.0:
                raise ValueError(
                    f"Metric '{self.metric_name}' ({self.unit}) cannot be negative: {self.value}"
                )
        return self


class MiningSession(BaseModel):
    """Represents a simulated or real experimental mining session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    started_at_utc: str
    ended_at_utc: str | None = None
    session_state: SessionState
    data_mode: DataMode
    miner_name: str | None = None
    pool_name: str | None = None
    stop_reason: str | None = None

    @field_validator("started_at_utc", mode="before")
    @classmethod
    def _validate_started_utc(cls, val: datetime | str) -> str:
        return normalize_utc_timestamp(val)

    @field_validator("ended_at_utc", mode="before")
    @classmethod
    def _validate_ended_utc(cls, val: datetime | str | None) -> str | None:
        if val is None:
            return None
        return normalize_utc_timestamp(val)

    @model_validator(mode="after")
    def _validate_session_rules(self) -> MiningSession:
        if self.data_mode == "simulated" and not self.id.startswith("sim_"):
            raise ValueError("Simulated MiningSession id must start with prefix 'sim_'.")
        if self.ended_at_utc is not None and self.ended_at_utc < self.started_at_utc:
            raise ValueError("ended_at_utc cannot be earlier than started_at_utc.")
        return self


class PoolShare(BaseModel):
    """Represents a share submitted to a mining pool (real or simulated)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    accepted: bool
    difficulty: float | None = Field(default=None, gt=0.0)
    reject_reason: str | None = None
    status: Literal["measured", "simulated"]
    source: str = Field(min_length=1)
    observed_at_utc: str

    @field_validator("observed_at_utc", mode="before")
    @classmethod
    def _validate_utc(cls, val: datetime | str) -> str:
        return normalize_utc_timestamp(val)

    @model_validator(mode="after")
    def _validate_rejection(self) -> PoolShare:
        if not self.accepted and (not self.reject_reason or not self.reject_reason.strip()):
            raise ValueError("Rejected PoolShare must include an explicit reject_reason.")
        return self


class RewardSnapshot(BaseModel):
    """Represents either a local estimated reward or a pool-reported unconfirmed balance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    session_id: str | None = None
    amount_btc: str
    reward_stage: RewardStage
    status: QualityStatus
    source: str = Field(min_length=1)
    observed_at_utc: str

    @field_validator("amount_btc", mode="before")
    @classmethod
    def _validate_btc_amount(cls, val: Decimal | str | int) -> str:
        return normalize_decimal_str(val, allow_negative=False)

    @field_validator("observed_at_utc", mode="before")
    @classmethod
    def _validate_utc(cls, val: datetime | str) -> str:
        return normalize_utc_timestamp(val)


class PriceSnapshot(BaseModel):
    """Market price snapshot for BTC in USD, BOB, or USDT."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    asset: str = Field(default="BTC", min_length=1)
    quote_asset: str = Field(min_length=1)
    price: str | None = None
    status: Literal["measured", "unavailable", "simulated"]
    source: str = Field(min_length=1)
    observed_at_utc: str

    @field_validator("price", mode="before")
    @classmethod
    def _validate_price(cls, val: Decimal | str | int | None) -> str | None:
        if val is None:
            return None
        return normalize_decimal_str(val, allow_negative=False)

    @field_validator("observed_at_utc", mode="before")
    @classmethod
    def _validate_utc(cls, val: datetime | str) -> str:
        return normalize_utc_timestamp(val)

    @model_validator(mode="after")
    def _validate_price_availability(self) -> PriceSnapshot:
        if self.status == "unavailable" and self.price is not None:
            raise ValueError("Unavailable PriceSnapshot must have price=None.")
        if self.status != "unavailable" and self.price is None:
            raise ValueError(f"PriceSnapshot with status='{self.status}' requires a price.")
        return self


class PaymentEvent(BaseModel):
    """Represents a pool payout emission, a Binance deposit detection, or reconciliation event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    event_type: PaymentEventType
    asset: str = Field(default="BTC", min_length=1)
    amount: str
    network_fee: str | None = None
    settlement_status: SettlementStatus
    data_status: Literal["measured", "simulated"]
    source: str = Field(min_length=1)
    external_reference: str | None = None
    observed_at_utc: str

    @field_validator("amount", mode="before")
    @classmethod
    def _validate_amount(cls, val: Decimal | str | int) -> str:
        return normalize_decimal_str(val, allow_negative=False)

    @field_validator("network_fee", mode="before")
    @classmethod
    def _validate_fee(cls, val: Decimal | str | int | None) -> str | None:
        if val is None:
            return None
        return normalize_decimal_str(val, allow_negative=False)

    @field_validator("observed_at_utc", mode="before")
    @classmethod
    def _validate_utc(cls, val: datetime | str) -> str:
        return normalize_utc_timestamp(val)

    @model_validator(mode="after")
    def _validate_simulated_reference(self) -> PaymentEvent:
        if (
            self.data_status == "simulated"
            and self.external_reference is not None
            and not self.external_reference.startswith("SIM-")
        ):
            raise ValueError("Simulated PaymentEvent external_reference must start with 'SIM-'.")
        return self


class PeriodicReport(BaseModel):
    """30-minute analytical report window with coverage and gap tracking."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    window_start_utc: str
    window_end_utc: str
    data_mode: DataMode
    sample_coverage_pct: float = Field(ge=0.0, le=100.0)
    gaps_count: int = Field(ge=0)
    summary_json: str = Field(min_length=2)
    generated_at_utc: str

    @field_validator("window_start_utc", "window_end_utc", "generated_at_utc", mode="before")
    @classmethod
    def _validate_utc(cls, val: datetime | str) -> str:
        return normalize_utc_timestamp(val)

    @model_validator(mode="after")
    def _validate_window_order(self) -> PeriodicReport:
        if self.window_end_utc <= self.window_start_utc:
            raise ValueError("window_end_utc must be strictly greater than window_start_utc.")
        return self
