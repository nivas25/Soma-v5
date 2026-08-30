"""Freeze 2,000 window_ids from label_queue.csv. No LLM. Never reshuffle."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from loguru import logger
from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soma_data.config import (  # noqa: E402
    LABEL_QUEUE_CSV,
    PILOT_2K_IDS,
    PILOT_2K_MANIFEST,
    PILOT_N,
    USED_WINDOW_IDS,
    WINDOWS_FULL_PARQUET,
    ensure_dirs,
)
from soma_data.pilot_select import freeze_pilot_ids  # noqa: E402


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    console = Console()
    ensure_dirs()

    required = {
        "label_queue.csv": LABEL_QUEUE_CSV,
        "windows_full.parquet": WINDOWS_FULL_PARQUET,
    }
    for name, path in required.items():
        if not path.exists():
            raise FileNotFoundError(f"required artifact missing: {name} ({path})")
        console.print(f"[green]ok[/green] {name}: {path} ({path.stat().st_size:,} bytes)")

    force = "--force" in sys.argv
    if force:
        logger.warning("--force will REPLACE the frozen 2k id list (forbidden in normal runs)")
    manifest = freeze_pilot_ids(force=force)
    console.print(f"frozen n={manifest['n']} seed={manifest['seed']}")
    console.print(f"source sha256={manifest['source_sha256']}")
    console.print(f"strata={json.dumps(manifest['stratum_actual'])}")
    console.print(f"fill={manifest['stratum_fill']}")
    console.print(f"ids → {PILOT_2K_IDS}")
    console.print(f"manifest → {PILOT_2K_MANIFEST}")
    console.print(f"used_window_ids → {USED_WINDOW_IDS} (append-only)")
    n_ids = len([ln for ln in PILOT_2K_IDS.read_text(encoding="utf-8").splitlines() if ln.strip()])
    if n_ids != PILOT_N:
        raise AssertionError(f"id file has {n_ids} != {PILOT_N}")
    # Frozen order is sorted by window_id
    ids = [ln.strip() for ln in PILOT_2K_IDS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if ids != sorted(ids):
        raise AssertionError("pilot ids are not sorted by window_id")
    console.print("[green]freeze OK — do not reshuffle[/green]")


if __name__ == "__main__":
    main()
