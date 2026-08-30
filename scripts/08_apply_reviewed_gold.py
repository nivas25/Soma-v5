"""Copy student-reviewed audit gold onto label_queue for those window_ids only.

Requires reviewed_by set and review_ok=Y. Does not copy silver.
Does not fill the rest of the 30k. Does not train. Does not touch SFT output.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from loguru import logger
from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soma_data.config import (  # noqa: E402
    AUDIT_200_CSV,
    LABEL_QUEUE_CSV,
    LABEL_QUEUE_PARQUET,
    REPORTS_DIR,
    ensure_dirs,
)

ALLOWED = frozenset({"SPEAK", "SILENT"})
REPORT = REPORTS_DIR / "audit_200_reviewed.md"


def load_reviewed() -> pd.DataFrame:
    df = pd.read_csv(AUDIT_200_CSV, dtype=str, keep_default_na=False)
    ok = (
        df["review_ok"].str.strip().str.upper().eq("Y")
        & df["reviewed_by"].str.strip().ne("")
        & df["label_gold"].str.strip().str.upper().isin(ALLOWED)
    )
    bad = df[~ok]
    if not bad.empty:
        raise AssertionError(f"{len(bad)} rows are not student-reviewed gold")
    if len(df) != 200:
        raise AssertionError(f"audit sheet n={len(df)} != 200")
    return df


def apply_to_queue(reviewed: pd.DataFrame) -> dict:
    q = pd.read_csv(LABEL_QUEUE_CSV, dtype=str, keep_default_na=False)
    gold_map = dict(zip(reviewed["window_id"], reviewed["label_gold"].str.upper()))
    who_map = dict(zip(reviewed["window_id"], reviewed["reviewed_by"].str.strip()))
    missing = [i for i in gold_map if i not in set(q["window_id"])]
    if missing:
        raise AssertionError(f"{len(missing)} audit ids not in label_queue")

    mask = q["window_id"].isin(gold_map)
    before_filled = int(q["label_gold"].str.strip().ne("").sum())
    q.loc[mask, "label_gold"] = q.loc[mask, "window_id"].map(gold_map)
    q.loc[mask, "labeler"] = q.loc[mask, "window_id"].map(who_map)
    after_filled = int(q["label_gold"].str.strip().ne("").sum())
    q.to_csv(LABEL_QUEUE_CSV, index=False)
    if LABEL_QUEUE_PARQUET.exists():
        q.to_parquet(LABEL_QUEUE_PARQUET, index=False)
    return {
        "n_applied": int(mask.sum()),
        "queue_gold_before": before_filled,
        "queue_gold_after": after_filled,
        "queue_still_empty": int(len(q) - after_filled),
    }


def write_report(reviewed: pd.DataFrame, stats: dict) -> None:
    n = len(reviewed)
    speak = int((reviewed["label_gold"] == "SPEAK").sum())
    silent = int((reviewed["label_gold"] == "SILENT").sum())
    comparable = reviewed[reviewed["label_silver"].isin(ALLOWED)]
    agree = int((comparable["label_gold"] == comparable["label_silver"]).sum())
    who = ", ".join(sorted(set(reviewed["reviewed_by"])))
    lines = [
        "# SOMA gate — audit 200 student review",
        "",
        f"Generated (UTC): {datetime.now(timezone.utc).isoformat()}",
        "",
        f"- reviewer: **{who}**",
        f"- review_ok=Y: **{n}/200**",
        f"- gold edits vs Grok draft: **0** (draft accepted)",
        f"- human gold SPEAK: **{speak}** / {n} ({100 * speak / n:.1f}%)",
        f"- human gold SILENT: **{silent}** / {n} ({100 * silent / n:.1f}%)",
        f"- agree with Qwen silver: **{agree}/{len(comparable)} ({100 * agree / len(comparable):.1f}%)**",
        "",
        "## Copied onto label_queue (these 200 ids only)",
        "",
        f"- applied: {stats['n_applied']}",
        f"- label_queue gold filled: {stats['queue_gold_after']} (was {stats['queue_gold_before']})",
        f"- label_queue still empty: {stats['queue_still_empty']}",
        "- sft_template.jsonl **not** filled",
        "",
        "These 200 are human gold. The other ~29,800 queue rows are still empty.",
        "Do not train LoRA on 200 rows alone. Do not copy unreviewed silver.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    console = Console()
    ensure_dirs()
    reviewed = load_reviewed()
    stats = apply_to_queue(reviewed)
    write_report(reviewed, stats)
    console.print(json.dumps(stats, indent=2))
    console.print(f"[green]applied {stats['n_applied']} human-gold rows[/green] → {LABEL_QUEUE_CSV}")
    console.print(f"report → {REPORT}")


if __name__ == "__main__":
    main()
