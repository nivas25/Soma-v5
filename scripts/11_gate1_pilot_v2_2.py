"""Gate 1 retry: audit_200 with Qwen 32B + pilot_v2.2. Score vs Nivas gold.

Does not write label_gold. Harvest only if overall>=78% AND addressed>=75%
AND SPEAK in 35-55%. Does not train.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
from loguru import logger
from rich.console import Console
from rich.panel import Panel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soma_data.config import (  # noqa: E402
    AUDIT_200_CSV,
    GATE1_ADDRESSED_AGREE_MIN,
    GATE1_SPEAK_MAX,
    GATE1_SPEAK_MIN,
    GATE1_V2_2_AGREE_MIN,
    PILOT_V2_1_AUDIT200_JSONL,
    PILOT_V2_2_AUDIT200_FAIL_JSONL,
    PILOT_V2_2_AUDIT200_JSONL,
    PILOT_V2_2_GATE1_MD,
    PROMPT_VERSION_V2_2,
    TEACHER_RETRIES,
    ensure_dirs,
)
from soma_data.teacher import detect_modal, modal_setup_instructions  # noqa: E402
from soma_data.teacher_prompt_v2_2 import (  # noqa: E402
    TEACHER_SYSTEM_PROMPT_V2_2,
    build_user_payload_v2_2,
    few_shot_window_ids,
    helper_in_window,
)

console = Console()


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _append(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _done_ids() -> set[str]:
    ids: set[str] = set()
    for p in (PILOT_V2_2_AUDIT200_JSONL, PILOT_V2_2_AUDIT200_FAIL_JSONL):
        for rec in _load_jsonl(p):
            if rec.get("window_id"):
                ids.add(rec["window_id"])
    return ids


def load_audit() -> pd.DataFrame:
    df = pd.read_csv(AUDIT_200_CSV, dtype=str, keep_default_na=False)
    df = df[df["review_ok"].str.strip().str.upper().eq("Y")].copy()
    if len(df) != 200:
        raise AssertionError(f"audit review_ok=Y n={len(df)} != 200")
    gold = df["label_gold"].str.strip().str.upper()
    if not gold.isin({"SPEAK", "SILENT"}).all():
        raise AssertionError("audit gold not SPEAK/SILENT")
    shots = few_shot_window_ids()
    overlap = shots & set(df["window_id"])
    if overlap:
        raise AssertionError(f"few-shots used test ids: {overlap}")
    return df.reset_index(drop=True)


def build_items(df: pd.DataFrame) -> list[dict]:
    out = []
    for rec in df.to_dict(orient="records"):
        out.append(
            {
                "window_id": rec["window_id"],
                "user_payload": build_user_payload_v2_2(rec),
                "chat_block": rec.get("chat_block") or "",
                "last_speaker": rec.get("last_speaker") or "",
                "last_is_question": rec.get("last_is_question") or "",
                "last_is_thanks": rec.get("last_is_thanks") or "",
                "addressed_to": rec.get("addressed_to") or "",
                "last_line": rec.get("last_line") or "",
                "split": rec.get("split") or "",
                "date": rec.get("date") or "",
                "label_gold": rec["label_gold"].strip().upper(),
                "helper_in_window": "yes" if helper_in_window(rec) else "no",
            }
        )
    return out


def _remote_one(teacher, item: dict) -> dict:
    last = None
    for attempt in range(3):
        try:
            rec = teacher.label_one.remote(item)
            rec["label_gold"] = item["label_gold"]
            rec["last_line"] = item.get("last_line") or ""
            rec["label_silver_v2"] = rec.get("label_silver") or ""
            rec["prompt_version"] = PROMPT_VERSION_V2_2
            rec["helper_in_window"] = item.get("helper_in_window") or ""
            return rec
        except Exception as exc:  # noqa: BLE001
            last = exc
            logger.warning("remote {} {}: {}", item["window_id"], type(exc).__name__, exc)
            time.sleep(2 * (attempt + 1))
    return {
        "window_id": item["window_id"],
        "raw_ok": False,
        "error": f"remote {type(last).__name__}: {last}",
        "label_gold": item["label_gold"],
        "last_line": item.get("last_line") or "",
        "prompt_version": PROMPT_VERSION_V2_2,
        "label_silver_v2": "",
        "helper_in_window": item.get("helper_in_window") or "",
        "retries": TEACHER_RETRIES,
    }


def _pred_label(p: dict) -> str:
    return str(p.get("label_silver_v2") or p.get("label_silver") or "").strip().upper()


def score(audit: pd.DataFrame, preds: list[dict]) -> dict:
    pmap = {r["window_id"]: r for r in preds}
    v21_map = {r["window_id"]: r for r in _load_jsonl(PILOT_V2_1_AUDIT200_JSONL)}
    rows = []
    for rec in audit.to_dict(orient="records"):
        p = pmap.get(rec["window_id"]) or {}
        gold = rec["label_gold"].strip().upper()
        pred = _pred_label(p)
        ok = bool(p.get("raw_ok")) and pred in {"SPEAK", "SILENT"}
        addr = str(rec.get("addressed_to") or "").strip()
        q = str(rec.get("last_is_question") or "").strip().lower() in {"true", "1", "yes"}
        v21 = _pred_label(v21_map.get(rec["window_id"]) or {})
        rows.append(
            {
                "window_id": rec["window_id"],
                "gold": gold,
                "pred": pred if ok else "",
                "ok": ok,
                "addressed": bool(addr),
                "question": q,
                "last_line": rec.get("last_line") or "",
                "agree": ok and pred == gold,
                "v21": v21,
                "helper": "yes" if helper_in_window(rec) else "no",
            }
        )
    n = len(rows)
    scored = [r for r in rows if r["ok"]]
    ns = len(scored)
    agree = sum(1 for r in scored if r["agree"])
    addr = [r for r in scored if r["addressed"]]
    ques = [r for r in scored if r["question"]]
    nivas_speak = sum(1 for r in rows if r["gold"] == "SPEAK")
    v2_speak = sum(1 for r in scored if r["pred"] == "SPEAK")
    overall = agree / ns if ns else 0.0
    addr_pct = (sum(1 for r in addr if r["agree"]) / len(addr)) if addr else 0.0
    q_pct = (sum(1 for r in ques if r["agree"]) / len(ques)) if ques else 0.0
    speak_pct = v2_speak / ns if ns else 0.0
    speak_ok = GATE1_SPEAK_MIN <= speak_pct <= GATE1_SPEAK_MAX
    passed = (
        ns == n
        and overall >= GATE1_V2_2_AGREE_MIN
        and addr_pct >= GATE1_ADDRESSED_AGREE_MIN
        and speak_ok
    )
    gold_speak_v2_silent = [r for r in scored if r["gold"] == "SPEAK" and r["pred"] == "SILENT"]
    gold_silent_v2_speak = [r for r in scored if r["gold"] == "SILENT" and r["pred"] == "SPEAK"]
    v21_ok = [r for r in scored if r["v21"] in {"SPEAK", "SILENT"}]
    return {
        "n": n,
        "n_scored": ns,
        "n_fail_parse": n - ns,
        "agree": agree,
        "overall": overall,
        "addressed_n": len(addr),
        "addressed_agree": addr_pct,
        "question_n": len(ques),
        "question_agree": q_pct,
        "nivas_speak": nivas_speak,
        "nivas_speak_pct": nivas_speak / n,
        "v2_speak": v2_speak,
        "v2_speak_pct": speak_pct,
        "speak_ok": speak_ok,
        "passed": passed,
        "disagreements": [r for r in scored if not r["agree"]],
        "n_gold_speak_v2_silent": len(gold_speak_v2_silent),
        "n_gold_silent_v2_speak": len(gold_silent_v2_speak),
        "v21_agree": sum(1 for r in v21_ok if r["v21"] == r["gold"]),
        "v21_n": len(v21_ok),
        "fixed": [r for r in scored if r["v21"] != r["gold"] and r["agree"]],
        "regressed": [r for r in scored if r["v21"] == r["gold"] and not r["agree"]],
        "helper_yes": sum(1 for r in scored if r["helper"] == "yes"),
    }


def write_report(stats: dict) -> None:
    status = "PASS" if stats["passed"] else "FAIL"
    v21_n = stats.get("v21_n") or 0
    v21_pct = (100 * stats["v21_agree"] / v21_n) if v21_n else 0.0
    lines = [
        "# Gate 1 — pilot_v2.2 vs Nivas gold (audit_200)",
        "",
        f"**{status}**",
        "",
        "v2.1 leftover: empty `addressed_to` but a helper is already on the last speaker's thread.",
        "v2.2 expands `helper_in_window` (helper language / 2+ answers to last speaker / last speaker",
        "diagnostic / ubotu tell). If helper_in_window=yes and last line is not a brand-new group",
        "how-to → SILENT. Harvest bar is overall ≥78% (not 80%).",
        "",
        f"- prompt_version: `{PROMPT_VERSION_V2_2}`",
        "- model: Qwen/Qwen2.5-32B-Instruct (transformers generate, temp 0, max_new_tokens=80)",
        f"- n: {stats['n']} (parse-ok {stats['n_scored']}, fail {stats['n_fail_parse']})",
        f"- overall agree: **{stats['agree']}/{stats['n_scored']} ({100 * stats['overall']:.1f}%)**  (harvest need ≥ {100 * GATE1_V2_2_AGREE_MIN:.0f}%)",
        f"- addressed_to nonempty: **{100 * stats['addressed_agree']:.1f}%** of {stats['addressed_n']}  (need ≥ {100 * GATE1_ADDRESSED_AGREE_MIN:.0f}%)",
        f"- last_is_question: {100 * stats['question_agree']:.1f}% of {stats['question_n']}",
        f"- SPEAK rate Nivas: {stats['nivas_speak']}/{stats['n']} ({100 * stats['nivas_speak_pct']:.1f}%)",
        f"- SPEAK rate v2.2: {stats['v2_speak']}/{stats['n_scored']} ({100 * stats['v2_speak_pct']:.1f}%)  (need 35–55%)",
        f"- gold SILENT / v2.2 SPEAK: {stats['n_gold_silent_v2_speak']}",
        f"- gold SPEAK / v2.2 SILENT: {stats['n_gold_speak_v2_silent']}",
        f"- helper_in_window=yes: {stats['helper_yes']}/{stats['n_scored']}",
        "",
        "## vs v2.1",
        "",
        f"| metric | v2.1 | v2.2 | harvest need |",
        f"| --- | --- | --- | --- |",
        f"| overall | {stats['v21_agree']}/{v21_n} ({v21_pct:.1f}%) | {stats['agree']}/{stats['n_scored']} ({100 * stats['overall']:.1f}%) | ≥78% |",
        f"| addressed | 85.0% of 40 | {100 * stats['addressed_agree']:.1f}% of {stats['addressed_n']} | ≥75% |",
        f"| SPEAK rate | 52.5% | {100 * stats['v2_speak_pct']:.1f}% | 35–55% |",
        f"| fixed from v2.1 | — | {len(stats['fixed'])} | — |",
        f"| regressed vs v2.1 | — | {len(stats['regressed'])} | — |",
        "",
        "## System prompt (pilot_v2.2)",
        "",
        "```",
        TEACHER_SYSTEM_PROMPT_V2_2,
        "```",
        "",
        "## 15 disagreements",
        "",
    ]
    if not stats["disagreements"]:
        lines.append("- none")
    else:
        for r in stats["disagreements"][:15]:
            lines.append(
                f"- `{r['window_id']}` gold=**{r['gold']}** v2.2=**{r['pred']}** helper={r['helper']} — `{r['last_line']}`"
            )
    lines += [
        "",
        "Nivas gold was not overwritten. Few-shots did not use audit_200 ids.",
        "Harvest is blocked unless PASS (overall≥78% AND addressed≥75% AND SPEAK 35–55%).",
        "",
    ]
    PILOT_V2_2_GATE1_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_remote(items: list[dict]) -> None:
    import modal

    from soma_data.modal_teacher import Teacher, app

    done = _done_ids()
    pending = [it for it in items if it["window_id"] not in done]
    console.print(f"pending={len(pending)} already={len(done)}")
    if not pending:
        return
    with modal.enable_output():
        with app.run():
            teacher = Teacher()
            health = teacher.health_info.remote()
            console.print(Panel(json.dumps(health, indent=2), title="TEACHER_READY v2.2"))
            for i, item in enumerate(pending, 1):
                rec = _remote_one(teacher, item)
                if rec.get("raw_ok"):
                    _append(PILOT_V2_2_AUDIT200_JSONL, rec)
                    tag = rec.get("label_silver_v2")
                else:
                    _append(PILOT_V2_2_AUDIT200_FAIL_JSONL, rec)
                    tag = rec.get("error")
                console.print(f"{len(done) + i}/{len(items)} {item['window_id']} {tag}")


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    ensure_dirs()
    df = load_audit()
    console.print(f"audit gold n={len(df)} prompt={PROMPT_VERSION_V2_2}")
    status = detect_modal()
    if not status.get("usable"):
        console.print(modal_setup_instructions())
        raise SystemExit(2)
    items = build_items(df)
    run_remote(items)
    preds = _load_jsonl(PILOT_V2_2_AUDIT200_JSONL) + _load_jsonl(PILOT_V2_2_AUDIT200_FAIL_JSONL)
    stats = score(df, preds)
    write_report(stats)
    console.print(
        f"GATE1 {'PASS' if stats['passed'] else 'FAIL'} "
        f"overall={100 * stats['overall']:.1f}% addressed={100 * stats['addressed_agree']:.1f}% "
        f"speak={100 * stats['v2_speak_pct']:.1f}% → {PILOT_V2_2_GATE1_MD}"
    )
    if not stats["passed"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
