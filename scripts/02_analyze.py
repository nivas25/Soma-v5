"""Step 2 — parse + deep EDA. Writes messages.parquet, schema.md, eda.md."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soma_data.config import MESSAGES_PARQUET, ensure_dirs  # noqa: E402
from soma_data.hf_download import CARD_ANNOTATED  # noqa: E402
from soma_data.stats import (  # noqa: E402
    compute_eda,
    describe_raw_split,
    load_all_raw,
    messages_for_windows,
    messages_to_frame,
    parse_messages,
    plot_eda,
    write_eda_md,
    write_schema_md,
    write_stats_json,
)


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    ensure_dirs()

    raw_all = load_all_raw()
    logger.info("raw snapshots concatenated: {} rows", len(raw_all))

    raw_win = messages_for_windows(raw_all)
    logger.info("windowing partition (ubuntu all splits + channel_two/all_): {} rows", len(raw_win))

    parsed = parse_messages(raw_win)
    msg_df = messages_to_frame(parsed)
    MESSAGES_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    msg_df.to_parquet(MESSAGES_PARQUET, index=False)
    logger.info("wrote {} parsed messages → {}", len(msg_df), MESSAGES_PARQUET)

    eda = compute_eda(parsed)
    figs = plot_eda(eda)
    write_schema_md(raw_all, parsed)
    write_eda_md(eda, figs)

    split_desc = {}
    for (config, split), g in raw_all.groupby(["config", "split"], sort=True):
        split_desc[f"{config}/{split}"] = describe_raw_split(g)

    write_stats_json(
        {
            "stage": "02_analyze",
            "raw_rows_all_snapshots": int(len(raw_all)),
            "raw_rows_windowing_partition": int(len(raw_win)),
            "parsed_rows": int(len(parsed)),
            "card_annotated": {f"{k[0]}/{k[1]}": v for k, v in CARD_ANNOTATED.items()},
            "per_split": split_desc,
            "eda_headline": {k: eda[k] for k in eda if k not in {"by_date", "samples"}},
        }
    )
    logger.info(
        "EDA: system={:.2f}% question={:.2f}% addressed={:.2f}% parse_fail={:.3f}%",
        eda["pct_system"],
        eda["pct_question"],
        eda["pct_addressed"],
        eda["pct_parse_fail"],
    )


if __name__ == "__main__":
    main()
