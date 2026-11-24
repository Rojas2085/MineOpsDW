"""Repository secret scanner to prevent accidental leaks of keys, tokens, or private material."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "data",
        "logs",
        "node_modules",
        "dist",
        "build",
    }
)

# High-confidence patterns indicating real secrets or populated credential assignments
_PRIVATE_KEY_HEADER = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
_POPULATED_ENV_SECRET = re.compile(
    r"(?m)^\s*(BINANCE_READ_ONLY_API_KEY|BINANCE_READ_ONLY_API_SECRET)\s*=\s*([^\s#]+)"
)
_POPULATED_PAYOUT_ADDRESS = re.compile(
    r"(?m)^\s*PAYOUT_ADDRESS\s*=\s*([^\s#]+)"
)
_EVM_WALLET_ADDRESS = re.compile(r"\b0x[a-fA-F0-9]{40}\b")


@dataclass(frozen=True)
class SecretFinding:
    """Represents a potential secret detected during a workspace scan."""

    file_path: Path
    rule_name: str
    line_number: int


def scan_workspace_for_secrets(root_dir: Path | str) -> list[SecretFinding]:
    """Scan all non-excluded text files under root_dir for leaked credentials or private keys."""
    root = Path(root_dir).resolve()
    findings: list[SecretFinding] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() in {".sqlite", ".sqlite3", ".db", ".pyc", ".png", ".jpg"}:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for idx, line in enumerate(text.splitlines(), start=1):
            if _PRIVATE_KEY_HEADER.search(line):
                findings.append(
                    SecretFinding(
                        file_path=path,
                        rule_name="private_key_header",
                        line_number=idx,
                    )
                )
            env_match = _POPULATED_ENV_SECRET.match(line)
            if env_match:
                val = env_match.group(2).strip().strip("'\"")
                if val and val not in {"", "YOUR_KEY_HERE", "REDACTED", "[REDACTED]"}:
                    findings.append(
                        SecretFinding(
                            file_path=path,
                            rule_name="populated_binance_credential",
                            line_number=idx,
                        )
                    )
            if path.name != ".env":
                if path.name.startswith(".env") or path.suffix == ".env":
                    payout_match = _POPULATED_PAYOUT_ADDRESS.match(line)
                    if payout_match:
                        val = payout_match.group(1).strip().strip("'\"")
                        if val and val not in {"", "TU_DIRECCION_PUBLICA", "YOUR_ADDRESS_HERE"}:
                            findings.append(
                                SecretFinding(
                                    file_path=path,
                                    rule_name="populated_payout_address",
                                    line_number=idx,
                                )
                            )
                if "security_scanner" not in path.name:
                    if _EVM_WALLET_ADDRESS.search(line) and "0x0000000000000000000000000000000000000000" not in line:
                        findings.append(
                            SecretFinding(
                                file_path=path,
                                rule_name="evm_wallet_address",
                                line_number=idx,
                            )
                        )

    return findings
