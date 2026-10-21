"""Typed configuration loader and validation for MineOps DW."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})


class AppSettings(BaseModel):
    """Application settings validated from environment variables or a local .env file."""

    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    app_env: Literal["development", "testing", "production"] = Field(
        default="development",
        alias="APP_ENV",
    )
    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8765, ge=1024, le=65535, alias="APP_PORT")
    allow_non_loopback: bool = Field(default=False, alias="ALLOW_NON_LOOPBACK")

    sample_interval_seconds: int = Field(
        default=10,
        ge=1,
        le=3600,
        alias="SAMPLE_INTERVAL_SECONDS",
    )
    report_interval_minutes: int = Field(
        default=30,
        ge=1,
        le=1440,
        alias="REPORT_INTERVAL_MINUTES",
    )
    telemetry_mode: Literal["simulated", "real"] = Field(
        default="simulated",
        alias="TELEMETRY_MODE",
    )

    max_session_minutes: int = Field(
        default=30,
        ge=1,
        le=1440,
        alias="MAX_SESSION_MINUTES",
    )
    max_cpu_percent: float = Field(
        default=75.0,
         gt=0.0,
        le=100.0,
        alias="MAX_CPU_PERCENT",
    )
    max_cpu_temp_c: float = Field(
        default=80.0,
        ge=40.0,
        le=95.0,
        alias="MAX_CPU_TEMP_C",
    )

    database_path: Path = Field(
        default=Path("data/mineops_dw.sqlite3"),
        alias="DATABASE_PATH",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        alias="LOG_LEVEL",
    )

    binance_read_only_api_key: SecretStr = Field(
        default=SecretStr(""),
        alias="BINANCE_READ_ONLY_API_KEY",
    )
    binance_read_only_api_secret: SecretStr = Field(
        default=SecretStr(""),
        alias="BINANCE_READ_ONLY_API_SECRET",
    )

    @field_validator("app_host")
    @classmethod
    def _normalize_host(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("APP_HOST cannot be empty.")
        return cleaned

    def model_post_init(self, __context: object) -> None:
        """Enforce loopback binding unless explicitly overridden."""
        if not self.allow_non_loopback and self.app_host not in LOOPBACK_HOSTS:
            raise ValueError(
                f"Binding to non-loopback host '{self.app_host}' is forbidden by default. "
                "Keep APP_HOST=127.0.0.1 for local security."
            )

    @property
    def is_binance_configured(self) -> bool:
        """Return True only when both read-only API key and secret are non-empty."""
        key = self.binance_read_only_api_key.get_secret_value().strip()
        secret = self.binance_read_only_api_secret.get_secret_value().strip()
        return bool(key and secret)

    def secret_values(self) -> tuple[str, ...]:
        """Return non-empty secret strings so the logger filter can redact them."""
        candidates = (
            self.binance_read_only_api_key.get_secret_value().strip(),
            self.binance_read_only_api_secret.get_secret_value().strip(),
        )
        return tuple(secret for secret in candidates if len(secret) >= 4)


def load_settings(
    env_file: Path | str | None = None,
    environ: dict[str, str] | None = None,
) -> AppSettings:
    """Load and validate application settings from an optional .env file and environment."""
    merged: dict[str, str] = {}

    if env_file is not None:
        env_path = Path(env_file)
        if env_path.is_file():
            file_values = dotenv_values(env_path)
            for key, val in file_values.items():
                if val is not None:
                    merged[key] = val

    source_env = os.environ if environ is None else environ
    for field_info in AppSettings.model_fields.values():
        env_key = field_info.alias
        if env_key and env_key in source_env:
            merged[env_key] = source_env[env_key]

    return AppSettings.model_validate(merged)
