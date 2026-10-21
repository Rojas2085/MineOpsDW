"""Centralized logging configuration with automatic secret redaction."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

REDACTED_PLACEHOLDER = "[REDACTED]"

# Patterns matching sensitive key/value pairs in query strings, headers, or log messages
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)\b("
    r"api[_-]?key|api[_-]?secret|secret|token|signature|password|passphrase|"
    r"x-mbx-apikey|pool-auth-token|binance_read_only_api_key|binance_read_only_api_secret"
    r")\b(\s*[:=]\s*['\"]?)([^'\"\s,&;]+)(['\"]?)"
)


def redact_sensitive_text(text: str, explicit_secrets: Iterable[str] = ()) -> str:
    """Redact known secret values and key/value secret patterns from a string."""
    if not text:
        return text

    sanitized = text
    for secret in explicit_secrets:
        if secret and len(secret) >= 4 and secret in sanitized:
            sanitized = sanitized.replace(secret, REDACTED_PLACEHOLDER)

    sanitized = _SENSITIVE_KEY_PATTERN.sub(
        rf"\1\2{REDACTED_PLACEHOLDER}\4",
        sanitized,
    )
    return sanitized


class SecretRedactingFilter(logging.Filter):
    """Logging filter that strips API keys, signatures, tokens, and explicit secrets."""

    def __init__(self, explicit_secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._explicit_secrets: tuple[str, ...] = tuple(
            s for s in explicit_secrets if s and len(s) >= 4
        )

    def filter(self, record: logging.LogRecord) -> bool:
        """Sanitize the formatted message and arguments in-place before emission."""
        rendered_message = record.getMessage()
        sanitized_message = redact_sensitive_text(rendered_message, self._explicit_secrets)
        record.msg = sanitized_message
        record.args = ()
        return True


def configure_logging(
    level: str = "INFO",
    explicit_secrets: Iterable[str] = (),
    logger_name: str = "mineops_dw",
) -> logging.Logger:
    """Configure and return the project logger with a SecretRedactingFilter attached."""
    logger = logging.getLogger(logger_name)
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric_level)
    logger.propagate = False

    redacting_filter = SecretRedactingFilter(explicit_secrets=explicit_secrets)

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="%(asctime)sZ | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    for handler in logger.handlers:
        handler.filters = [
            f for f in handler.filters if not isinstance(f, SecretRedactingFilter)
        ]
        handler.addFilter(redacting_filter)

    logger.filters = [
        f for f in logger.filters if not isinstance(f, SecretRedactingFilter)
    ]
    logger.addFilter(redacting_filter)
    return logger
