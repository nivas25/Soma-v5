"""Freeze a 2,000-row pilot set from label_queue.csv. Never reshuffle once written."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from soma_data.config import (
    LABEL_QUEUE_CSV,
    PILOT_2K_IDS,
    PILOT_2K_MANIFEST,
    PILOT_N,
    PILOT_STRATA,
    PROMPT_VERSION,
    SEED,
    TEACHER_MAX_NEW_TOKENS,
    TEACHER_TEMPERATURE,
    TEACHER_TOP_P,
    USED_WINDOW_IDS,
    ensure_dirs,
)


def _is_true(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def _has_addr(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    return series.notna() & s.ne("") & s.str.lower().ne("nan") & s.str.lower().ne("none") & s.str.lower().ne("null")


def assign_strata(df: pd.DataFrame) -> pd.Series:
    is_q = _is_true(df["last_is_question"])
    addr = _has_addr(df["addressed_to"])
    stratum = pd.Series("other", index=df.index, dtype="object")
    stratum = stratum.mask(addr & ~is_q, "addressed_not_question")
    stratum = stratum.mask(is_q, "question")
    return stratum


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def select_pilot(
    df: pd.DataFrame,
    *,
    seed: int = SEED,
    n: int = PILOT_N,
    targets: dict[str, int] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Deterministic stratified sample. Returns frozen rows sorted by window_id."""
    targets = dict(targets or PILOT_STRATA)
    work = df.copy()
    work["stratum"] = assign_strata(work)
    rng = np.random.default_rng(seed)

    picked_parts: list[pd.DataFrame] = []
    actual: dict[str, int] = {}
    fill_notes: list[str] = []
    taken_ids: set[str] = set()

    def _take(pool: pd.DataFrame, k: int) -> pd.DataFrame:
        if k <= 0 or pool.empty:
            return pool.iloc[0:0]
        k = min(k, len(pool))
        idx = rng.choice(pool.index.to_numpy(), size=k, replace=False)
        return pool.loc[idx]

    for name in ("question", "addressed_not_question", "other"):
        need = int(targets.get(name, 0))
        pool = work.loc[work["stratum"].eq(name) & ~work["window_id"].isin(taken_ids)]
        part = _take(pool, need)
        actual[name] = int(len(part))
        taken_ids.update(part["window_id"].tolist())
        picked_parts.append(part)
        if len(part) < need:
            fill_notes.append(f"{name}: wanted {need}, had {len(part)}")

    selected = pd.concat(picked_parts, ignore_index=True) if picked_parts else work.iloc[0:0]
    short = n - len(selected)
    if short > 0:
        leftover = work.loc[~work["window_id"].isin(taken_ids)]
        extra = _take(leftover, short)
        fill_notes.append(f"filled {len(extra)} from remaining queue to reach {n}")
        selected = pd.concat([selected, extra], ignore_index=True)
        for name, cnt in extra["stratum"].value_counts().to_dict().items():
            actual[str(name)] = actual.get(str(name), 0) + int(cnt)

    if len(selected) > n:
        selected = selected.sample(n=n, random_state=seed)

    selected = selected.sort_values("window_id", kind="mergesort").reset_index(drop=True)
    if selected["window_id"].duplicated().any():
        raise AssertionError("duplicate window_id in pilot selection")
    if len(selected) != n:
        raise AssertionError(f"pilot size {len(selected)} != {n}")
    meta = {
        "stratum_targets": targets,
        "stratum_actual": {k: int(v) for k, v in selected["stratum"].value_counts().to_dict().items()},
        "stratum_sampled_before_sort": actual,
        "stratum_fill": fill_notes,
    }
    return selected, meta


def freeze_pilot_ids(*, force: bool = False) -> dict[str, Any]:
    """Write ids + manifest. Refuses to overwrite an existing freeze."""
    ensure_dirs()
    if PILOT_2K_IDS.exists() and not force:
        existing = [ln.strip() for ln in PILOT_2K_IDS.read_text(encoding="utf-8").splitlines() if ln.strip()]
        logger.warning("pilot id file already frozen ({} ids) at {} — not reshuffling", len(existing), PILOT_2K_IDS)
        if PILOT_2K_MANIFEST.exists():
            return json.loads(PILOT_2K_MANIFEST.read_text(encoding="utf-8"))
        raise FileExistsError(f"{PILOT_2K_IDS} exists but manifest is missing")

    if not LABEL_QUEUE_CSV.exists():
        raise FileNotFoundError(f"missing {LABEL_QUEUE_CSV}")

    src_hash = sha256_file(LABEL_QUEUE_CSV)
    df = pd.read_csv(LABEL_QUEUE_CSV, dtype=str, keep_default_na=False)
    selected, meta = select_pilot(df, seed=SEED, n=PILOT_N)
    ids = selected["window_id"].tolist()

    PILOT_2K_IDS.write_text("\n".join(ids) + "\n", encoding="utf-8")
    _append_used(ids)

    manifest = {
        "n": len(ids),
        "seed": SEED,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_file": str(LABEL_QUEUE_CSV.as_posix()),
        "source_sha256": src_hash,
        "window_ids": ids,
        "strata": selected[["window_id", "stratum"]].to_dict(orient="records"),
        **meta,
        "prompt_version": PROMPT_VERSION,
        "inference": {
            "temperature": TEACHER_TEMPERATURE,
            "top_p": TEACHER_TOP_P,
            "max_new_tokens": TEACHER_MAX_NEW_TOKENS,
            "json_only": True,
            "one_window_per_prompt": True,
        },
        "model_id": None,
        "model_revision": None,
        "backend": None,
        "gpu": None,
        "note": "model_* filled after first successful teacher call. Do not reshuffle these ids.",
    }
    PILOT_2K_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("froze {} ids → {}", len(ids), PILOT_2K_IDS)
    logger.info("strata {}", manifest["stratum_actual"])
    return manifest


def _append_used(ids: list[str]) -> None:
    existing: set[str] = set()
    if USED_WINDOW_IDS.exists():
        existing = {ln.strip() for ln in USED_WINDOW_IDS.read_text(encoding="utf-8").splitlines() if ln.strip()}
    new = [i for i in ids if i not in existing]
    if not new:
        logger.info("used_window_ids already contains this freeze")
        return
    with USED_WINDOW_IDS.open("a", encoding="utf-8") as fh:
        for i in new:
            fh.write(i + "\n")
    logger.info("appended {} ids → {}", len(new), USED_WINDOW_IDS)


def load_frozen_ids() -> list[str]:
    if not PILOT_2K_IDS.exists():
        raise FileNotFoundError(f"{PILOT_2K_IDS} missing. Run scripts/05_select_pilot_2k.py")
    ids = [ln.strip() for ln in PILOT_2K_IDS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(ids) != PILOT_N:
        raise AssertionError(f"frozen id count {len(ids)} != {PILOT_N}")
    return ids
