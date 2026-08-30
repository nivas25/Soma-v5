"""Step 6 — label_queue, sft_template.jsonl, stats reconciliation, quality asserts."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soma_data.config import (  # noqa: E402
    GAP_THRESHOLD,
    LABEL_QUEUE_CAP,
    LABEL_QUEUE_CSV,
    LABEL_QUEUE_PARQUET,
    MESSAGES_PARQUET,
    MIN_HISTORY,
    REQUIRE_EXACT_W,
    SEED,
    SFT_TEMPLATE_JSONL,
    STATS_JSON,
    TARGET_OTHER_FRACTION,
    WINDOW_SIZE,
    WINDOWS_FULL_PARQUET,
    ensure_dirs,
)
from soma_data.export import (  # noqa: E402
    assert_window_invariants,
    sample_label_queue,
    write_label_queue,
    write_sft_template,
)
from soma_data.hf_download import iter_raw_snapshots  # noqa: E402
from soma_data.quality import assert_no_hf_token_in_tree  # noqa: E402
from soma_data.stats import write_stats_json  # noqa: E402


def _raw_counts() -> dict[str, int]:
    out = {}
    total = 0
    for config, split, path in iter_raw_snapshots():
        n = int(pd.read_parquet(path, columns=["id"]).shape[0])
        out[f"{config}/{split}"] = n
        total += n
    out["_sum_snapshots"] = total
    return out


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    ensure_dirs()

    if not WINDOWS_FULL_PARQUET.exists():
        raise FileNotFoundError(f"{WINDOWS_FULL_PARQUET} missing. Run scripts/03_build_windows.py")

    windows = pd.read_parquet(WINDOWS_FULL_PARQUET)
    assert_window_invariants(windows, w=WINDOW_SIZE)
    logger.info("windows_full={}", len(windows))

    queue = sample_label_queue(
        windows,
        cap=LABEL_QUEUE_CAP,
        seed=SEED,
        other_fraction=TARGET_OTHER_FRACTION,
    )
    write_label_queue(queue)
    write_sft_template(queue, SFT_TEMPLATE_JSONL)

    n_raw_parsed = int(pd.read_parquet(MESSAGES_PARQUET, columns=["original_id"]).shape[0])
    n_q = int(queue["last_is_question"].sum())
    addr_s = queue["addressed_to"].astype(str).str.strip()
    is_addr = queue["addressed_to"].notna() & addr_s.ne("") & addr_s.str.lower().ne("nan") & addr_s.str.lower().ne("none")
    n_addr = int(is_addr.sum())
    n_thanks = int(queue["last_is_thanks"].sum())
    n_other = int((~queue["last_is_question"].astype(bool) & ~is_addr).sum())
    q_frac = n_q / len(queue) if len(queue) else 0.0

    recon = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "04_export",
        "frozen": {
            "WINDOW_SIZE": WINDOW_SIZE,
            "MIN_HISTORY": MIN_HISTORY,
            "REQUIRE_EXACT_W": REQUIRE_EXACT_W,
            "GAP_THRESHOLD": GAP_THRESHOLD,
            "SEED": SEED,
            "LABEL_QUEUE_CAP": LABEL_QUEUE_CAP,
            "TARGET_OTHER_FRACTION": TARGET_OTHER_FRACTION,
        },
        "reconciliation": {
            "raw_snapshots": _raw_counts(),
            "parsed_messages": n_raw_parsed,
            "windows_full": int(len(windows)),
            "label_queue": int(len(queue)),
            "sft_template": int(len(queue)),
        },
        "label_queue_mix": {
            "n": int(len(queue)),
            "last_is_question": n_q,
            "question_frac": round(q_frac, 4),
            "addressed": n_addr,
            "other_neither_q_nor_addressed": n_other,
            "last_is_thanks": n_thanks,
            "note": "question_frac should be well below 0.90 after mixing in others / cap",
        },
        "gold_labels": "EMPTY — no SPEAK/SILENT model labels in this task",
        "artifacts": {
            "windows_full": str(WINDOWS_FULL_PARQUET.as_posix()),
            "label_queue_csv": str(LABEL_QUEUE_CSV.as_posix()),
            "label_queue_parquet": str(LABEL_QUEUE_PARQUET.as_posix()),
            "sft_template": str(SFT_TEMPLATE_JSONL.as_posix()),
        },
    }

    # Merge with 02_analyze stats if present.
    if STATS_JSON.exists():
        try:
            prev = json.loads(STATS_JSON.read_text(encoding="utf-8"))
            recon["from_02_analyze"] = {
                k: prev[k]
                for k in (
                    "raw_rows_all_snapshots",
                    "raw_rows_windowing_partition",
                    "parsed_rows",
                    "card_annotated",
                    "eda_headline",
                    "per_split",
                )
                if k in prev
            }
        except json.JSONDecodeError:
            pass

    write_stats_json(recon)
    assert_no_hf_token_in_tree()
    if q_frac >= 0.90:
        logger.warning("question_frac={:.2f} still very high — other pool may be tiny", q_frac)
    logger.info("04_export complete. label_queue={} question_frac={:.3f}", len(queue), q_frac)


if __name__ == "__main__":
    main()
