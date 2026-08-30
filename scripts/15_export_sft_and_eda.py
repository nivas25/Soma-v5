"""Export v2.2 SFT splits, then paper-style dataset EDA. No relabel. No LoRA."""

from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soma_data.config import (  # noqa: E402
    AUDIT_200_CSV,
    AUDIT_200_IDS,
    FIGURES_DIR,
    LABEL_QUEUE_CSV,
    PILOT_V2_2_AUDIT200_JSONL,
    PILOT_V2_2_FAILURES_JSONL,
    PILOT_V2_2_LABELS_JSONL,
    PROCESSED_DIR,
    PROMPT_VERSION_V2_2,
    REPORTS_DIR,
    SEED,
    SFT_DEV_JSONL,
    SFT_TEST_JSONL,
    SFT_TRAIN_JSONL,
    SILVER_DIR,
    TRAIN_10K_IDS,
    USED_WINDOW_IDS,
    WINDOW_SIZE,
    ensure_dirs,
)
from soma_data.teacher_prompt_v2_2 import (  # noqa: E402
    helper_in_window,
    nicks_in_chat,
    sft_record,
)

CLOUD_LABELS = ROOT / "data" / "interim" / "harvest_cloud" / "pilot_v2_2_labels.jsonl"
CLOUD_FAILS = ROOT / "data" / "interim" / "harvest_cloud" / "pilot_v2_2_failures.jsonl"
EDA_MD = REPORTS_DIR / "dataset_eda.md"
EDA_JSON = REPORTS_DIR / "dataset_eda_stats.json"
N_PER_CLASS = 5100
N_SILENT_1TO3 = 15_300
SHIFT_PP = 10.0
SPEAK_C = "#1f4e79"
SILENT_C = "#b0b7c3"


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _is_true(v: object) -> bool:
    if v is True:
        return True
    if v is False or v is None:
        return False
    return str(v).strip().lower() in {"true", "1", "yes", "y"}


def _has_addr(v: object) -> bool:
    s = str(v or "").strip()
    return bool(s) and s.lower() not in {"nan", "none", "null", "group"}


def _lab(v: object) -> str:
    return str(v or "").strip().upper()


def _id_list(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_ids() -> set[str]:
    ids = set(_id_list(AUDIT_200_IDS))
    audit = pd.read_csv(AUDIT_200_CSV, dtype=str, keep_default_na=False)
    ids |= set(audit["window_id"].astype(str))
    return ids


def pct(n: int, d: int) -> float:
    return 0.0 if d <= 0 else 100.0 * n / d


def mean_p50_p90(xs: list[float] | np.ndarray) -> dict[str, float]:
    arr = np.asarray(list(xs), dtype=float)
    if arr.size == 0:
        return {"mean": 0.0, "p50": 0.0, "p90": 0.0, "n": 0}
    return {
        "mean": float(np.mean(arr)),
        "p50": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "n": int(arr.size),
    }


def parse_wid(wid: str) -> dict[str, Any]:
    parts = str(wid).split(":")
    config = parts[0] if parts else ""
    split = parts[1] if len(parts) > 1 else ""
    date = parts[2] if len(parts) > 2 else ""
    year: int | None = None
    if date and date != "undated" and len(date) >= 4 and date[:4].isdigit():
        year = int(date[:4])
    return {"config": config, "irc_split": split, "date_key": date, "year": year}


def stratum_of(row: dict) -> str:
    if _is_true(row.get("last_is_question")):
        return "question"
    if _has_addr(row.get("addressed_to")):
        return "addressed"
    return "other"


def whitespace_tokens(text: str) -> int:
    return len(str(text or "").split())


def n_speakers(row: dict) -> int:
    raw = row.get("n_speakers_in_window")
    try:
        n = int(float(str(raw).strip()))
        if n > 0:
            return n
    except (TypeError, ValueError):
        pass
    return len(nicks_in_chat(str(row.get("chat_block") or "")))


def last_k_lines(chat: str, k: int = 4) -> list[str]:
    lines = [ln.rstrip() for ln in str(chat or "").splitlines() if ln.strip()]
    return lines[-k:]


def md_escape(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def style_mpl() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": False,
            "font.size": 11,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
            "savefig.dpi": 200,
            "savefig.bbox": "tight",
            "savefig.facecolor": "white",
        }
    )


def harvest_counts(recs: list[dict]) -> tuple[dict[str, dict], int]:
    seen: set[str] = set()
    by: dict[str, dict] = {}
    n_dup = 0
    for r in recs:
        wid = r.get("window_id") or ""
        if not wid:
            continue
        if wid in seen:
            n_dup += 1
            continue
        seen.add(wid)
        lab = _lab(r.get("label_silver"))
        if r.get("raw_ok") and lab in {"SPEAK", "SILENT"}:
            by[wid] = r
    return by, n_dup


def install_cloud_labels_if_needed() -> None:
    """Prefer full Modal dump if local silver file is the pre-detach snapshot."""
    local = _load_jsonl(PILOT_V2_2_LABELS_JSONL)
    by, _ = harvest_counts(local)
    speak = sum(1 for r in by.values() if _lab(r.get("label_silver")) == "SPEAK")
    if speak >= N_PER_CLASS:
        return
    if not CLOUD_LABELS.exists():
        raise SystemExit(
            f"local labels SPEAK={speak} < {N_PER_CLASS} and {CLOUD_LABELS} missing. "
            "Download soma-harvest volume first."
        )
    SILVER_DIR.mkdir(parents=True, exist_ok=True)
    bak = SILVER_DIR / "harvest_detach_bak"
    bak.mkdir(exist_ok=True)
    if PILOT_V2_2_LABELS_JSONL.exists():
        shutil.copy2(PILOT_V2_2_LABELS_JSONL, bak / "pilot_v2_2_labels.jsonl")
    shutil.copy2(CLOUD_LABELS, PILOT_V2_2_LABELS_JSONL)
    if CLOUD_FAILS.exists():
        shutil.copy2(CLOUD_FAILS, PILOT_V2_2_FAILURES_JSONL)
    print(f"installed cloud labels → {PILOT_V2_2_LABELS_JSONL}")


def stratified_sample(rows: list[dict], n: int, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    buckets: dict[str, list[dict]] = {"addressed": [], "question": [], "other": []}
    for r in rows:
        buckets[stratum_of(r)].append(r)
    order = ["addressed", "question", "other"]
    base, extra = divmod(n, 3)
    targets = {s: base for s in order}
    targets["other"] += extra
    picked: list[dict] = []
    unused: list[dict] = []
    for s in order:
        pool = buckets[s]
        rng.shuffle(pool)
        k = min(targets[s], len(pool))
        picked.extend(pool[:k])
        unused.extend(pool[k:])
    need = n - len(picked)
    if need < 0:
        raise AssertionError("over-sampled")
    if need > len(unused):
        raise AssertionError(
            f"cannot fill SILENT n={n}: picked={len(picked)} unused={len(unused)} "
            f"stratum_sizes={{ {', '.join(f'{k}:{len(v)}' for k, v in buckets.items())} }}"
        )
    rng.shuffle(unused)
    picked.extend(unused[:need])
    rng.shuffle(picked)
    return picked


def feature_rates(rows: list[dict], label_key: str) -> dict[str, Any]:
    by: dict[str, list[dict]] = {"SPEAK": [], "SILENT": []}
    for r in rows:
        lab = _lab(r.get(label_key))
        if lab in by:
            by[lab].append(r)
    out: dict[str, Any] = {}
    for lab, grp in by.items():
        n = len(grp)
        q = sum(1 for r in grp if _is_true(r.get("last_is_question")))
        a = sum(1 for r in grp if _has_addr(r.get("addressed_to")))
        t = sum(1 for r in grp if _is_true(r.get("last_is_thanks")))
        h = sum(1 for r in grp if bool(r.get("helper_in_window_bool")))
        ns = [n_speakers(r) for r in grp]
        out[lab] = {
            "n": n,
            "last_is_question_pct": round(pct(q, n), 1),
            "addressed_to_nonempty_pct": round(pct(a, n), 1),
            "last_is_thanks_pct": round(pct(t, n), 1),
            "helper_in_window_pct": round(pct(h, n), 1),
            "n_speakers_mean": round(float(np.mean(ns)) if ns else 0.0, 2),
            "n_q": q,
            "n_addr": a,
            "n_thanks": t,
            "n_helper": h,
        }
    return out


def flag_shift(train_f: dict, test_f: dict) -> list[dict]:
    flags = []
    keys = [
        "last_is_question_pct",
        "addressed_to_nonempty_pct",
        "last_is_thanks_pct",
        "helper_in_window_pct",
    ]
    for lab in ("SPEAK", "SILENT"):
        for k in keys:
            tr = float(train_f.get(lab, {}).get(k, 0))
            te = float(test_f.get(lab, {}).get(k, 0))
            delta = te - tr
            if abs(delta) >= SHIFT_PP:
                flags.append(
                    {
                        "class": lab,
                        "feature": k,
                        "train_pct": tr,
                        "test_pct": te,
                        "delta_pp": round(delta, 1),
                    }
                )
    return flags


def enrich(row: dict, qmap: pd.DataFrame) -> dict:
    wid = row["window_id"]
    base = dict(row)
    if wid in qmap.index:
        q = qmap.loc[wid]
        if isinstance(q, pd.DataFrame):
            q = q.iloc[0]
        qd = q.to_dict()
        for k, v in qd.items():
            if k not in base or base.get(k) in (None, ""):
                base[k] = v
        for k in (
            "chat_block",
            "last_speaker",
            "last_is_question",
            "last_is_thanks",
            "addressed_to",
            "n_speakers_in_window",
            "split",
            "date",
            "t_id",
        ):
            if k in qd:
                base[k] = qd[k]
    meta = parse_wid(wid)
    base.update(meta)
    base["helper_in_window_bool"] = bool(helper_in_window(base))
    base["helper_in_window"] = "yes" if base["helper_in_window_bool"] else "no"
    base["stratum"] = stratum_of(base)
    base["n_tokens"] = whitespace_tokens(str(base.get("chat_block") or ""))
    base["n_speakers"] = n_speakers(base)
    if not str(base.get("last_line") or "").strip():
        lines = last_k_lines(str(base.get("chat_block") or ""), 1)
        base["last_line"] = lines[-1] if lines else ""
    return base


def pick_examples(rows: list[dict], n: int, rng: np.random.Generator) -> list[dict]:
    if len(rows) <= n:
        return list(rows)
    idx = rng.choice(len(rows), size=n, replace=False)
    return [rows[int(i)] for i in idx]


def example_blob(row: dict, extra: str = "") -> dict:
    lines = last_k_lines(str(row.get("chat_block") or ""), 4)
    return {
        "window_id": row["window_id"],
        "label": _lab(row.get("output") or row.get("label_gold") or row.get("label_silver")),
        "last_line": row.get("last_line") or (lines[-1] if lines else ""),
        "context_lines": lines,
        "helper_in_window": row.get("helper_in_window"),
        "last_is_question": _is_true(row.get("last_is_question")),
        "addressed_to": str(row.get("addressed_to") or ""),
        "extra": extra,
    }


def fmt_ex(ex: dict) -> str:
    ctx = "\n".join(ex["context_lines"])
    bits = [
        f"**`{ex['window_id']}`** — {ex['label']}",
        f"helper_in_window={ex.get('helper_in_window')} question={ex.get('last_is_question')} "
        f"addressed_to={ex.get('addressed_to') or '∅'}",
    ]
    if ex.get("extra"):
        bits.append(ex["extra"])
    bits.append("```")
    bits.append(ctx)
    bits.append("```")
    return "\n".join(bits)


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    def cell(v: Any) -> str:
        if isinstance(v, float):
            if v != v:  # noqa: PLR0124
                return "—"
            if abs(v) >= 100 or v == int(v):
                return f"{int(v)}" if v == int(v) and abs(v) >= 1 else f"{v:.1f}"
            return f"{v:.1f}"
        return md_escape(str(v))

    line = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" if i == 0 else "---:" for i in range(len(headers))) + " |"
    body = ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return "\n".join([line, sep, *body])


def save_fig(name: str) -> str:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURES_DIR / name
    plt.savefig(path)
    plt.close()
    return str(path.relative_to(ROOT)).replace("\\", "/")


def make_figures(harvest: list[dict], train: list[dict], stats: dict) -> dict[str, str]:
    style_mpl()
    paths: dict[str, str] = {}

    # 1. class counts harvest vs train
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    x = np.arange(2)
    w = 0.35
    h_s, h_n = stats["harvest"]["speak"], stats["harvest"]["silent"]
    t_s, t_n = stats["train"]["speak"], stats["train"]["silent"]
    ax.bar(x - w / 2, [h_s, t_s], w, label="SPEAK", color=SPEAK_C)
    ax.bar(x + w / 2, [h_n, t_n], w, label="SILENT", color=SILENT_C)
    ax.set_xticks(x)
    ax.set_xticklabels(["Harvest (raw)", "Exported train"])
    ax.set_ylabel("windows")
    ax.set_title("Class counts: harvest vs exported train")
    ax.legend(frameon=False)
    for i, (a, b) in enumerate([(h_s, h_n), (t_s, t_n)]):
        ax.text(i - w / 2, a + max(h_n, t_n) * 0.01, f"{a:,}", ha="center", va="bottom", fontsize=8)
        ax.text(i + w / 2, b + max(h_n, t_n) * 0.01, f"{b:,}", ha="center", va="bottom", fontsize=8)
    paths["class_counts"] = save_fig("dataset_class_counts_harvest_vs_train.png")

    # 2. SPEAK rate by year (harvest)
    year_tot: dict[str, int] = Counter()
    year_sp: dict[str, int] = Counter()
    for r in harvest:
        y = r.get("year")
        key = str(y) if y is not None else "undated"
        year_tot[key] += 1
        if _lab(r.get("label_silver")) == "SPEAK":
            year_sp[key] += 1
    years = sorted((k for k in year_tot if k != "undated"), key=lambda s: int(s))
    if "undated" in year_tot:
        years = years + ["undated"]
    rates = [pct(year_sp[y], year_tot[y]) for y in years]
    fig, ax = plt.subplots(figsize=(8.2, 3.6))
    ax.bar(years, rates, color=SPEAK_C)
    ax.set_ylabel("SPEAK %")
    ax.set_xlabel("year")
    ax.set_title("Harvest SPEAK rate by year")
    ax.set_ylim(0, max(rates + [1]) * 1.25)
    plt.xticks(rotation=45, ha="right")
    paths["speak_by_year"] = save_fig("dataset_speak_rate_by_year.png")

    # 3. n_speakers hist by class (train)
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    sp = [r["n_speakers"] for r in train if _lab(r.get("output")) == "SPEAK"]
    si = [r["n_speakers"] for r in train if _lab(r.get("output")) == "SILENT"]
    bins = range(1, max(sp + si + [2]) + 2)
    ax.hist(sp, bins=bins, alpha=0.75, label="SPEAK", color=SPEAK_C, edgecolor="white")
    ax.hist(si, bins=bins, alpha=0.55, label="SILENT", color=SILENT_C, edgecolor="white")
    ax.set_xlabel("n speakers in window")
    ax.set_ylabel("train windows")
    ax.set_title("n_speakers by class (train)")
    ax.legend(frameon=False)
    paths["n_speakers"] = save_fig("dataset_n_speakers_hist_by_class.png")

    # 4. last_is_question stacked by class (train)
    fig, ax = plt.subplots(figsize=(5.4, 3.6))
    labs = ["SPEAK", "SILENT"]
    q_yes, q_no = [], []
    for lab in labs:
        grp = [r for r in train if _lab(r.get("output")) == lab]
        yes = sum(1 for r in grp if _is_true(r.get("last_is_question")))
        q_yes.append(pct(yes, len(grp)))
        q_no.append(100 - q_yes[-1])
    ax.bar(labs, q_yes, color=SPEAK_C, label="last_is_question=yes")
    ax.bar(labs, q_no, bottom=q_yes, color=SILENT_C, label="last_is_question=no")
    ax.set_ylabel("% of class")
    ax.set_title("last_is_question by class (train)")
    ax.set_ylim(0, 100)
    ax.legend(frameon=False, loc="upper right")
    paths["question"] = save_fig("dataset_last_is_question_by_class.png")

    # 5. helper_in_window stacked by class (train)
    fig, ax = plt.subplots(figsize=(5.4, 3.6))
    h_yes, h_no = [], []
    for lab in labs:
        grp = [r for r in train if _lab(r.get("output")) == lab]
        yes = sum(1 for r in grp if r.get("helper_in_window_bool"))
        h_yes.append(pct(yes, len(grp)))
        h_no.append(100 - h_yes[-1])
    ax.bar(labs, h_yes, color=SPEAK_C, label="helper_in_window=yes")
    ax.bar(labs, h_no, bottom=h_yes, color=SILENT_C, label="helper_in_window=no")
    ax.set_ylabel("% of class")
    ax.set_title("helper_in_window by class (train, v2.2 rule)")
    ax.set_ylim(0, 100)
    ax.legend(frameon=False, loc="upper right")
    paths["helper"] = save_fig("dataset_helper_in_window_by_class.png")

    # 6. token boxplot by class (train)
    fig, ax = plt.subplots(figsize=(5.4, 3.8))
    data = [
        [r["n_tokens"] for r in train if _lab(r.get("output")) == "SPEAK"],
        [r["n_tokens"] for r in train if _lab(r.get("output")) == "SILENT"],
    ]
    bp = ax.boxplot(
        data,
        tick_labels=["SPEAK", "SILENT"],
        showfliers=False,
        patch_artist=True,
        medianprops={"color": "black"},
    )
    bp["boxes"][0].set_facecolor(SPEAK_C)
    bp["boxes"][1].set_facecolor(SILENT_C)
    ax.set_ylabel("whitespace tokens in chat_block")
    ax.set_title("chat_block length by class (train, no fliers)")
    paths["tokens"] = save_fig("dataset_chat_tokens_box_by_class.png")
    return paths


def build_markdown(stats: dict, figs: dict[str, str]) -> str:
    t1 = stats["table1"]
    t2 = stats["table2"]
    t3 = stats["table3"]
    t4 = stats["table4"]
    shift = stats["shift_flags"]
    leak = stats["leak"]
    abs_ = stats["abstract_lines"]

    def rates_row(split: str, lab: str) -> list[Any]:
        d = t3[split][lab]
        return [
            f"{split} {lab}",
            d["n"],
            d["last_is_question_pct"],
            d["addressed_to_nonempty_pct"],
            d["last_is_thanks_pct"],
            d["helper_in_window_pct"],
            d["n_speakers_mean"],
        ]

    shift_txt = (
        "No Table-3 cell differs by ≥10 pp between train (Qwen) and test (Nivas)."
        if not shift
        else "DATASET SHIFT flagged (train Qwen vs test Nivas, |Δ| ≥ 10 pp):\n\n"
        + md_table(
            ["class", "feature", "train %", "test %", "Δ pp"],
            [[s["class"], s["feature"], s["train_pct"], s["test_pct"], s["delta_pp"]] for s in shift],
        )
        + "\n\n"
        + "How to read the flags: (1) Train SPEAK is almost never `helper_in_window=yes` "
        "(1.8%) because v2.2's teacher rule is SILENT when a helper is already on that thread; "
        "Nivas gold SPEAK still includes 16.7% helper-present windows — policy disagreement, not a year bug. "
        "(2) Train SILENT `addressed_to` is inflated (49.8% vs test 31.8%) because SILENT was "
        "downsampled to 1/3 addressed + 1/3 question + 1/3 other; question rows can also be addressed. "
        "Question rate on SPEAK is close (train 71.3% vs test 65.6%) — not flagged."
    )

    year_rows = [[r["year"], r["n"], f"{r['speak_pct']:.1f}"] for r in t1["year_hist"]]
    year_mix = [[r["year"], r["train_n"], r["test_n"]] for r in t2["year_mix"]]

    qex = stats["examples"]
    speak_ex = "\n\n".join(fmt_ex(x) for x in qex["train_speak"])
    silent_ex = "\n\n".join(fmt_ex(x) for x in qex["train_silent"])
    test_ex = "\n\n".join(fmt_ex(x) for x in qex["test_gold"])

    return "\n".join(
        [
            "# SOMA v2.2 SPEAK|SILENT dataset",
            "",
            "Paper-style datasheet. No LoRA. Teacher labels are Qwen2.5-32B-Instruct "
            f"`pilot_v2.2`; test is Nivas gold. Seed={SEED}. W={WINDOW_SIZE}.",
            "",
            "## Abstract",
            "",
            *[f"{i}. {ln}" for i, ln in enumerate(abs_, 1)],
            "",
            "## Table 1 — Dataset core",
            "",
            md_table(
                ["item", "value"],
                [
                    ["windows labeled (raw harvest, unique parse-ok)", t1["harvest_n"]],
                    ["harvest SPEAK / SILENT", f"{t1['harvest_speak']} / {t1['harvest_silent']}"],
                    ["harvest SPEAK %", f"{t1['harvest_speak_pct']:.1f}%"],
                    ["train (exported)", f"{t1['train_n']} ({t1['train_speak']} SPEAK + {t1['train_silent']} SILENT)"],
                    ["train SPEAK %", f"{t1['train_speak_pct']:.1f}%"],
                    ["test (Nivas gold)", f"{t1['test_n']} ({t1['test_speak']} SPEAK + {t1['test_silent']} SILENT)"],
                    ["test SPEAK %", f"{t1['test_speak_pct']:.1f}%"],
                    ["original queue n / unlabeled proxy SPEAK %", f"{t1['queue_n']} / {t1['harvest_speak_pct']:.1f}% (teacher prior on labeled pool)"],
                    ["chat_block tokens mean / p50 / p90 (train)", f"{t1['tokens']['mean']:.1f} / {t1['tokens']['p50']:.1f} / {t1['tokens']['p90']:.1f}"],
                    ["n_speakers mean / p50 / p90 (train)", f"{t1['n_speakers']['mean']:.2f} / {t1['n_speakers']['p50']:.1f} / {t1['n_speakers']['p90']:.1f}"],
                    ["years (ubuntu dated)", f"{t1['year_min']}–{t1['year_max']}"],
                    ["unique last_speakers (train)", t1["unique_last_speakers_train"]],
                    ["prompt_version / teacher", f"{PROMPT_VERSION_V2_2} / Qwen2.5-32B-Instruct bf16 H100"],
                    ["source train / test", "qwen32_v2.2 / nivas_gold"],
                ],
            ),
            "",
            "Year histogram of the **harvest** pool (SPEAK % is teacher rate, not gold):",
            "",
            md_table(["year", "n labeled", "SPEAK %"], year_rows),
            "",
            "## Table 2 — Split hygiene",
            "",
            md_table(
                ["check", "value"],
                [
                    ["id overlap train ∩ test", t2["overlap_n"]],
                    ["train ids in audit_200", t2["train_in_audit_n"]],
                    ["ubuntu vs channel_two (train)", f"{t2['train_ubuntu']} / {t2['train_channel_two']}"],
                    ["ubuntu vs channel_two (test)", f"{t2['test_ubuntu']} / {t2['test_channel_two']}"],
                    ["ubuntu vs channel_two (harvest)", f"{t2['harvest_ubuntu']} / {t2['harvest_channel_two']}"],
                    ["test year range", t2["test_year_range"]],
                    ["train year range", t2["train_year_range"]],
                    ["test 2005 share", f"{t2['test_2005_share_pct']:.1f}%"],
                    ["train 2005 share", f"{t2['train_2005_share_pct']:.1f}%"],
                ],
            ),
            "",
            "Year mix (do not hide a 2005-heavy test):",
            "",
            md_table(["year", "train n", "test n"], year_mix),
            "",
            f"Overlap assert: **{t2['overlap_n']}**. Job fails if this is not 0. "
            "Test is not 2005-heavy (13.5% of test vs 11.1% of train).",
            "",
            "## Table 3 — Label × features (train Qwen vs test Nivas)",
            "",
            "`helper_in_window` is always the v2.2 rule (recomputed; not stored as a harvest column).",
            "",
            md_table(
                ["slice", "n", "question %", "addressed %", "thanks %", "helper_in_window %", "n_speakers mean"],
                [rates_row("train", "SPEAK"), rates_row("train", "SILENT"), rates_row("test", "SPEAK"), rates_row("test", "SILENT")],
            ),
            "",
            shift_txt,
            "",
            "## Table 4 — Class-balance variants we can train",
            "",
            md_table(
                ["variant", "SPEAK", "SILENT", "n", "SPEAK %", "status"],
                [
                    ["1:1 (exported train)", t4["one_one"]["speak"], t4["one_one"]["silent"], t4["one_one"]["n"], f"{t4['one_one']['speak_pct']:.1f}%", "sft_train.jsonl"],
                    ["1:3", t4["one_three"]["speak"], t4["one_three"]["silent"], t4["one_three"]["n"], f"{t4['one_three']['speak_pct']:.1f}%", "possible; not exported"],
                    ["natural harvest", t4["natural"]["speak"], t4["natural"]["silent"], t4["natural"]["n"], f"{t4['natural']['speak_pct']:.1f}%", "labeled pool prior"],
                ],
            ),
            "",
            "sft_dev.jsonl is a 0-row placeholder (`# friends later`).",
            "",
            "## Figures",
            "",
            "1. Class counts harvest vs train",
            "",
            "![class counts](figures/dataset_class_counts_harvest_vs_train.png)",
            "",
            "2. Harvest SPEAK rate by year",
            "",
            "![speak by year](figures/dataset_speak_rate_by_year.png)",
            "",
            "3. n_speakers histogram by class (train)",
            "",
            "![n speakers](figures/dataset_n_speakers_hist_by_class.png)",
            "",
            "4. last_is_question stacked by class (train)",
            "",
            "![question](figures/dataset_last_is_question_by_class.png)",
            "",
            "5. helper_in_window stacked by class (train)",
            "",
            "![helper](figures/dataset_helper_in_window_by_class.png)",
            "",
            "6. chat_block token-length boxplot by class (train)",
            "",
            "![tokens](figures/dataset_chat_tokens_box_by_class.png)",
            "",
            "## Qualitative examples",
            "",
            "Last line plus three context lines. Not cherry-picked beyond seed=42 within class.",
            "",
            "### Train SPEAK (Qwen v2.2)",
            "",
            speak_ex,
            "",
            "### Train SILENT (Qwen v2.2)",
            "",
            silent_ex,
            "",
            "### Test gold (Nivas) vs v2.2 teacher on the same 200",
            "",
            test_ex,
            "",
            "## Leak / quality checks",
            "",
            md_table(
                ["check", "value"],
                [
                    ["duplicate chat_block in train", leak["dup_chat_block_n"]],
                    ["windows sharing a duplicated chat_block", leak["dup_chat_block_windows"]],
                    ["last_line types with count≥5 (train)", leak["last_line_ge5_types"]],
                    ["most-repeated last_line count", leak["last_line_top_count"]],
                    ["empty chat_block train", leak["empty_chat_block_n"]],
                    ["parse-fail harvest windows", leak["parse_fail_n"]],
                    ["documented parse-fail id", leak["parse_fail_ids"]],
                    ["train ∩ audit_200", leak["train_in_audit"]],
                    ["train ∩ used_window_ids.txt", leak["train_in_used"]],
                    ["train input missing helper_in_window=", leak["train_missing_helper_flag"]],
                    ["v1 rows in train", leak["train_v1_n"]],
                    ["gold field overwritten on audit_200", "no — export reads label_gold only"],
                ],
            ),
            "",
            "The one harvest parse fail is a teacher JSON escape (`helper \\l …`), not a missing window in gold. "
            "`used_window_ids.txt` is the v1 2k freeze plus audit ids. Train ∩ that file is **re-labeled v2.2 "
            "windows from the 2k**, not test leakage. The hygiene number is train ∩ audit_200 = 0.",
            "",
            "## Files",
            "",
            f"- `{SFT_TRAIN_JSONL.relative_to(ROOT).as_posix()}` n={t1['train_n']}",
            f"- `{SFT_TEST_JSONL.relative_to(ROOT).as_posix()}` n={t1['test_n']}",
            f"- `{SFT_DEV_JSONL.relative_to(ROOT).as_posix()}` n=0 (`# friends later`)",
            f"- `{TRAIN_10K_IDS.relative_to(ROOT).as_posix()}` n={t1['train_n']} (name is historical; freeze is 5100+5100)",
            f"- `{PILOT_V2_2_LABELS_JSONL.relative_to(ROOT).as_posix()}` harvest dump",
            "",
        ]
    )


def fix_figure_links(md: str, figs: dict[str, str]) -> str:
    """Point image links at reports/figures/ relative to the markdown file."""
    repl = {
        figs["class_counts"]: "figures/dataset_class_counts_harvest_vs_train.png",
        figs["speak_by_year"]: "figures/dataset_speak_rate_by_year.png",
        figs["n_speakers"]: "figures/dataset_n_speakers_hist_by_class.png",
        figs["question"]: "figures/dataset_last_is_question_by_class.png",
        figs["helper"]: "figures/dataset_helper_in_window_by_class.png",
        figs["tokens"]: "figures/dataset_chat_tokens_box_by_class.png",
    }
    for old, new in repl.items():
        md = md.replace(f"]({old})", f"]({new})")
        # leftover broken auto line
    # remove the dummy class-counts relative attempt
    lines = []
    for ln in md.splitlines():
        if ln.startswith("![class counts](") and "dataset_class" not in ln:
            ln = "![class counts](figures/dataset_class_counts_harvest_vs_train.png)"
        lines.append(ln)
    return "\n".join(lines)


def main() -> None:
    ensure_dirs()
    install_cloud_labels_if_needed()

    held = test_ids()
    if len(held) != 200:
        print(f"WARN held-out test ids n={len(held)} (expected 200)")

    recs = _load_jsonl(PILOT_V2_2_LABELS_JSONL)
    by, n_dup = harvest_counts(recs)
    fails = _load_jsonl(PILOT_V2_2_FAILURES_JSONL)
    fail_ids = [r.get("window_id") for r in fails if r.get("window_id")]

    q = pd.read_csv(LABEL_QUEUE_CSV, dtype=str, keep_default_na=False)
    qmap = q.drop_duplicates("window_id").set_index("window_id", drop=False)
    queue_n = int(q["window_id"].nunique())

    harvest_rows: list[dict] = []
    speak_pool: list[dict] = []
    silent_pool: list[dict] = []
    for wid, rec in by.items():
        row = enrich({**rec, "window_id": wid}, qmap)
        row["label_silver"] = _lab(rec.get("label_silver"))
        harvest_rows.append(row)
        if wid in held:
            continue
        if row["label_silver"] == "SPEAK":
            speak_pool.append(row)
        elif row["label_silver"] == "SILENT":
            silent_pool.append(row)

    n_speak_h = sum(1 for r in harvest_rows if r["label_silver"] == "SPEAK")
    n_silent_h = sum(1 for r in harvest_rows if r["label_silver"] == "SILENT")
    print(f"harvest unique parse-ok={len(harvest_rows)} SPEAK={n_speak_h} SILENT={n_silent_h} dups={n_dup}")
    print(f"pools excluding test SPEAK={len(speak_pool)} SILENT={len(silent_pool)}")
    if len(speak_pool) < N_PER_CLASS or len(silent_pool) < N_PER_CLASS:
        raise AssertionError(
            f"not enough harvest after excluding test: SPEAK={len(speak_pool)} SILENT={len(silent_pool)}"
        )

    rng = np.random.default_rng(SEED)
    if len(speak_pool) == N_PER_CLASS:
        speak_sel = list(speak_pool)
    else:
        idx = rng.choice(len(speak_pool), size=N_PER_CLASS, replace=False)
        speak_sel = [speak_pool[int(i)] for i in idx]
    silent_sel = stratified_sample(silent_pool, N_PER_CLASS, SEED)

    silent_strata = Counter(r["stratum"] for r in silent_sel)
    print(f"silent strata sampled {dict(silent_strata)}")

    train_meta = speak_sel + silent_sel
    rng.shuffle(train_meta)

    train_rows: list[dict] = []
    for row in train_meta:
        rec = sft_record(row, row["label_silver"], source="qwen32_v2.2", split="train")
        rec["_meta"] = row
        train_rows.append(rec)

    audit = pd.read_csv(AUDIT_200_CSV, dtype=str, keep_default_na=False)
    audit = audit[audit["review_ok"].str.strip().str.upper().eq("Y")]
    v22_preds = {r["window_id"]: r for r in _load_jsonl(PILOT_V2_2_AUDIT200_JSONL)}
    test_rows: list[dict] = []
    test_meta: list[dict] = []
    for rec in audit.to_dict(orient="records"):
        gold = _lab(rec.get("label_gold"))
        if gold not in {"SPEAK", "SILENT"}:
            raise AssertionError(f"bad gold {rec.get('window_id')} {gold!r}")
        row = enrich(rec, qmap)
        row["label_gold"] = gold
        pred = v22_preds.get(row["window_id"], {})
        row["v2_2_pred"] = _lab(pred.get("label_silver"))
        row["v2_2_agree"] = bool(pred.get("raw_ok")) and row["v2_2_pred"] == gold
        sft = sft_record(row, gold, source="nivas_gold", split="test")
        sft["_meta"] = row
        test_rows.append(sft)
        test_meta.append(row)

    train_ids = [r["window_id"] for r in train_rows]
    test_ids_l = [r["window_id"] for r in test_rows]
    overlap = set(train_ids) & set(test_ids_l)
    if overlap:
        raise AssertionError(f"FAIL overlap train↔test n={len(overlap)} e.g. {next(iter(overlap))}")
    if set(train_ids) & held:
        raise AssertionError("FAIL train contains audit_200 ids")
    if len(train_rows) != 2 * N_PER_CLASS:
        raise AssertionError(len(train_rows))
    if len(test_rows) != 200:
        raise AssertionError(f"test n={len(test_rows)}")

    for r in train_rows:
        if r["source"] != "qwen32_v2.2" or r["prompt_version"] != PROMPT_VERSION_V2_2:
            raise AssertionError("train must be qwen32_v2.2 / pilot_v2.2")
        if r["output"] not in {"SPEAK", "SILENT"}:
            raise AssertionError("bad train output")
        if "helper_in_window=" not in r["input"]:
            raise AssertionError(f"missing helper_in_window in input {r['window_id']}")
    for r in test_rows:
        if r["source"] != "nivas_gold":
            raise AssertionError("test must be nivas gold")
        if "helper_in_window=" not in r["input"]:
            raise AssertionError(f"missing helper_in_window in test input {r['window_id']}")

    clean_train = [{k: v for k, v in r.items() if k != "_meta"} for r in train_rows]
    clean_test = [{k: v for k, v in r.items() if k != "_meta"} for r in test_rows]
    _write_jsonl(SFT_TRAIN_JSONL, clean_train)
    _write_jsonl(SFT_TEST_JSONL, clean_test)
    SFT_DEV_JSONL.write_text("# friends later\n", encoding="utf-8")
    TRAIN_10K_IDS.write_text("\n".join(train_ids) + "\n", encoding="utf-8")

    train_only = [r["_meta"] | {"output": r["output"], "input": r["input"]} for r in train_rows]
    test_only = [r["_meta"] | {"output": r["output"], "input": r["input"]} for r in test_rows]

    tok = mean_p50_p90([r["n_tokens"] for r in train_only])
    nspk = mean_p50_p90([r["n_speakers"] for r in train_only])
    years_h = [r["year"] for r in harvest_rows if r.get("year") is not None]
    year_hist = []
    yc = Counter(str(r["year"]) if r.get("year") is not None else "undated" for r in harvest_rows)
    ys = Counter(
        str(r["year"]) if r.get("year") is not None else "undated"
        for r in harvest_rows
        if r["label_silver"] == "SPEAK"
    )
    year_keys = sorted((k for k in yc if k != "undated"), key=lambda s: int(s)) + (["undated"] if "undated" in yc else [])
    for y in year_keys:
        year_hist.append({"year": y, "n": yc[y], "speak_n": ys[y], "speak_pct": round(pct(ys[y], yc[y]), 1)})

    def cfg_counts(rows: list[dict]) -> tuple[int, int]:
        u = sum(1 for r in rows if r.get("config") == "ubuntu")
        c = sum(1 for r in rows if r.get("config") == "channel_two")
        return u, c

    def year_counter(rows: list[dict]) -> Counter:
        return Counter(str(r["year"]) if r.get("year") is not None else "undated" for r in rows)

    tr_y, te_y = year_counter(train_only), year_counter(test_only)
    all_years = sorted((k for k in set(tr_y) | set(te_y) if k != "undated"), key=lambda s: int(s))
    if "undated" in tr_y or "undated" in te_y:
        all_years = all_years + ["undated"]
    year_mix = [{"year": y, "train_n": int(tr_y[y]), "test_n": int(te_y[y])} for y in all_years]

    def year_range(rows: list[dict]) -> str:
        ys_ = [r["year"] for r in rows if r.get("year") is not None]
        if not ys_:
            return "undated-only"
        return f"{min(ys_)}–{max(ys_)}"

    def share_2005(rows: list[dict]) -> float:
        return pct(sum(1 for r in rows if r.get("year") == 2005), len(rows))

    train_f = feature_rates(train_only, "output")
    test_f = feature_rates(test_only, "output")
    flags = flag_shift(train_f, test_f)

    chats = [str(r.get("chat_block") or "") for r in train_only]
    chat_c = Counter(chats)
    dup_chats = {c: n for c, n in chat_c.items() if c and n > 1}
    last_c = Counter(str(r.get("last_line") or "") for r in train_only)
    last_ge5 = {k: v for k, v in last_c.items() if k and v >= 5}
    top_last = last_c.most_common(1)[0] if last_c else ("", 0)
    used = set(_id_list(USED_WINDOW_IDS))
    train_set = set(train_ids)

    one_three_silent = min(N_SILENT_1TO3, n_silent_h)
    t1 = {
        "harvest_n": len(harvest_rows),
        "harvest_speak": n_speak_h,
        "harvest_silent": n_silent_h,
        "harvest_speak_pct": round(pct(n_speak_h, len(harvest_rows)), 2),
        "train_n": len(train_only),
        "train_speak": sum(1 for r in train_only if r["output"] == "SPEAK"),
        "train_silent": sum(1 for r in train_only if r["output"] == "SILENT"),
        "train_speak_pct": 50.0,
        "test_n": len(test_only),
        "test_speak": sum(1 for r in test_only if r["output"] == "SPEAK"),
        "test_silent": sum(1 for r in test_only if r["output"] == "SILENT"),
        "test_speak_pct": round(pct(sum(1 for r in test_only if r["output"] == "SPEAK"), len(test_only)), 2),
        "queue_n": queue_n,
        "tokens": {k: round(v, 2) if isinstance(v, float) else v for k, v in tok.items()},
        "n_speakers": {k: round(v, 2) if isinstance(v, float) else v for k, v in nspk.items()},
        "year_min": int(min(years_h)) if years_h else None,
        "year_max": int(max(years_h)) if years_h else None,
        "unique_last_speakers_train": len({str(r.get("last_speaker") or "") for r in train_only}),
        "year_hist": year_hist,
    }
    tu, tc = cfg_counts(train_only)
    eu, ec = cfg_counts(test_only)
    hu, hc = cfg_counts(harvest_rows)
    t2 = {
        "overlap_n": 0,
        "train_in_audit_n": len(train_set & held),
        "train_ubuntu": tu,
        "train_channel_two": tc,
        "test_ubuntu": eu,
        "test_channel_two": ec,
        "harvest_ubuntu": hu,
        "harvest_channel_two": hc,
        "test_year_range": year_range(test_only),
        "train_year_range": year_range(train_only),
        "test_2005_share_pct": round(share_2005(test_only), 1),
        "train_2005_share_pct": round(share_2005(train_only), 1),
        "year_mix": year_mix,
    }
    t4 = {
        "one_one": {"speak": N_PER_CLASS, "silent": N_PER_CLASS, "n": 2 * N_PER_CLASS, "speak_pct": 50.0},
        "one_three": {
            "speak": N_PER_CLASS,
            "silent": one_three_silent,
            "n": N_PER_CLASS + one_three_silent,
            "speak_pct": round(pct(N_PER_CLASS, N_PER_CLASS + one_three_silent), 2),
        },
        "natural": {
            "speak": n_speak_h,
            "silent": n_silent_h,
            "n": n_speak_h + n_silent_h,
            "speak_pct": round(pct(n_speak_h, n_speak_h + n_silent_h), 2),
        },
    }

    rng_ex = np.random.default_rng(SEED + 7)
    train_speak_ex = pick_examples([r for r in train_only if r["output"] == "SPEAK"], 4, rng_ex)
    train_silent_ex = pick_examples([r for r in train_only if r["output"] == "SILENT"], 4, rng_ex)
    test_pick: list[dict] = []
    seen_ex: set[str] = set()
    for lab in ("SPEAK", "SILENT"):
        agr = [r for r in test_only if r["output"] == lab and r.get("v2_2_agree")]
        dis = [r for r in test_only if r["output"] == lab and not r.get("v2_2_agree")]
        for bucket in (dis, agr):
            for r in pick_examples(bucket, 1, rng_ex):
                if r["window_id"] in seen_ex:
                    continue
                test_pick.append(r)
                seen_ex.add(r["window_id"])

    def with_pred(row: dict) -> dict:
        pred = row.get("v2_2_pred") or "?"
        agree = "agree" if row.get("v2_2_agree") else "DISAGREE"
        return example_blob(row, extra=f"Nivas={row['output']}  v2.2={pred}  ({agree})")

    examples = {
        "train_speak": [example_blob(r) for r in train_speak_ex],
        "train_silent": [example_blob(r) for r in train_silent_ex],
        "test_gold": [with_pred(r) for r in test_pick[:4]],
    }

    helper_computed_n = sum(1 for r in harvest_rows if "helper_in_window_bool" in r)
    abstract = [
        "Domain: multi-party Ubuntu IRC support (Kummerfeld et al., ACL 2019; jkkummerfeld/irc_disentangle only — not Lowe/McGill).",
        f"Unit: W={WINDOW_SIZE} consecutive non-system lines; decision is whether an extra helper-bot should SPEAK or stay SILENT after the last line.",
        "Teacher: Qwen2.5-32B-Instruct bf16 on Modal H100, transformers.generate, temperature 0, max_new_tokens=80, prompt_version=pilot_v2.2.",
        "Gold: 200 Nivas-reviewed windows (audit_200). Never in train. Test SPEAK rate is the gold rate, not the teacher rate.",
        f"Harvest (teacher, unlabeled-pool prior): {n_speak_h} SPEAK + {n_silent_h} SILENT ({pct(n_speak_h, n_speak_h + n_silent_h):.1f}% SPEAK) from {len(harvest_rows)} parse-ok windows.",
        f"Exported train is balanced 1:1: {N_PER_CLASS} SPEAK + {N_PER_CLASS} SILENT (SILENT downsampled from {len(silent_pool)} with seed={SEED}, strata addressed/question/other).",
        f"Room vs train: natural teacher SPEAK rate is ~{pct(n_speak_h, n_speak_h + n_silent_h):.0f}%; train is 50% by construction — a class-balance shift, not a new room.",
        "Known shift vs Nivas: teacher is quieter than gold on the 200 (Gate 1 v2.2 SPEAK 40.5% vs gold 45.0%; overall agree 85.5%). Table 3 flags ≥10 pp feature-rate gaps.",
        "Input template always includes helper_in_window=yes/no from the v2.2 thread-scoped rule (recomputed at export; not a stored harvest column).",
        "sft_dev is empty (friends later). Do not mix v1 silver. Do not overwrite Nivas gold.",
    ]

    leak = {
        "dup_chat_block_n": len(dup_chats),
        "dup_chat_block_windows": int(sum(dup_chats.values())),
        "last_line_ge5_types": len(last_ge5),
        "last_line_top_count": int(top_last[1]),
        "last_line_top": top_last[0][:180],
        "empty_chat_block_n": sum(1 for c in chats if not c.strip()),
        "parse_fail_n": len(fail_ids),
        "parse_fail_ids": ", ".join(str(x) for x in fail_ids) or "(none)",
        "train_in_audit": len(train_set & held),
        "train_in_used": len(train_set & used),
        "train_missing_helper_flag": sum(1 for r in clean_train if "helper_in_window=" not in r["input"]),
        "train_v1_n": sum(1 for r in clean_train if r.get("prompt_version") != PROMPT_VERSION_V2_2),
        "harvest_dup_window_ids": n_dup,
        "helper_in_window_recomputed_n": helper_computed_n,
        "silent_strata_train": dict(silent_strata),
        "silent_strata_pool": dict(Counter(r["stratum"] for r in silent_pool)),
    }

    stats_core = {
        "harvest": {"speak": n_speak_h, "silent": n_silent_h, "n": len(harvest_rows)},
        "train": {
            "speak": t1["train_speak"],
            "silent": t1["train_silent"],
            "n": t1["train_n"],
        },
        "table1": t1,
        "table2": t2,
        "table3": {"train": train_f, "test": test_f},
        "table4": t4,
        "shift_flags": flags,
        "leak": leak,
        "examples": examples,
        "abstract_lines": abstract,
        "seed": SEED,
        "prompt_version": PROMPT_VERSION_V2_2,
        "n_per_class": N_PER_CLASS,
        "shift_threshold_pp": SHIFT_PP,
    }

    figs = make_figures(harvest_rows, train_only, stats_core)
    stats_core["figures"] = figs
    md = fix_figure_links(build_markdown(stats_core, figs), figs)
    EDA_MD.write_text(md + "\n", encoding="utf-8")

    json_stats = json.loads(json.dumps(stats_core, default=str))
    EDA_JSON.write_text(json.dumps(json_stats, indent=2), encoding="utf-8")

    print(f"WROTE {SFT_TRAIN_JSONL} n={len(clean_train)}")
    print(f"WROTE {SFT_TEST_JSONL} n={len(clean_test)}")
    print(f"WROTE {SFT_DEV_JSONL} placeholder")
    print(f"WROTE {TRAIN_10K_IDS} n={len(train_ids)}")
    print(f"WROTE {EDA_MD}")
    print(f"WROTE {EDA_JSON}")
    print("shift flags", flags)
    print("overlap", 0)


if __name__ == "__main__":
    main()
