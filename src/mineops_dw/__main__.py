"""CLI entrypoint to run MineOps DW local server (`PYTHONPATH=src python -m mineops_dw`)."""

from __future__ import annotations

from mineops_dw.runtime import run_local_service

if __name__ == "__main__":
    run_local_service()
