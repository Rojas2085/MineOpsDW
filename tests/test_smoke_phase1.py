"""Phase 1 smoke tests: package structure, typed settings, and secret-safe logging."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from mineops_dw import __version__
from mineops_dw.config import AppSettings, load_settings
from mineops_dw.logging_config import (
    REDACTED_PLACEHOLDER,
    SecretRedactingFilter,
    configure_logging,
    redact_sensitive_text,
)


def test_package_and_subpackages_importable() -> None:
    """All core architectural packages must import cleanly."""
    assert __version__ == "0.1.0"
    subpackages = (
        "mineops_dw.domain",
        "mineops_dw.adapters",
        "mineops_dw.storage",
        "mineops_dw.collector",
        "mineops_dw.api",
        "mineops_dw.reporting",
    )
    for mod_name in subpackages:
        module = importlib.import_module(mod_name)
        assert module is not None


def test_default_settings_are_safe_and_simulated() -> None:
    """Default configuration must bind to loopback and start in simulated mode."""
    settings = load_settings(environ={})
    assert settings.app_host == "127.0.0.1"
    assert settings.app_port == 8765
    assert settings.telemetry_mode == "simulated"
    assert settings.report_interval_minutes == 30
    assert settings.sample_interval_seconds == 10
    assert settings.max_cpu_percent == 75.0
    assert settings.max_cpu_temp_c == 80.0
    assert settings.is_binance_configured is False


def test_load_settings_from_env_example() -> None:
    """The repository .env.example file must parse and validate without errors."""
    env_example = Path(__file__).resolve().parents[1] / ".env.example"
    assert env_example.is_file()
    settings = load_settings(env_file=env_example, environ={})
    assert settings.app_host == "127.0.0.1"
    assert settings.telemetry_mode == "simulated"
    assert settings.is_binance_configured is False


def test_non_loopback_host_rejected_by_default() -> None:
    """Exposing the API to 0.0.0.0 or a public IP must fail unless explicitly allowed."""
    with pytest.raises(ValidationError, match="non-loopback host"):
        load_settings(environ={"APP_HOST": "0.0.0.0"})


def test_invalid_safety_limits_rejected() -> None:
    """Out-of-range CPU load or temperature thresholds must be rejected."""
    with pytest.raises(ValidationError):
        AppSettings(MAX_CPU_PERCENT=120.0)
    with pytest.raises(ValidationError):
        AppSettings(MAX_CPU_TEMP_C=105.0)


def test_secret_redaction_in_text_and_logger(caplog: pytest.LogCaptureFixture) -> None:
    """API keys, secrets, and signatures must never appear in plain text in logs."""
    fake_key = "test_fake_key_9988776655"
    fake_secret = "test_fake_secret_1122334455"

    raw = (
        f"Request failed: X-MBX-APIKEY={fake_key} "
        f"signature=abcdef1234567890 raw_secret={fake_secret}"
    )
    sanitized = redact_sensitive_text(raw, explicit_secrets=(fake_key, fake_secret))
    assert fake_key not in sanitized
    assert fake_secret not in sanitized
    assert "abcdef1234567890" not in sanitized
    assert REDACTED_PLACEHOLDER in sanitized

    logger = configure_logging(
        level="INFO",
        explicit_secrets=(fake_key, fake_secret),
        logger_name="mineops_dw.test_logger",
    )
    record = logging.LogRecord(
        name=logger.name,
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Binance error with key %s and token=%s",
        args=(fake_key, "my_secret_token_value"),
        exc_info=None,
    )
    redactor = SecretRedactingFilter(explicit_secrets=(fake_key, fake_secret))
    assert redactor.filter(record) is True
    assert fake_key not in str(record.msg)
    assert "my_secret_token_value" not in str(record.msg)
    assert REDACTED_PLACEHOLDER in str(record.msg)
