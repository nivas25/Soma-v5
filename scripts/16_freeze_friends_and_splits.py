"""Freeze 400 friend holdout + 1:1 / 1:3 train files. No Modal. No UI server. No LoRA."""

from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soma_data.config import (  # noqa: E402
    AUDIT_200_CSV,
    AUDIT_200_IDS,
    FRIEND_400_IDS,
    FRIEND_ASSIGNMENT_MD,
    FRIENDS_DIR,
    LABEL_QUEUE_CSV,
    MANU_200_CSV,
    PILOT_V2_2_LABELS_JSONL,
    PROMPT_VERSION_V2_2,
    PUNITH_200_CSV,
    SEED,
    SFT_DEV_JSONL,
    SFT_TEST_JSONL,
    SFT_TRAIN_1TO1_JSONL,
    SFT_TRAIN_1TO3_JSONL,
    SFT_TRAIN_JSONL,
    SPLIT_CARD_MD,
    ensure_dirs,
)
from soma_data.pilot_select import assign_strata  # noqa: E402
from soma_data.teacher_prompt_v2_2 import sft_record  # noqa: E402

N_FRIENDS = 400
N_PER_FRIEND = 200
N_SPEAK = 5100
N_SILENT_1TO1 = 5100
N_SILENT_1TO3 = 15300
FRIEND_CSV_COLUMNS = [
    "window_id",
    "split",
    "date",
    "stratum",
    "audit_bucket",
    "label_silver",
    "reason",
    "guideline_hint",
    "last_speaker",
    "last_is_question",
    "last_is_thanks",
    "addressed_to",
    "last_line",
    "chat_block",
    "raw_ok",
    "error",
    "label_gold",
    "label_source",
    "judge_reason",
    "agree_with_silver",
    "reviewed_by",
    "review_ok",
    "notes",
    "grok_draft",
    "reviewed_at",
    "labeler",
]


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        rec = json.loads(ln)
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    if path.suffix == ".jsonl":
        return {r["window_id"] for r in _load_jsonl(path) if r.get("window_id")}
    return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()}


def _lab(v: object) -> str:
    return str(v or "").strip().upper()


def last_line(chat: str) -> str:
    lines = [ln.strip() for ln in str(chat or "").splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def test_ids() -> set[str]:
    ids = _ids(SFT_TEST_JSONL)
    ids |= _ids(AUDIT_200_IDS)
    audit = pd.read_csv(AUDIT_200_CSV, dtype=str, keep_default_na=False)
    ids |= set(audit["window_id"].astype(str))
    return ids


def harvest_by_id() -> dict[str, dict]:
    by: dict[str, dict] = {}
    for r in _load_jsonl(PILOT_V2_2_LABELS_JSONL):
        wid = r.get("window_id") or ""
        lab = _lab(r.get("label_silver"))
        if not wid or wid in by:
            continue
        if r.get("raw_ok") and lab in {"SPEAK", "SILENT"}:
            by[wid] = r
    return by


def stratified_pick(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    work = df.copy()
    work["stratum"] = assign_strata(work)
    order = ["question", "addressed_not_question", "other"]
    base, extra = divmod(n, 3)
    targets = {s: base for s in order}
    targets["other"] += extra
    picked_idx: list = []
    unused_idx: list = []
    for s in order:
        pool = work.index[work["stratum"] == s].to_numpy().copy()
        rng.shuffle(pool)
        k = min(targets[s], len(pool))
        picked_idx.extend(pool[:k].tolist())
        unused_idx.extend(pool[k:].tolist())
    need = n - len(picked_idx)
    if need > len(unused_idx):
        raise AssertionError(
            f"cannot pick {n} friends: got {len(picked_idx)} + unused {len(unused_idx)} "
            f"from pool {len(work)} strata={dict(work['stratum'].value_counts())}"
        )
    rng.shuffle(unused_idx)
    picked_idx.extend(unused_idx[:need])
    out = work.loc[picked_idx].copy()
    # frozen order: shuffle once, first 200 Manu / next 200 Punith
    order_idx = rng.permutation(len(out))
    return out.iloc[order_idx].reset_index(drop=True)


def friend_sheet(rows: pd.DataFrame, bucket: str) -> pd.DataFrame:
    chats = rows["chat_block"].astype(str)
    sheet = pd.DataFrame(
        {
            "window_id": rows["window_id"].astype(str),
            "split": rows["split"].astype(str) if "split" in rows.columns else "",
            "date": rows["date"].astype(str) if "date" in rows.columns else "",
            "stratum": rows["stratum"].astype(str),
            "audit_bucket": bucket,
            "label_silver": "",
            "reason": "",
            "guideline_hint": "",
            "last_speaker": rows["last_speaker"].astype(str) if "last_speaker" in rows.columns else "",
            "last_is_question": rows["last_is_question"].astype(str) if "last_is_question" in rows.columns else "",
            "last_is_thanks": rows["last_is_thanks"].astype(str) if "last_is_thanks" in rows.columns else "",
            "addressed_to": rows["addressed_to"].astype(str) if "addressed_to" in rows.columns else "",
            "last_line": [last_line(c) for c in chats],
            "chat_block": chats,
            "raw_ok": "",
            "error": "",
            "label_gold": "",
            "label_source": "",
            "judge_reason": "",
            "agree_with_silver": "",
            "reviewed_by": "",
            "review_ok": "",
            "notes": "",
            "grok_draft": "",
            "reviewed_at": "",
            "labeler": "",
        }
    )
    return sheet[FRIEND_CSV_COLUMNS]


def assignment_md(manu: pd.DataFrame, punith: pd.DataFrame) -> str:
    def mix(df: pd.DataFrame) -> str:
        c = df["stratum"].value_counts().to_dict()
        return ", ".join(f"{k}={v}" for k, v in sorted(c.items()))

    return "\n".join(
        [
            "# Friend holdout — Manu 200 / Punith 200",
            "",
            "These 400 windows are **not gold yet**. They are a frozen holdout.",
            "They are **not** in Nivas test (audit_200) and **not** in train 1:1 or train 1:3.",
            "",
            "## Files",
            "",
            f"- **Manu:** `data/friends/manu_200.csv` (n={len(manu)}; {mix(manu)})",
            f"- **Punith:** `data/friends/punith_200.csv` (n={len(punith)}; {mix(punith)})",
            "- Combined ids: `data/friends/friend_400_ids.txt` (Manu first, then Punith)",
            "",
            "## Rules",
            "",
            "- Do **not** look at Qwen / teacher labels. The CSVs have `label_silver` empty on purpose.",
            "- Do **not** share sheets. Manu does not open Punith's file and vice versa.",
            "- `label_gold`, `labeler`, `reviewed_by`, `review_ok` start empty. The UI fills them.",
            "- Nivas 200 is test-only. Friends never go into train.",
            "",
            "## How to label (do not run until you are the annotator)",
            "",
            "```",
            "uv run python scripts/07_label_ui.py --annotator manu",
            "uv run python scripts/07_label_ui.py --annotator punith",
            "```",
            "",
            "Or start without a flag and click **Manu** / **Punith** / **Nivas** on the start screen.",
            "Finish writes `data/friends/{name}_done.csv` and `{name}_done.jsonl`.",
            "",
            f"Seed={SEED}. Stratified question / addressed_not_question / other from unlabeled queue rows.",
            "",
        ]
    )


def queue_row_to_sft(row: dict, label: str, split: str) -> dict:
    rec = sft_record(row, label, source="qwen32_v2.2", split=split)
    if "helper_in_window=" not in rec["input"]:
        raise AssertionError(f"missing helper_in_window in {row.get('window_id')}")
    return rec


def speak_silent(rows: list[dict]) -> tuple[int, int]:
    s = sum(1 for r in rows if r.get("output") == "SPEAK")
    n = sum(1 for r in rows if r.get("output") == "SILENT")
    return s, n


def main() -> None:
    ensure_dirs()
    held = test_ids()
    train1 = _load_jsonl(SFT_TRAIN_JSONL)
    if len(train1) != N_SPEAK + N_SILENT_1TO1:
        raise AssertionError(f"sft_train.jsonl n={len(train1)} expected {N_SPEAK + N_SILENT_1TO1}")
    train1_ids = {r["window_id"] for r in train1}
    if train1_ids & held:
        raise AssertionError("existing 1:1 train overlaps test")

    q = pd.read_csv(LABEL_QUEUE_CSV, dtype=str, keep_default_na=False)
    q = q.drop_duplicates("window_id")
    qmap = q.set_index("window_id", drop=False)
    harvest = harvest_by_id()
    harvest_ids = set(harvest)
    blocked = held | train1_ids

    unlabeled = q[~q["window_id"].isin(blocked | harvest_ids)].copy()
    leftover_silent = q[
        q["window_id"].isin(harvest_ids)
        & ~q["window_id"].isin(blocked)
        & q["window_id"].map(lambda i: _lab(harvest.get(i, {}).get("label_silver")) == "SILENT")
    ].copy()
    print(
        f"pool unlabeled={len(unlabeled)} harvest_silent_leftover={len(leftover_silent)} "
        f"blocked test={len(held)} train1={len(train1_ids)}"
    )
    if len(unlabeled) >= N_FRIENDS:
        pool = unlabeled
        source = "unlabeled_queue"
    else:
        pool = pd.concat([unlabeled, leftover_silent], ignore_index=True).drop_duplicates("window_id")
        source = "unlabeled_plus_harvest_silent_leftover"
    if len(pool) < N_FRIENDS:
        raise AssertionError(f"friend pool {len(pool)} < {N_FRIENDS}")

    picked = stratified_pick(pool, N_FRIENDS, SEED)
    if picked["window_id"].duplicated().any():
        raise AssertionError("duplicate friend ids")
    friend_ids = picked["window_id"].astype(str).tolist()
    if set(friend_ids) & blocked:
        raise AssertionError("friend ids leaked into train/test")

    manu = picked.iloc[:N_PER_FRIEND].copy()
    punith = picked.iloc[N_PER_FRIEND:].copy()
    if len(manu) != N_PER_FRIEND or len(punith) != N_PER_FRIEND:
        raise AssertionError("friend split sizes")

    manu_sheet = friend_sheet(manu, "friend_manu")
    punith_sheet = friend_sheet(punith, "friend_punith")
    for col in ("label_gold", "labeler", "reviewed_by", "review_ok", "label_silver", "grok_draft"):
        if manu_sheet[col].astype(str).str.strip().ne("").any() or punith_sheet[col].astype(str).str.strip().ne("").any():
            raise AssertionError(f"{col} must be empty on friend sheets")

    FRIENDS_DIR.mkdir(parents=True, exist_ok=True)
    manu_sheet.to_csv(MANU_200_CSV, index=False)
    punith_sheet.to_csv(PUNITH_200_CSV, index=False)
    FRIEND_400_IDS.write_text("\n".join(friend_ids) + "\n", encoding="utf-8")
    FRIEND_ASSIGNMENT_MD.write_text(assignment_md(manu, punith), encoding="utf-8")
    print(f"friends source={source} manu_strata={dict(manu['stratum'].value_counts())} "
          f"punith_strata={dict(punith['stratum'].value_counts())}")

    friend_set = set(friend_ids)

    # A. 1:1 — existing export, still excluding friends (by construction)
    if train1_ids & friend_set:
        raise AssertionError("1:1 overlaps friends — 1:1 would have to be rebuilt")
    for r in train1:
        if r.get("source") != "qwen32_v2.2" or r.get("prompt_version") != PROMPT_VERSION_V2_2:
            raise AssertionError("1:1 must stay qwen32_v2.2")
        if r.get("output") not in {"SPEAK", "SILENT"}:
            raise AssertionError("1:1 bad output")
        if "helper_in_window=" not in r.get("input", ""):
            raise AssertionError("1:1 missing helper_in_window")
    shutil.copy2(SFT_TRAIN_JSONL, SFT_TRAIN_1TO1_JSONL)

    # B. 1:3
    speak_h = [wid for wid, r in harvest.items() if _lab(r.get("label_silver")) == "SPEAK"]
    silent_h = [wid for wid, r in harvest.items() if _lab(r.get("label_silver")) == "SILENT"]
    speak_ok = [w for w in speak_h if w not in held and w not in friend_set]
    silent_ok = [w for w in silent_h if w not in held and w not in friend_set]
    if len(speak_ok) < N_SPEAK:
        raise AssertionError(f"SPEAK pool {len(speak_ok)} < {N_SPEAK}")
    if len(silent_ok) < N_SILENT_1TO3:
        raise AssertionError(f"SILENT pool {len(silent_ok)} < {N_SILENT_1TO3}")
    rng = np.random.default_rng(SEED)
    if len(speak_ok) == N_SPEAK:
        speak_sel = speak_ok
    else:
        speak_sel = [speak_ok[i] for i in rng.choice(len(speak_ok), size=N_SPEAK, replace=False)]
    silent_sel = [silent_ok[i] for i in rng.choice(len(silent_ok), size=N_SILENT_1TO3, replace=False)]
    mix_ids = speak_sel + silent_sel
    rng.shuffle(mix_ids)
    train13: list[dict] = []
    for wid in mix_ids:
        if wid not in qmap.index:
            raise AssertionError(f"1:3 id missing from queue {wid}")
        row = qmap.loc[wid].to_dict()
        row["last_line"] = last_line(row.get("chat_block") or "")
        lab = _lab(harvest[wid].get("label_silver"))
        train13.append(queue_row_to_sft(row, lab, "train"))
    if len(train13) != N_SPEAK + N_SILENT_1TO3:
        raise AssertionError(len(train13))
    _write_jsonl(SFT_TRAIN_1TO3_JSONL, train13)

    # C. test unchanged
    test_rows = _load_jsonl(SFT_TEST_JSONL)
    if len(test_rows) != 200:
        raise AssertionError(f"sft_test n={len(test_rows)}")
    if any(r.get("source") != "nivas_gold" for r in test_rows):
        raise AssertionError("sft_test must stay nivas_gold")

    # D. dev placeholder
    SFT_DEV_JSONL.write_text("# friends 400 after they label — future test B\n", encoding="utf-8")

    files = {
        "sft_train_1to1.jsonl": train1,
        "sft_train_1to3.jsonl": train13,
        "sft_test.jsonl": test_rows,
        "friend_400": [{"window_id": i, "output": ""} for i in friend_ids],
    }
    idsets = {
        "sft_train_1to1.jsonl": {r["window_id"] for r in train1},
        "sft_train_1to3.jsonl": {r["window_id"] for r in train13},
        "sft_test.jsonl": {r["window_id"] for r in test_rows},
        "friend_400": friend_set,
    }

    print("")
    print(f"{'file':<28} {'n':>6} {'speak':>6} {'silent':>7} {'overlap_test':>13} {'overlap_friends':>16}")
    fail = False
    rows_md = []
    for name, recs in files.items():
        n = len(recs)
        sp, si = speak_silent(recs) if name != "friend_400" else (0, 0)
        ot = 0 if name == "sft_test.jsonl" else len(idsets[name] & idsets["sft_test.jsonl"])
        of = 0 if name == "friend_400" else len(idsets[name] & friend_set)
        if ot or of:
            fail = True
        print(f"{name:<28} {n:6d} {sp:6d} {si:7d} {ot:13d} {of:16d}")
        rows_md.append((name, n, sp, si, ot, of, 100.0 * sp / n if n and name != "friend_400" else 0.0))

    # 1:1 vs 1:3 may overlap (same SPEAK, some SILENT). Must not match test/friends.
    cross_1to1_test = len(idsets["sft_train_1to1.jsonl"] & idsets["sft_test.jsonl"])
    cross_1to3_test = len(idsets["sft_train_1to3.jsonl"] & idsets["sft_test.jsonl"])
    cross_1to1_fr = len(idsets["sft_train_1to1.jsonl"] & friend_set)
    cross_1to3_fr = len(idsets["sft_train_1to3.jsonl"] & friend_set)
    cross_test_fr = len(idsets["sft_test.jsonl"] & friend_set)
    one_in_three = len(idsets["sft_train_1to1.jsonl"] & idsets["sft_train_1to3.jsonl"])
    if cross_1to1_test or cross_1to3_test or cross_1to1_fr or cross_1to3_fr or cross_test_fr:
        fail = True

    s1, n1 = speak_silent(train1)
    s3, n3 = speak_silent(train13)
    st, nt = speak_silent(test_rows)
    share = {
        "1to1_in_1to3": one_in_three,
        "friend_source": source,
        "friend_strata": dict(Counter(picked["stratum"].tolist())),
        "manu_strata": dict(Counter(manu["stratum"].tolist())),
        "punith_strata": dict(Counter(punith["stratum"].tolist())),
    }

    lines = [
        "# Split card — SOMA v2.2 freeze",
        "",
        "No LoRA. Friends are **not gold yet**. First experiment uses Nivas 200 as the only test.",
        "",
        "## Counts",
        "",
        "| file | n | SPEAK | SILENT | SPEAK % | overlap_test | overlap_friends |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, n, sp, si, ot, of, pct in rows_md:
        lines.append(f"| {name} | {n} | {sp} | {si} | {pct:.1f}% | {ot} | {of} |")
    lines += [
        "",
        f"- train 1:1 ∩ train 1:3 = {one_in_three} (expected: same 5,100 SPEAK plus shared SILENT; not a leak)",
        f"- train 1:1 ∩ test = {cross_1to1_test}",
        f"- train 1:3 ∩ test = {cross_1to3_test}",
        f"- train 1:1 ∩ friend400 = {cross_1to1_fr}",
        f"- train 1:3 ∩ friend400 = {cross_1to3_fr}",
        f"- test ∩ friend400 = {cross_test_fr}",
        f"- friend source: `{source}` (Qwen labels not copied onto friend CSVs)",
        f"- friend strata: {share['friend_strata']}",
        f"- Manu strata: {share['manu_strata']}",
        f"- Punith strata: {share['punith_strata']}",
        "",
        "## Experiment plan",
        "",
        "Primary run is **train 1:3** (5,100 SPEAK + 15,300 SILENT, closer to the room prior ~24% SPEAK) "
        f"and the ablation is **train 1:1** (5,100 / 5,100, {100.0 * s1 / (s1 + n1):.0f}% SPEAK). "
        f"Test is **Nivas 200 gold only** ({st} SPEAK / {nt} SILENT, {100.0 * st / (st + nt):.1f}% SPEAK). "
        "The 400 friend windows (Manu 200, Punith 200) stay unlabeled holdout until after that result; "
        "they are future test B, not a training mix and not gold today.",
        "",
        f"prompt_version=`{PROMPT_VERSION_V2_2}`. Train source=`qwen32_v2.2`. Test source=`nivas_gold`. Seed={SEED}.",
        "",
        "sft_dev.jsonl is empty (`# friends 400 after they label — future test B`).",
        "",
        "Label UI (do not start it from this freeze): `uv run python scripts/07_label_ui.py --annotator manu`",
        "",
    ]
    SPLIT_CARD_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"WROTE {MANU_200_CSV}")
    print(f"WROTE {PUNITH_200_CSV}")
    print(f"WROTE {FRIEND_400_IDS}")
    print(f"WROTE {FRIEND_ASSIGNMENT_MD}")
    print(f"WROTE {SFT_TRAIN_1TO1_JSONL}")
    print(f"WROTE {SFT_TRAIN_1TO3_JSONL} n={len(train13)} SPEAK={s3} SILENT={n3}")
    print(f"WROTE {SPLIT_CARD_MD}")
    print(f"1:1 inside 1:3 = {one_in_three}")
    if fail:
        raise SystemExit("FAIL overlap")
    print("OVERLAP_OK")


if __name__ == "__main__":
    main()
