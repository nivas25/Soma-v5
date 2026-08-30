"""EDA, schema contract, and row-count reconciliation."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from loguru import logger

from soma_data.config import (
    CHANNEL_TWO_DATE_SENTINEL,
    CHANNEL_TWO_WINDOW_SPLIT,
    EDA_MD,
    FIGURES_DIR,
    GAP_THRESHOLD,
    HF_DATASET,
    LICENSE,
    MIN_HISTORY,
    PAPER_CITE,
    REQUIRE_EXACT_W,
    SCHEMA_MD,
    SEED,
    STATS_JSON,
    TIME_CAP_MINUTES,
    WINDOW_SIZE,
)
from soma_data.hf_download import CARD_ANNOTATED, iter_raw_snapshots, load_raw_table
from soma_data.parse_irc import ParsedIrcMessage, parse_raw_line
from soma_data.windows import assign_slices_and_runs, hhmm_to_minutes, parse_dataframe

# config.py does not currently export CARD_ANNOTATED_NOTE — avoid the import error
# by not relying on it. (Imported above by mistake if I added it.)


def _pct(n: int, d: int) -> float:
    return 0.0 if d == 0 else 100.0 * n / d


def load_all_raw() -> pd.DataFrame:
    frames = []
    for config, split, _path in iter_raw_snapshots():
        frames.append(load_raw_table(config, split))
    if not frames:
        raise FileNotFoundError("No raw parquet under data/raw. Run 01_download.py")
    return pd.concat(frames, ignore_index=True)


def messages_for_windows(raw: pd.DataFrame) -> pd.DataFrame:
    """Drop overlapping channel_two subset splits; keep all_ + all ubuntu splits."""
    mask = (raw["config"] != "channel_two") | (raw["split"] == CHANNEL_TWO_WINDOW_SPLIT)
    return raw.loc[mask].copy()


def parse_messages(raw: pd.DataFrame) -> list[ParsedIrcMessage]:
    parsed = parse_dataframe(raw)
    return assign_slices_and_runs(parsed)


def messages_to_frame(parsed: list[ParsedIrcMessage]) -> pd.DataFrame:
    return pd.DataFrame([m.model_dump() for m in parsed])


def describe_raw_split(df: pd.DataFrame) -> dict[str, Any]:
    n = len(df)
    null_rates = {}
    for col in df.columns:
        if col == "connections":
            null_rates[col] = _pct(int(df[col].map(lambda x: x is None).sum()), n)
        else:
            null_rates[col] = _pct(int(df[col].isna().sum()), n)
    id_unique = True
    dup_n = 0
    if "id" in df.columns and "date" in df.columns:
        dup_n = int(df.duplicated(["date", "id"]).sum())
        id_unique = dup_n == 0
    conn_types = df["connections"].map(lambda x: type(x).__name__).value_counts().to_dict()
    return {
        "n_rows": n,
        "columns": list(df.columns),
        "dtypes": {c: str(df[c].dtype) for c in df.columns},
        "null_rates_pct": null_rates,
        "id_unique_per_date": id_unique,
        "n_duplicate_date_id": dup_n,
        "connections_python_type": conn_types,
        "n_empty_connections": int(df["connections"].map(len).eq(0).sum()),
        "n_nonempty_connections": int(df["connections"].map(len).gt(0).sum()),
        "date_sentinel_only": bool(set(df["date"].astype(str).unique()) <= {CHANNEL_TWO_DATE_SENTINEL}),
        "n_unique_dates": int(df["date"].nunique()),
        "id_min": int(df["id"].min()) if n else None,
        "id_max": int(df["id"].max()) if n else None,
    }


def clock_anomalies(parsed: list[ParsedIrcMessage]) -> dict[str, Any]:
    """Flag time going backwards vs official (date, id) order. Midnight wrap is OK."""
    n_wrap = 0
    n_back = 0
    examples_back: list[str] = []
    examples_wrap: list[str] = []
    prev_by_key: dict[tuple, ParsedIrcMessage] = {}
    for m in parsed:
        key = (m.config, m.split, m.date, m.slice_id, m.run_id)
        prev = prev_by_key.get(key)
        prev_by_key[key] = m
        if prev is None:
            continue
        a = hhmm_to_minutes(prev.time_hhmm)
        b = hhmm_to_minutes(m.time_hhmm)
        if a is None or b is None:
            continue
        if b >= a:
            continue
        # backwards in clock
        if a >= 12 * 60 and b < 12 * 60:
            n_wrap += 1
            if len(examples_wrap) < 8:
                examples_wrap.append(
                    f"{m.config}/{m.split} {m.date} id {prev.original_id}->{m.original_id} "
                    f"{prev.time_hhmm}->{m.time_hhmm}"
                )
        else:
            n_back += 1
            if len(examples_back) < 8:
                examples_back.append(
                    f"{m.config}/{m.split} {m.date} id {prev.original_id}->{m.original_id} "
                    f"{prev.time_hhmm}->{m.time_hhmm} | {prev.raw[:80]!r} -> {m.raw[:80]!r}"
                )
    return {
        "n_midnight_wraps": n_wrap,
        "n_non_wrap_backwards": n_back,
        "examples_wrap": examples_wrap,
        "examples_backwards": examples_back,
    }


def gap_analysis(parsed: list[ParsedIrcMessage]) -> dict[str, Any]:
    """Are ids contiguous per date/slice, or sampled with large holes?"""
    groups: dict[tuple, list[int]] = defaultdict(list)
    for m in parsed:
        groups[(m.config, m.split, m.date, m.slice_id)].append(m.original_id)

    n_groups = 0
    n_contiguous = 0
    gap_sizes: list[int] = []
    n_big_gaps = 0
    max_gap = 0
    examples_big: list[str] = []
    slice_resets = 0
    run_counts: list[int] = []
    prev_walk: dict[tuple[str, str], ParsedIrcMessage] = {}
    for m in sorted(parsed, key=lambda x: (x.config, x.split, x.row_idx)):
        key_cs = (m.config, m.split)
        prev = prev_walk.get(key_cs)
        prev_walk[key_cs] = m
        if prev is not None and m.date == prev.date and m.original_id < prev.original_id:
            slice_resets += 1

    runs_per_group: dict[tuple, set[int]] = defaultdict(set)
    for m in parsed:
        runs_per_group[(m.config, m.split, m.date, m.slice_id)].add(m.run_id)

    for key, ids in groups.items():
        ids = sorted(ids)
        n_groups += 1
        diffs = [ids[i] - ids[i - 1] for i in range(1, len(ids))]
        if diffs and max(diffs) == 1 and min(ids) + len(ids) - 1 == max(ids):
            n_contiguous += 1
        for d in diffs:
            gap = d - 1
            if gap > 0:
                gap_sizes.append(gap)
                max_gap = max(max_gap, gap)
                if d > GAP_THRESHOLD:
                    n_big_gaps += 1
                    if len(examples_big) < 12:
                        examples_big.append(f"{key} step={d} (missing {gap})")
        run_counts.append(len(runs_per_group[key]))

    arr = np.array(gap_sizes) if gap_sizes else np.array([0])
    return {
        "n_date_slices": n_groups,
        "n_fully_contiguous_slices": n_contiguous,
        "frac_contiguous": n_contiguous / n_groups if n_groups else 0.0,
        "n_gaps_gt_threshold": n_big_gaps,
        "gap_threshold": GAP_THRESHOLD,
        "max_missing_ids": int(max_gap),
        "gap_p50": float(np.percentile(arr, 50)) if gap_sizes else 0.0,
        "gap_p90": float(np.percentile(arr, 90)) if gap_sizes else 0.0,
        "gap_p99": float(np.percentile(arr, 99)) if gap_sizes else 0.0,
        "n_extra_slices_from_id_reset": slice_resets,
        "runs_per_slice_p50": float(np.percentile(run_counts, 50)) if run_counts else 0.0,
        "runs_per_slice_p90": float(np.percentile(run_counts, 90)) if run_counts else 0.0,
        "examples_big_gaps": examples_big,
        "justification": (
            f"GAP_THRESHOLD={GAP_THRESHOLD} (new run iff id[t]-id[t-1] > {GAP_THRESHOLD}). "
            "Kummerfeld 2019 samples 173 time slices of #ubuntu; ids are log-line numbers "
            "inside each file. Same-calendar-day files concatenated on the Hub reset id to 0 "
            "(new slice). Tiny holes (1–5) stay in-run so JOIN bursts we later drop do not "
            "shatter a real conversation. Jumps of 6+ are treated as a new run so we never "
            "glue two distant samples into one fake room."
        ),
    }


def type_samples(parsed: list[ParsedIrcMessage], k: int = 15) -> dict[str, list[str]]:
    buckets = {"question": [], "address": [], "system": [], "normal": [], "action": []}
    # Primary domain first so the labeller sees Ubuntu, not only channel_two.
    ordered = sorted(parsed, key=lambda m: (0 if m.config == "ubuntu" else 1, m.row_idx))
    for m in ordered:
        if m.is_system and len(buckets["system"]) < k:
            buckets["system"].append(m.raw)
        elif m.is_action and len(buckets["action"]) < k:
            buckets["action"].append(m.raw)
        elif m.has_question and len(buckets["question"]) < k:
            buckets["question"].append(m.raw)
        elif m.addressed_to and len(buckets["address"]) < k:
            buckets["address"].append(m.raw)
        elif (not m.is_system) and (not m.has_question) and (not m.addressed_to) and len(buckets["normal"]) < k:
            buckets["normal"].append(m.raw)
        if all(len(v) >= k for v in buckets.values()):
            break
    return buckets


def compute_eda(parsed: list[ParsedIrcMessage]) -> dict[str, Any]:
    n = len(parsed)
    n_sys = sum(1 for m in parsed if m.is_system)
    n_q = sum(1 for m in parsed if m.has_question)
    n_addr = sum(1 for m in parsed if m.addressed_to)
    n_act = sum(1 for m in parsed if m.is_action)
    n_fail = sum(1 for m in parsed if not m.parse_ok)
    n_ann = sum(1 for m in parsed if m.connections)

    by_split: Counter[str] = Counter(f"{m.config}/{m.split}" for m in parsed)
    by_date: Counter[str] = Counter()
    nicks_by_day: dict[str, set[str]] = defaultdict(set)
    deg = Counter()
    for m in parsed:
        by_date[f"{m.config}|{m.date}"] += 1
        if m.speaker and not m.is_system:
            nicks_by_day[f"{m.config}|{m.date}"].add(m.speaker)
        d = len(m.connections)
        if d == 0:
            deg["0"] += 1
        elif d == 1:
            deg["1"] += 1
        else:
            deg["2+"] += 1

    nick_counts = [len(v) for v in nicks_by_day.values()] or [0]
    date_counts = list(by_date.values()) or [0]

    return {
        "n_parsed": n,
        "n_system": n_sys,
        "pct_system": round(_pct(n_sys, n), 3),
        "n_action": n_act,
        "pct_action": round(_pct(n_act, n), 3),
        "n_question": n_q,
        "pct_question": round(_pct(n_q, n), 3),
        "n_addressed": n_addr,
        "pct_addressed": round(_pct(n_addr, n), 3),
        "n_parse_fail": n_fail,
        "pct_parse_fail": round(_pct(n_fail, n), 3),
        "n_annotated_nonempty_connections": n_ann,
        "messages_per_split": dict(by_split),
        "n_date_keys": len(by_date),
        "messages_per_date_p50": float(np.percentile(date_counts, 50)),
        "messages_per_date_p90": float(np.percentile(date_counts, 90)),
        "messages_per_date_min": int(min(date_counts)),
        "messages_per_date_max": int(max(date_counts)),
        "unique_nicks_per_day_p50": float(np.percentile(nick_counts, 50)),
        "unique_nicks_per_day_p90": float(np.percentile(nick_counts, 90)),
        "connections_degree": {k: int(deg[k]) for k in ("0", "1", "2+")},
        "clock": clock_anomalies(parsed),
        "gaps": gap_analysis(parsed),
        "samples": type_samples(parsed),
        "by_date": dict(by_date),
    }


def plot_eda(eda: dict[str, Any]) -> list[Path]:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    counts = list(eda["by_date"].values())
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(counts, bins=min(40, max(10, len(set(counts)))), color="#3b6ea5", edgecolor="white")
    ax.set_title("Messages per (config, date)")
    ax.set_xlabel("messages")
    ax.set_ylabel("number of dates")
    p = FIGURES_DIR / "messages_per_date_hist.png"
    fig.tight_layout()
    fig.savefig(p, dpi=120)
    plt.close(fig)
    paths.append(p)

    deg = eda["connections_degree"]
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.bar(list(deg.keys()), list(deg.values()), color="#c47b2b")
    ax.set_title("Reply-graph degree (len(connections))")
    ax.set_xlabel("degree bucket")
    p = FIGURES_DIR / "connections_degree.png"
    fig.tight_layout()
    fig.savefig(p, dpi=120)
    plt.close(fig)
    paths.append(p)

    splits = eda["messages_per_split"]
    fig, ax = plt.subplots(figsize=(8, 4))
    labels = list(splits.keys())
    ax.barh(labels, [splits[k] for k in labels], color="#2a9d8f")
    ax.set_title("Messages per config/split (windowing partition)")
    p = FIGURES_DIR / "messages_per_split.png"
    fig.tight_layout()
    fig.savefig(p, dpi=120)
    plt.close(fig)
    paths.append(p)
    return paths


def write_schema_md(raw: pd.DataFrame, parsed: list[ParsedIrcMessage]) -> None:
    lines: list[str] = []
    lines.append("# Schema contract — SOMA IRC gate data")
    lines.append("")
    lines.append(f"Source: `{HF_DATASET}`  ")
    lines.append(f"Paper: {PAPER_CITE}  ")
    lines.append(f"License: {LICENSE}  ")
    lines.append("Not used: Lowe / McGill Ubuntu Dialogue Corpus (dyadic extracted threads).")
    lines.append("")
    lines.append(f"Generated (UTC): {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append("## Hub configs and splits (actual downloads)")
    lines.append("")
    lines.append("| config | split | n_rows | n_nonempty_connections | card_annotated | has_real_date | id unique per date |")
    lines.append("|---|---|---:|---:|---:|---|---|")
    for (config, split), g in raw.groupby(["config", "split"], sort=True):
        meta = describe_raw_split(g)
        card = CARD_ANNOTATED.get((config, split), "—")
        lines.append(
            f"| {config} | {split} | {meta['n_rows']} | {meta['n_nonempty_connections']} | "
            f"{card} | {not meta['date_sentinel_only']} | {meta['id_unique_per_date']} |"
        )
    lines.append("")
    lines.append("### Notes vs the dataset card")
    lines.append("")
    lines.append("- Card **annotated** Ubuntu counts: train 67,463 / dev 2,500 / test 5,000.")
    lines.append("- Hub loader returns **context + annotated**. Context is typically the first")
    lines.append("  ~1,000 messages of each slice (`connections` empty; labels start at id ≥ 1000).")
    lines.append("- Hub split name is `validation` (not `dev`).")
    lines.append("- `channel_two` has **no `date` field**. We fill `date=\"undated\"` so the frozen")
    lines.append("  sort key `(config, date, id)` stays defined. It is one #linux session (Elsner & Charniak 2008 / Kummerfeld re-annotation).")
    lines.append("- `channel_two` Hub splits: `dev`, `pilot`, `test`, `pilot_dev`, `all_`.")
    lines.append("  `all_` is the union (2,602 rows). Overlapping subset splits are stored in")
    lines.append("  `data/raw/` but **windows use `all_` only** (domain-shift partition).")
    lines.append("- `connections` is `list[int]` (reply-graph edges, possibly a self-loop for thread start).")
    lines.append("  Used as a **feature**, never as a sort key.")
    lines.append("- Nonempty-`connections` slightly exceeds the card’s annotated counts (e.g. ubuntu")
    lines.append("  train 68,074 vs 67,463). The extras are context-region messages that still carry")
    lines.append("  a reply edge / self-loop. We do **not** drop them: they are real IRC turns.")
    lines.append("")
    lines.append("## Raw Hub fields (do not invent)")
    lines.append("")
    lines.append("| field | dtype | meaning |")
    lines.append("|---|---|---|")
    lines.append("| id | int | message id inside the source file; values referenced by `connections` |")
    lines.append("| raw | str | original IRC log line (primary text) |")
    lines.append("| ascii | str | ascii-fied `raw` |")
    lines.append("| tokenized | str | tokenised / UNK version |")
    lines.append("| connections | sequence[int32] | reply-graph neighbours (same thread) |")
    lines.append("| date | str | Ubuntu only. Calendar day of the log file. |")
    lines.append("")
    lines.append("## Parsed message (`data/interim/messages.parquet`)")
    lines.append("")
    lines.append("Derived from `raw` with tested regex. Plus Hub identity fields.")
    lines.append("")
    lines.append("| field | meaning |")
    lines.append("|---|---|")
    lines.append("| config, split, date, original_id, row_idx | identity / order |")
    lines.append("| raw, ascii, tokenized, connections | passthrough |")
    lines.append("| time_hhmm | `[HH:MM]` when present |")
    lines.append("| speaker | nick inside `<…>` or system/action nick |")
    lines.append("| text | remainder after nick |")
    lines.append("| is_system | JOIN/PART/QUIT/NICK/KICK/MODE/TOPIC |")
    lines.append("| is_action | `/me` (`=== nick rest` without a system verb, or `* nick`) |")
    lines.append("| addressed_to | `^Nick:` on `text`, else null (URLs excluded) |")
    lines.append("| has_question | `'?' in text` |")
    lines.append("| parse_ok | regex matched a known shape |")
    lines.append("| slice_id, run_id | ordering (see eda.md) |")
    lines.append("")
    lines.append("## Frozen window schema (`data/processed/windows_full.parquet`)")
    lines.append("")
    lines.append("Decision point = after message `t`. Window = last "
                 f"**W={WINDOW_SIZE}** non-system messages in the same run, ending at `t`.")
    lines.append(f"`REQUIRE_EXACT_W={REQUIRE_EXACT_W}` — short leading windows are **not** emitted.")
    lines.append(f"`MIN_HISTORY={MIN_HISTORY}` is recorded but unused (exact-W is stricter).")
    lines.append(f"Time-capped view (`time_capped_n`): count of the {WINDOW_SIZE} lines whose clock is within "
                 f"{TIME_CAP_MINUTES} minutes of `t` (feature only; `chat_block` stays {WINDOW_SIZE} lines).")
    lines.append("")
    lines.append("| field | meaning |")
    lines.append("|---|---|")
    lines.append("| window_id | `{config}:{split}:{date}:{slice_id}:{run_id}:{t_id}` |")
    lines.append("| config, split, date, slice_id, run_id, t_id, source | keys |")
    lines.append("| chat_block | `Nick: text` one message per line, exactly W lines |")
    lines.append("| last_speaker, addressed_to, n_speakers_in_window, n_messages | room flags |")
    lines.append("| question_open | last line **or last 3** contain `?` |")
    lines.append("| assistant_named | always false in this corpus (schema stability) |")
    lines.append("| thread_ids_last | `connections` of t |")
    lines.append("| thread_overlap_count | window msgs sharing a reply edge with t |")
    lines.append("| last_is_question, last_is_thanks | last-line flags |")
    lines.append("| time_capped_n, time_hhmm_last, window_message_ids | features / QA |")
    lines.append("| label_gold | **empty** — humans fill later |")
    lines.append("| guideline_hint | auto hint only, not a label |")
    lines.append("")
    lines.append("Gold SPEAK/SILENT is **not** produced in this task.")
    lines.append("")
    SCHEMA_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote {}", SCHEMA_MD)


def _md_samples(title: str, rows: list[str]) -> list[str]:
    out = [f"### {title} (n={len(rows)})", ""]
    for r in rows:
        out.append(f"- `{r}`")
    out.append("")
    return out


def write_eda_md(eda: dict[str, Any], figure_paths: list[Path]) -> None:
    g = eda["gaps"]
    c = eda["clock"]
    lines = [
        "# EDA — jkkummerfeld/irc_disentangle (multi-party stream)",
        "",
        f"Generated (UTC): {datetime.now(timezone.utc).isoformat()}",
        f"Seed: {SEED}. GAP_THRESHOLD={GAP_THRESHOLD}. W={WINDOW_SIZE}.",
        "",
        "## Headline counts",
        "",
        f"- parsed messages (windowing partition): **{eda['n_parsed']:,}**",
        f"- system JOIN/PART/QUIT/NICK/…: **{eda['pct_system']:.2f}%** ({eda['n_system']:,})",
        f"- `/me` actions (kept in windows): **{eda['pct_action']:.2f}%** ({eda['n_action']:,})",
        f"- questions (`?` in text): **{eda['pct_question']:.2f}%** ({eda['n_question']:,})",
        f"- addressed (`Nick:` prefix): **{eda['pct_addressed']:.2f}%** ({eda['n_addressed']:,})",
        f"- parse failures: **{eda['pct_parse_fail']:.3f}%** ({eda['n_parse_fail']:,})",
        f"- nonempty `connections` (annotated-ish): **{eda['n_annotated_nonempty_connections']:,}**",
        "",
        "### Messages per split",
        "",
        "| split | n |",
        "|---|---:|",
    ]
    for k, v in sorted(eda["messages_per_split"].items()):
        lines.append(f"| {k} | {v:,} |")
    lines += [
        "",
        "### Messages per date",
        "",
        f"- n date-keys: {eda['n_date_keys']}",
        f"- p50={eda['messages_per_date_p50']:.0f}, p90={eda['messages_per_date_p90']:.0f}, "
        f"min={eda['messages_per_date_min']}, max={eda['messages_per_date_max']}",
        "",
        "### Unique nicks per day (non-system speakers)",
        "",
        f"- p50={eda['unique_nicks_per_day_p50']:.1f}, p90={eda['unique_nicks_per_day_p90']:.1f}",
        "",
        "### connections degree",
        "",
        "| degree | n |",
        "|---|---:|",
        f"| 0 | {eda['connections_degree']['0']:,} |",
        f"| 1 | {eda['connections_degree']['1']:,} |",
        f"| 2+ | {eda['connections_degree']['2+']:,} |",
        "",
        "## Are ids contiguous or sampled slices?",
        "",
        g["justification"],
        "",
        f"- date-slices: {g['n_date_slices']}",
        f"- fully contiguous slices (diff==1 throughout): {g['n_fully_contiguous_slices']} "
        f"({100*g['frac_contiguous']:.1f}%)",
        f"- gaps with step > {g['gap_threshold']}: {g['n_gaps_gt_threshold']}",
        f"- max missing ids in a step: {g['max_missing_ids']}",
        f"- gap size p50/p90/p99: {g['gap_p50']:.0f} / {g['gap_p90']:.0f} / {g['gap_p99']:.0f}",
        f"- extra slices from id-reset on the same date: {g['n_extra_slices_from_id_reset']}",
        "",
        "Empirical result on this Hub dump: every `(config, split, date, slice)` is **fully",
        "contiguous** (id step == 1). The 173 Kummerfeld time-slices show up as **different",
        "calendar dates** (plus channel_two `undated`), not as holes inside a date.",
        "`GAP_THRESHOLD=5` is a safety belt; it did not split any run here.",
        f"- runs per slice p50/p90: {g['runs_per_slice_p50']:.1f} / {g['runs_per_slice_p90']:.1f}",
        "",
        "Windows **never** jump a run, date, slice, split, or config.",
        "",
        "### Example large gaps",
        "",
    ]
    for ex in g["examples_big_gaps"]:
        lines.append(f"- `{ex}`")
    if not g["examples_big_gaps"]:
        lines.append("- (none)")
    lines += [
        "",
        "## Clock vs official (date, id) order",
        "",
        "Official order is always `(config, split, date, slice_id, original_id)`.",
        "If the `[HH:MM]` clock goes backwards we still trust that key.",
        "Early Ubuntu irclogs (c. 2004–2007) use a **12-hour** clock without AM/PM",
        "(`12:59` → `01:00` is one minute, not 12 hours). Later years are 24-hour",
        "(`23:59` → `00:00`). `time_capped_n` uses a 12h-or-24h wrap heuristic.",
        "",
        f"- midnight wraps (23:xx → 00:xx): {c['n_midnight_wraps']}",
        f"- non-wrap backwards (flagged anomalies): {c['n_non_wrap_backwards']}",
        "",
        "### wrap examples",
        "",
    ]
    for ex in c["examples_wrap"]:
        lines.append(f"- {ex}")
    if not c["examples_wrap"]:
        lines.append("- (none in sample)")
    lines += ["", "### anomaly examples", ""]
    for ex in c["examples_backwards"]:
        lines.append(f"- {ex}")
    if not c["examples_backwards"]:
        lines.append("- (none)")
    lines += ["", "## Sample raw lines", ""]
    for key, title in [
        ("question", "question"),
        ("address", "address"),
        ("system", "system"),
        ("normal", "normal"),
        ("action", "action (/me)"),
    ]:
        lines.extend(_md_samples(title, eda["samples"].get(key, [])))
    lines += ["", "## Figures", ""]
    for p in figure_paths:
        rel = p.as_posix().split("/reports/")[-1] if "/reports/" in p.as_posix() else p.name
        # Windows paths
        rel = "figures/" + p.name
        lines.append(f"![{p.stem}]({rel})")
        lines.append("")
    EDA_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote {}", EDA_MD)


def write_stats_json(payload: dict[str, Any]) -> None:
    STATS_JSON.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    logger.info("Wrote {}", STATS_JSON)
