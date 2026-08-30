"""Export labelling-ready + future-SFT-ready artifacts. Gold labels stay empty."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import orjson
import pandas as pd
from loguru import logger

from soma_data.config import (
    LABEL_QUEUE_CAP,
    LABEL_QUEUE_CSV,
    LABEL_QUEUE_PARQUET,
    SEED,
    SFT_INSTRUCTION,
    SFT_TEMPLATE_JSONL,
    TARGET_OTHER_FRACTION,
    WINDOW_SIZE,
)

LABEL_QUEUE_COLUMNS = [
    "window_id",
    "split",
    "date",
    "t_id",
    "chat_block",
    "last_speaker",
    "question_open",
    "addressed_to",
    "n_speakers_in_window",
    "last_is_question",
    "last_is_thanks",
    "thread_overlap_count",
    "label_gold",
    "labeler",
    "notes",
    "guideline_hint",
]


def _str_bool(v: Any) -> str:
    if v is True or v == "yes" or v == "true":
        return "yes"
    if v is False or v == "no" or v == "false":
        return "no"
    return "yes" if bool(v) else "no"


def format_sft_input(row: pd.Series) -> str:
    addressed = row.get("addressed_to")
    if addressed is None or (isinstance(addressed, float) and pd.isna(addressed)) or addressed == "":
        addressed_s = "group"
    else:
        addressed_s = str(addressed)
    n_speakers = int(row.get("n_speakers_in_window") or 0)
    last_speaker = row.get("last_speaker") or "UNKNOWN"
    room = (
        "[ROOM]\n"
        f"last_speaker: {last_speaker}\n"
        f"question_open: {_str_bool(row.get('question_open'))}\n"
        f"addressed_to: {addressed_s}\n"
        f"assistant_named: {_str_bool(row.get('assistant_named'))}\n"
        f"n_speakers: {n_speakers}\n"
    )
    chat = "[CHAT]\n" + str(row.get("chat_block") or "")
    return room + "\n" + chat


def sample_label_queue(
    windows: pd.DataFrame,
    *,
    cap: int = LABEL_QUEUE_CAP,
    seed: int = SEED,
    other_fraction: float = TARGET_OTHER_FRACTION,
) -> pd.DataFrame:
    """Must-include: ALL last-is-question + ALL addressed.

    Then add a seeded sample of 'other' so questions are not ~90% of the sheet.
    If must-include already exceeds `cap`, downsample with stratification.
    """
    df = windows.copy()
    addressed = df["addressed_to"].notna() & (df["addressed_to"].astype(str) != "")
    is_q = df["last_is_question"].astype(bool)
    is_must = is_q | addressed
    must = df.loc[is_must]
    other = df.loc[~is_must]
    rng = np.random.default_rng(seed)

    logger.info(
        "queue pool: total={} question={} addressed={} other={}",
        len(df),
        int(is_q.sum()),
        int(addressed.sum()),
        len(other),
    )

    if len(must) >= cap:
        # Prefer questions + addressed, but always reserve a slice of "other"
        # so the sheet is not 90% questions / 0% room-idle.
        q = df.loc[is_q]
        a_only = df.loc[addressed & ~is_q]
        n_other = min(len(other), int(round(cap * other_fraction)))
        remain = cap - n_other
        n_q = min(len(q), int(round(remain * 0.55)))
        n_a = min(len(a_only), remain - n_q)
        leftover = cap - n_q - n_a - n_other
        if leftover > 0:
            extra_q = min(max(0, len(q) - n_q), leftover)
            n_q += extra_q
            leftover -= extra_q
        if leftover > 0:
            extra_a = min(max(0, len(a_only) - n_a), leftover)
            n_a += extra_a
            leftover -= extra_a
        if leftover > 0:
            n_other = min(len(other), n_other + leftover)
        picked = []
        if n_q:
            picked.append(_take(q, n_q, rng))
        if n_a:
            picked.append(_take(a_only, n_a, rng))
        if n_other:
            picked.append(_take(other, n_other, rng))
        out = pd.concat(picked, ignore_index=True) if picked else must.iloc[0:0]
        logger.warning(
            "must-include {} >= cap {}; stratified q={} addressed_only={} other={}",
            len(must),
            cap,
            n_q,
            n_a,
            n_other,
        )
    else:
        remaining = cap - len(must)
        # Want others to be ~other_fraction of the final sheet when possible.
        target_other = min(len(other), remaining, max(0, int(round(len(must) * other_fraction / (1 - other_fraction)))))
        extra = _take(other, target_other, rng) if target_other else other.iloc[0:0]
        out = pd.concat([must, extra], ignore_index=True)
        logger.info(
            "queue keep must={} other_sample={} (target_other={})",
            len(must),
            len(extra),
            target_other,
        )

    out = out.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    return out


def _take(df: pd.DataFrame, n: int, rng: np.random.Generator) -> pd.DataFrame:
    if n <= 0 or df.empty:
        return df.iloc[0:0]
    n = min(n, len(df))
    idx = rng.choice(df.index.to_numpy(), size=n, replace=False)
    return df.loc[idx]


def prepare_label_frame(windows: pd.DataFrame) -> pd.DataFrame:
    out = windows.copy()
    out["label_gold"] = ""
    out["labeler"] = ""
    out["notes"] = ""
    # addressed_to as empty string rather than NaN for the CSV
    out["addressed_to"] = out["addressed_to"].apply(lambda x: "" if x is None or (isinstance(x, float) and pd.isna(x)) else x)
    missing = [c for c in LABEL_QUEUE_COLUMNS if c not in out.columns]
    if missing:
        raise KeyError(f"label queue missing columns: {missing}")
    return out[LABEL_QUEUE_COLUMNS]


def write_label_queue(queue: pd.DataFrame) -> None:
    frame = prepare_label_frame(queue)
    LABEL_QUEUE_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(LABEL_QUEUE_PARQUET, index=False)
    frame.to_csv(LABEL_QUEUE_CSV, index=False, encoding="utf-8", lineterminator="\n")
    logger.info("label_queue {} rows → {} and {}", len(frame), LABEL_QUEUE_CSV, LABEL_QUEUE_PARQUET)


def write_sft_template(windows: pd.DataFrame, path: Path = SFT_TEMPLATE_JSONL) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("wb") as fh:
        for rec in windows.to_dict(orient="records"):
            obj = {
                "window_id": rec["window_id"],
                "split": rec["split"],
                "source": rec.get("source") or f"irc_disentangle/{rec.get('config', 'ubuntu')}",
                "instruction": SFT_INSTRUCTION,
                "input": format_sft_input(pd.Series(rec)),
                "output": "",
            }
            fh.write(orjson.dumps(obj))
            fh.write(b"\n")
            n += 1
    logger.info("sft_template {} rows → {}", n, path)
    return n


def assert_window_invariants(windows: pd.DataFrame, *, w: int = WINDOW_SIZE) -> None:
    if windows.empty:
        raise AssertionError("windows frame is empty")
    # chat_block line count
    nlines = windows["chat_block"].map(lambda s: 0 if s is None else str(s).count("\n") + 1)
    bad = windows.loc[nlines != w]
    if len(bad):
        raise AssertionError(f"{len(bad)} windows have chat_block lines != {w}")
    # no cross-date / cross-run: encoded in window_id and columns
    if windows["date"].isna().any():
        raise AssertionError("null dates in windows")
    dup = windows["window_id"].duplicated().sum()
    if dup:
        raise AssertionError(f"{dup} duplicate window_id values")
    # window_message_ids stay inside the same run by construction; verify monotonic ids
    def _ids_ok(ids) -> bool:
        seq = list(ids)
        return len(seq) == w and seq == sorted(seq)

    if "window_message_ids" in windows.columns:
        bad_ids = windows["window_message_ids"].map(_ids_ok)
        if not bool(bad_ids.all()):
            raise AssertionError("some windows have unsorted or short window_message_ids")
    logger.info("window invariants OK (n={}, W={})", len(windows), w)
