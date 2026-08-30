"""Freeze 200 windows from the silver 2k for human audit. No gold. No LoRA."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from loguru import logger
from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soma_data.audit_select import freeze_audit  # noqa: E402
from soma_data.config import (  # noqa: E402
    AUDIT_200_CSV,
    AUDIT_200_IDS,
    AUDIT_200_MANIFEST,
    AUDIT_200_MD,
    AUDIT_N,
    PILOT_2K_IDS,
    PILOT_2K_LABELS_JSONL,
    ensure_dirs,
)
from soma_data.pilot_select import load_frozen_ids  # noqa: E402


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    console = Console()
    ensure_dirs()

    for p in (PILOT_2K_IDS, PILOT_2K_LABELS_JSONL):
        if not p.exists():
            raise FileNotFoundError(f"missing {p}. Finish the 2k pilot first.")
        console.print(f"[green]ok[/green] {p.name} ({p.stat().st_size:,} bytes)")

    frozen = load_frozen_ids()
    console.print(f"frozen 2k ids={len(frozen)} (will not reshuffle)")

    force = "--force" in sys.argv
    man = freeze_audit(force=force)
    ids = [ln.strip() for ln in AUDIT_200_IDS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(ids) != AUDIT_N:
        raise AssertionError(f"audit ids {len(ids)} != {AUDIT_N}")
    if ids != sorted(ids):
        raise AssertionError("audit ids are not sorted")
    extra = set(ids) - set(frozen)
    if extra:
        raise AssertionError(f"audit escaped frozen 2k: {len(extra)}")
    console.print(f"audit n={man['n']} seed={man['seed']}")
    console.print(f"buckets={json.dumps(man.get('bucket_actual'))}")
    console.print(f"ids → {AUDIT_200_IDS}")
    console.print(f"sheet → {AUDIT_200_CSV}")
    console.print(f"manifest → {AUDIT_200_MANIFEST}")
    console.print(f"guide → {AUDIT_200_MD}")
    console.print("[green]audit freeze OK — fill label_gold in the CSV only, not label_queue.csv[/green]")


if __name__ == "__main__":
    main()
