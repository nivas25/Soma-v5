"""Step 3/4/5 — order, run-split, emit exact-W=12 windows → windows_full.parquet."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soma_data.config import (  # noqa: E402
    GAP_THRESHOLD,
    MESSAGES_PARQUET,
    WINDOW_SIZE,
    WINDOWS_FULL_PARQUET,
    ensure_dirs,
)
from soma_data.export import assert_window_invariants  # noqa: E402
from soma_data.parse_irc import ParsedIrcMessage  # noqa: E402
from soma_data.windows import emit_windows, windows_to_frame  # noqa: E402


def _load_parsed() -> list[ParsedIrcMessage]:
    if not MESSAGES_PARQUET.exists():
        raise FileNotFoundError(f"{MESSAGES_PARQUET} missing. Run scripts/02_analyze.py")
    df = pd.read_parquet(MESSAGES_PARQUET)
    return [ParsedIrcMessage.model_validate(rec) for rec in df.to_dict(orient="records")]


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    ensure_dirs()
    parsed = _load_parsed()
    logger.info("loaded {} parsed messages (GAP_THRESHOLD={}, W={})", len(parsed), GAP_THRESHOLD, WINDOW_SIZE)

    records = emit_windows(parsed)
    frame = windows_to_frame(records)
    assert_window_invariants(frame, w=WINDOW_SIZE)

    # Cross-date / cross-run already asserted inside build_window_record.
    n_sys = sum(1 for m in parsed if m.is_system)
    WINDOWS_FULL_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(WINDOWS_FULL_PARQUET, index=False)
    logger.info(
        "windows_full: {} rows (from {} chat messages, {} system excluded) → {}",
        len(frame),
        len(parsed) - n_sys,
        n_sys,
        WINDOWS_FULL_PARQUET,
    )
    logger.info(
        "last_is_question={} addressed={} thanks={}",
        int(frame["last_is_question"].sum()),
        int(frame["addressed_to"].notna().sum()),
        int(frame["last_is_thanks"].sum()),
    )


if __name__ == "__main__":
    main()
