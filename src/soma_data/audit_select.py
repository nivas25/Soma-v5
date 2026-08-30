"""Freeze a 200-window human-audit subset of the silver 2k.

Does not reshuffle pilot_2k_ids.txt. Does not write label_gold.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from soma_data.config import (
    AUDIT_200_CSV,
    AUDIT_200_IDS,
    AUDIT_200_MANIFEST,
    AUDIT_200_MD,
    AUDIT_N,
    LABEL_QUEUE_CSV,
    PILOT_2K_FAILURES_JSONL,
    PILOT_2K_IDS,
    PILOT_2K_LABELS_JSONL,
    SEED,
    ensure_dirs,
)
from soma_data.pilot_select import assign_strata, load_frozen_ids, sha256_file

# Error-finding mix. Fill remainder from leftover SILENT.
AUDIT_BUCKETS: dict[str, int] = {
    "fail": 1,
    "speak_addressed": 20,  # SPEAK vs "addressed to human"
    "speak_other": 15,
    "speak_open_q": 40,  # SPEAK + "question + no clear addressee"
    "speak_open3": 20,  # SPEAK + "open question in last 3"
    "silent_open_q": 40,  # SILENT vs open-question hint
    "silent_open3": 20,
    "silent_addressed": 15,
    "silent_thanks": 10,
    "silent_other": 19,
}


def _hint(row: dict | pd.Series) -> str:
    return str(row.get("guideline_hint") or "").strip().lower()


def _is_present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    s = str(value).strip()
    return s != "" and s.lower() not in {"nan", "none", "null"}


def assign_audit_bucket(row: dict | pd.Series) -> str:
    raw_ok = row.get("raw_ok", True)
    if raw_ok in (False, 0, "0", "false", "False") or _is_present(row.get("error")):
        return "fail"
    lab = str(row.get("label_silver") or "").upper()
    if lab in {"NAN", "NONE"}:
        lab = ""
    hint = _hint(row)
    if lab == "SPEAK":
        if "addressed to human" in hint:
            return "speak_addressed"
        if "thanks" in hint:
            return "speak_thanks"
        if "question + no clear addressee" in hint:
            return "speak_open_q"
        if "open question in last 3" in hint:
            return "speak_open3"
        return "speak_other"
    if "question + no clear addressee" in hint:
        return "silent_open_q"
    if "open question in last 3" in hint:
        return "silent_open3"
    if "addressed to human" in hint:
        return "silent_addressed"
    if "thanks" in hint:
        return "silent_thanks"
    return "silent_other"


def _last_line(chat: str) -> str:
    lines = [ln for ln in str(chat or "").splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def select_audit(
    df: pd.DataFrame,
    *,
    seed: int = SEED,
    n: int = AUDIT_N,
    targets: dict[str, int] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Deterministic bucket sample. Output sorted by window_id."""
    targets = dict(targets or AUDIT_BUCKETS)
    work = df.copy()
    work["audit_bucket"] = [assign_audit_bucket(r) for r in work.to_dict(orient="records")]
    rng = np.random.default_rng(seed)
    picked: list[pd.DataFrame] = []
    actual: dict[str, int] = {}
    taken: set[str] = set()
    fill_notes: list[str] = []

    def _take(pool: pd.DataFrame, k: int) -> pd.DataFrame:
        pool = pool[~pool["window_id"].isin(taken)]
        if k <= 0 or pool.empty:
            return pool.iloc[0:0]
        k = min(k, len(pool))
        idx = rng.choice(pool.index.to_numpy(), size=k, replace=False)
        return pool.loc[idx]

    for bucket, k in targets.items():
        chunk = _take(work[work["audit_bucket"] == bucket], k)
        actual[bucket] = len(chunk)
        if len(chunk) < k:
            fill_notes.append(f"{bucket}: wanted {k} got {len(chunk)}")
        if not chunk.empty:
            picked.append(chunk)
            taken.update(chunk["window_id"].tolist())

    have = sum(actual.values())
    if have < n:
        rest = _take(work, n - have)
        fill_notes.append(f"fill leftover n={len(rest)}")
        if not rest.empty:
            picked.append(rest)
            actual["fill"] = len(rest)

    out = pd.concat(picked, axis=0) if picked else work.iloc[0:0]
    out = out.drop_duplicates("window_id").sort_values("window_id").reset_index(drop=True)
    if len(out) > n:
        out = out.iloc[:n].copy()
    meta = {
        "n": len(out),
        "seed": seed,
        "bucket_targets": targets,
        "bucket_actual": actual,
        "fill_notes": fill_notes,
    }
    return out, meta


def freeze_audit(*, force: bool = False) -> dict[str, Any]:
    ensure_dirs()
    if AUDIT_200_IDS.exists() and not force:
        ids = [ln.strip() for ln in AUDIT_200_IDS.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if len(ids) == AUDIT_N:
            logger.info("audit already frozen at {} — not reshuffling", AUDIT_200_IDS)
            return json.loads(AUDIT_200_MANIFEST.read_text(encoding="utf-8"))
        raise RuntimeError(f"audit id file exists with n={len(ids)} != {AUDIT_N}. Pass force=True to replace.")

    frozen = load_frozen_ids()
    if len(frozen) != 2000:
        raise AssertionError(f"pilot_2k_ids has {len(frozen)} != 2000")

    labels = []
    for line in PILOT_2K_LABELS_JSONL.read_text(encoding="utf-8").splitlines():
        if line.strip():
            labels.append(json.loads(line))
    fails = []
    if PILOT_2K_FAILURES_JSONL.exists():
        for line in PILOT_2K_FAILURES_JSONL.read_text(encoding="utf-8").splitlines():
            if line.strip():
                fails.append(json.loads(line))

    silver = pd.DataFrame(labels + fails)
    silver = silver.drop_duplicates("window_id")
    extra = set(silver["window_id"]) - set(frozen)
    missing = set(frozen) - set(silver["window_id"])
    if extra or missing:
        raise AssertionError(f"silver vs frozen mismatch extra={len(extra)} missing={len(missing)}")

    q = pd.read_csv(LABEL_QUEUE_CSV, dtype=str, keep_default_na=False)
    q = q.drop_duplicates("window_id")
    q["stratum"] = assign_strata(q)
    merged = silver.merge(q, on="window_id", how="left", suffixes=("", "_q"))
    # Prefer queue chat_block if silver is missing it
    if "chat_block_q" in merged.columns:
        merged["chat_block"] = merged["chat_block"].fillna("").replace("", np.nan)
        merged["chat_block"] = merged["chat_block"].fillna(merged["chat_block_q"])
    if "guideline_hint_q" in merged.columns:
        merged["guideline_hint"] = merged["guideline_hint"].fillna(merged["guideline_hint_q"])

    selected, meta = select_audit(merged, seed=SEED, n=AUDIT_N)
    not_in_frozen = set(selected["window_id"]) - set(frozen)
    if not_in_frozen:
        raise AssertionError("audit ids escaped the frozen 2k")

    ids = selected["window_id"].tolist()
    if ids != sorted(ids):
        raise AssertionError("audit ids not sorted")
    if len(ids) != len(set(ids)):
        raise AssertionError("duplicate audit ids")

    def _col(name: str, default: str = "") -> pd.Series:
        if name in selected.columns:
            return selected[name]
        return pd.Series([default] * len(selected), index=selected.index)

    chats = _col("chat_block")
    sheet = pd.DataFrame(
        {
            "window_id": selected["window_id"],
            "split": _col("split"),
            "date": _col("date"),
            "stratum": _col("stratum"),
            "audit_bucket": _col("audit_bucket"),
            "label_silver": _col("label_silver"),
            "reason": _col("reason"),
            "guideline_hint": _col("guideline_hint"),
            "last_speaker": _col("last_speaker"),
            "last_is_question": _col("last_is_question"),
            "last_is_thanks": _col("last_is_thanks"),
            "addressed_to": _col("addressed_to"),
            "last_line": [_last_line(c) for c in chats],
            "chat_block": chats,
            "raw_ok": _col("raw_ok", "True"),
            "error": _col("error"),
            "label_gold": "",
            "agree_with_silver": "",
            "notes": "",
        }
    )
    if sheet["label_gold"].astype(str).str.strip().ne("").any():
        raise AssertionError("label_gold must stay empty")

    AUDIT_200_IDS.write_text("\n".join(ids) + "\n", encoding="utf-8")
    sheet.to_csv(AUDIT_200_CSV, index=False)

    manifest = {
        "n": len(ids),
        "seed": SEED,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_pilot_ids": str(PILOT_2K_IDS.as_posix()),
        "source_labels_sha256": sha256_file(PILOT_2K_LABELS_JSONL),
        "window_ids": ids,
        **meta,
        "note": "Subset of frozen pilot_2k_ids. Do not copy label_silver into label_gold.",
    }
    AUDIT_200_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _write_md(sheet, manifest)
    logger.info("froze {} audit ids → {}", len(ids), AUDIT_200_IDS)
    return manifest


def _write_md(sheet: pd.DataFrame, man: dict[str, Any]) -> None:
    speak_n = int((sheet["label_silver"] == "SPEAK").sum())
    silent_n = int((sheet["label_silver"] == "SILENT").sum())
    fail_n = int((sheet["audit_bucket"] == "fail").sum()) if "audit_bucket" in sheet.columns else 0
    lines = [
        "# SOMA gate — human audit sheet (200 windows)",
        "",
        f"Generated (UTC): {man['created_at_utc']}",
        "",
        "Subset of the frozen 2,000 silver labels. **Not gold.**",
        "Do not copy `label_silver` into `label_queue.csv` `label_gold`.",
        "Do not train LoRA on this sheet.",
        "",
        "## Files",
        "",
        f"- ids: `{AUDIT_200_IDS.as_posix()}`",
        f"- sheet: `{AUDIT_200_CSV.as_posix()}`",
        f"- seed: `{man['seed']}` n=`{man['n']}`",
        "",
        "## How to label",
        "",
        "Open the CSV. For each row read `chat_block` (oldest → newest, 12 lines).",
        "Decide SPEAK or SILENT for **after the last line**. Default SILENT.",
        "Fill `label_gold` with `SPEAK` or `SILENT` only.",
        "Fill `agree_with_silver` with `Y` or `N`.",
        "Use `notes` for edge cases. Skip nothing.",
        "",
        "Rules: `reports/label_guidelines_stub.md`.",
        "",
        "## Mix (silver side, for sampling only)",
        "",
        f"- SPEAK (silver): {speak_n}",
        f"- SILENT (silver): {silent_n}",
        f"- teacher fail included: {fail_n}",
        "",
        "### bucket_actual",
        "",
        "```json",
        json.dumps(man.get("bucket_actual"), indent=2),
        "```",
        "",
        "## Resume",
        "",
        "Id file is frozen. Re-run `scripts/07_audit_sample.py` will not reshuffle.",
        "",
    ]
    AUDIT_200_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
