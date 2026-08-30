"""Harvest 5k SPEAK + 5k SILENT with pilot_v2.2. No Nivas gold edits. No v1 mix.

Requires Gate 1 v2.2 PASS (overall>=78%, addressed>=75%, SPEAK 35-55%).
Resume-safe jsonl. Test ids (audit_200) are never harvested into train.
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
    AUDIT_200_IDS,
    GATE1_ADDRESSED_AGREE_MIN,
    GATE1_SPEAK_MAX,
    GATE1_SPEAK_MIN,
    GATE1_V2_2_AGREE_MIN,
    HARVEST_SILENT_N,
    HARVEST_SPEAK_N,
    LABEL_QUEUE_CSV,
    PILOT_2K_IDS,
    PILOT_V2_2_AUDIT200_JSONL,
    PILOT_V2_2_FAILURES_JSONL,
    PILOT_V2_2_HARVEST_MD,
    PILOT_V2_2_LABELS_JSONL,
    PROMPT_VERSION_V2_2,
    SEED,
    SFT_DEV_JSONL,
    SFT_TEST_JSONL,
    SFT_TRAIN_JSONL,
    TEACHER_RETRIES,
    TRAIN_10K_IDS,
    ensure_dirs,
)
from soma_data.teacher import detect_modal, modal_setup_instructions  # noqa: E402
from soma_data.teacher_prompt_v2_2 import (  # noqa: E402
    build_user_payload_v2_2,
    sft_record,
)

console = Console()
DEV_PER_CLASS = 100


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


def _id_list(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_ids() -> set[str]:
    ids = set(_id_list(AUDIT_200_IDS))
    audit = pd.read_csv(AUDIT_200_CSV, dtype=str, keep_default_na=False)
    ids |= set(audit["window_id"].astype(str))
    return ids


def harvest_counts(recs: list[dict]) -> tuple[int, int]:
    speak = silent = 0
    for r in recs:
        lab = str(r.get("label_silver") or "").strip().upper()
        if not r.get("raw_ok") or lab not in {"SPEAK", "SILENT"}:
            continue
        if lab == "SPEAK":
            speak += 1
        else:
            silent += 1
    return speak, silent


def _assert_gate1() -> None:
    """Refuse harvest unless v2.2 audit200 already meets the harvest bar."""
    preds = _load_jsonl(PILOT_V2_2_AUDIT200_JSONL)
    if len(preds) < 200:
        raise SystemExit(f"gate1 jsonl n={len(preds)} < 200")
    audit = pd.read_csv(AUDIT_200_CSV, dtype=str, keep_default_na=False)
    audit = audit[audit["review_ok"].str.strip().str.upper().eq("Y")]
    pmap = {r["window_id"]: r for r in preds}
    rows = []
    for rec in audit.to_dict(orient="records"):
        p = pmap.get(rec["window_id"]) or {}
        gold = rec["label_gold"].strip().upper()
        pred = str(p.get("label_silver") or "").strip().upper()
        ok = bool(p.get("raw_ok")) and pred in {"SPEAK", "SILENT"}
        addr = bool(str(rec.get("addressed_to") or "").strip())
        rows.append({"gold": gold, "pred": pred, "ok": ok, "addr": addr, "agree": ok and pred == gold})
    scored = [r for r in rows if r["ok"]]
    overall = sum(1 for r in scored if r["agree"]) / len(scored)
    addr = [r for r in scored if r["addr"]]
    addr_pct = sum(1 for r in addr if r["agree"]) / len(addr)
    speak_pct = sum(1 for r in scored if r["pred"] == "SPEAK") / len(scored)
    passed = (
        len(scored) == 200
        and overall >= GATE1_V2_2_AGREE_MIN
        and addr_pct >= GATE1_ADDRESSED_AGREE_MIN
        and GATE1_SPEAK_MIN <= speak_pct <= GATE1_SPEAK_MAX
    )
    console.print(
        f"gate1 check overall={100*overall:.1f}% addressed={100*addr_pct:.1f}% "
        f"speak={100*speak_pct:.1f}% passed={passed}"
    )
    if not passed:
        raise SystemExit("harvest refused: Gate 1 v2.2 did not pass")


def candidate_ids(held: set[str]) -> list[str]:
    """Remaining pilot_2k first, then the rest of label_queue. Never test ids."""
    q = pd.read_csv(LABEL_QUEUE_CSV, dtype=str, keep_default_na=False)
    qids = list(dict.fromkeys(q["window_id"].astype(str)))
    qset = set(qids)
    frozen = [i for i in _id_list(PILOT_2K_IDS) if i in qset and i not in held]
    rest = [i for i in qids if i not in held and i not in set(frozen)]
    return frozen + rest


def queue_map() -> pd.DataFrame:
    df = pd.read_csv(LABEL_QUEUE_CSV, dtype=str, keep_default_na=False)
    return df.drop_duplicates("window_id").set_index("window_id", drop=False)


def build_item(row: dict) -> dict:
    return {
        "window_id": row["window_id"],
        "user_payload": build_user_payload_v2_2(row),
        "chat_block": row.get("chat_block") or "",
        "last_speaker": row.get("last_speaker") or "",
        "last_is_question": row.get("last_is_question") or "",
        "last_is_thanks": row.get("last_is_thanks") or "",
        "addressed_to": row.get("addressed_to") or "",
        "last_line": row.get("last_line") or "",
        "split": row.get("split") or "",
        "date": row.get("date") or "",
        "t_id": row.get("t_id") or "",
        "guideline_hint": "",
    }


def _remote_one(teacher, item: dict) -> dict:
    last = None
    for attempt in range(3):
        try:
            rec = teacher.label_one.remote(item)
            rec["prompt_version"] = PROMPT_VERSION_V2_2
            rec["label_silver_v2"] = rec.get("label_silver") or ""
            return rec
        except Exception as exc:  # noqa: BLE001
            last = exc
            logger.warning("remote {} {}: {}", item["window_id"], type(exc).__name__, exc)
            time.sleep(2 * (attempt + 1))
    return {
        "window_id": item["window_id"],
        "raw_ok": False,
        "error": f"remote {type(last).__name__}: {last}",
        "prompt_version": PROMPT_VERSION_V2_2,
        "label_silver_v2": "",
        "retries": TEACHER_RETRIES,
    }


def export_sft(labels: list[dict], qmap: pd.DataFrame, held: set[str]) -> dict:
    by_lab: dict[str, list[dict]] = {"SPEAK": [], "SILENT": []}
    seen: set[str] = set()
    for rec in labels:
        wid = rec.get("window_id") or ""
        if not wid or wid in held or wid in seen:
            continue
        lab = str(rec.get("label_silver") or "").strip().upper()
        if not rec.get("raw_ok") or lab not in by_lab:
            continue
        if wid not in qmap.index:
            continue
        seen.add(wid)
        by_lab[lab].append(rec)
    need_s = HARVEST_SPEAK_N + DEV_PER_CLASS
    need_n = HARVEST_SILENT_N + DEV_PER_CLASS
    if len(by_lab["SPEAK"]) < need_s or len(by_lab["SILENT"]) < need_n:
        raise AssertionError(
            f"not enough harvest labels SPEAK={len(by_lab['SPEAK'])}/{need_s} "
            f"SILENT={len(by_lab['SILENT'])}/{need_n}"
        )
    speak = by_lab["SPEAK"][:need_s]
    silent = by_lab["SILENT"][:need_n]
    rng = pd.Series(range(len(speak))).sample(frac=1, random_state=SEED).tolist()
    rng_s = pd.Series(range(len(silent))).sample(frac=1, random_state=SEED + 1).tolist()
    speak = [speak[i] for i in rng]
    silent = [silent[i] for i in rng_s]
    dev = speak[:DEV_PER_CLASS] + silent[:DEV_PER_CLASS]
    train = speak[DEV_PER_CLASS:] + silent[DEV_PER_CLASS:]

    def _sft_rows(recs: list[dict], split: str) -> list[dict]:
        out = []
        for rec in recs:
            row = qmap.loc[rec["window_id"]].to_dict()
            out.append(
                sft_record(
                    row,
                    rec["label_silver"],
                    source="teacher_v2.2",
                    split=split,
                )
            )
        return out

    train_rows = _sft_rows(train, "train")
    dev_rows = _sft_rows(dev, "dev")

    audit = pd.read_csv(AUDIT_200_CSV, dtype=str, keep_default_na=False)
    audit = audit[audit["review_ok"].str.strip().str.upper().eq("Y")]
    test_rows = []
    for rec in audit.to_dict(orient="records"):
        gold = rec["label_gold"].strip().upper()
        test_rows.append(sft_record(rec, gold, source="nivas_gold", split="test"))

    def _write(path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8",
        )

    _write(SFT_TRAIN_JSONL, train_rows)
    _write(SFT_DEV_JSONL, dev_rows)
    _write(SFT_TEST_JSONL, test_rows)
    harvest_ids = [r["window_id"] for r in train_rows + dev_rows]
    TRAIN_10K_IDS.write_text("\n".join(harvest_ids) + "\n", encoding="utf-8")
    train_ids = [r["window_id"] for r in train_rows]
    # sanity: no test leakage, no v1
    train_idset = set(harvest_ids)
    if train_idset & held:
        raise AssertionError("test ids leaked into train")
    for r in train_rows + dev_rows:
        if r["source"] != "teacher_v2.2" or r["prompt_version"] != PROMPT_VERSION_V2_2:
            raise AssertionError("train/dev must be teacher_v2.2")
        if r["output"] not in {"SPEAK", "SILENT"}:
            raise AssertionError("empty/bad output")
    for r in test_rows:
        if r["source"] != "nivas_gold":
            raise AssertionError("test must be nivas gold")
    stats = {
        "train_n": len(train_rows),
        "train_speak": sum(1 for r in train_rows if r["output"] == "SPEAK"),
        "train_silent": sum(1 for r in train_rows if r["output"] == "SILENT"),
        "dev_n": len(dev_rows),
        "dev_speak": sum(1 for r in dev_rows if r["output"] == "SPEAK"),
        "dev_silent": sum(1 for r in dev_rows if r["output"] == "SILENT"),
        "test_n": len(test_rows),
        "test_speak": sum(1 for r in test_rows if r["output"] == "SPEAK"),
        "test_silent": sum(1 for r in test_rows if r["output"] == "SILENT"),
        "labeled_n": len(seen),
        "labeled_speak": len(by_lab["SPEAK"]),
        "labeled_silent": len(by_lab["SILENT"]),
    }
    lines = [
        "# Harvest — pilot_v2.2 5k/5k",
        "",
        "Gate 1 PASS. Teacher labels only. Nivas gold is test-only. No v1 mix.",
        "",
        f"- prompt_version: `{PROMPT_VERSION_V2_2}`",
        f"- labeled parse-ok: {stats['labeled_n']} (SPEAK {stats['labeled_speak']}, SILENT {stats['labeled_silent']})",
        f"- sft_train: {stats['train_n']} (SPEAK {stats['train_speak']}, SILENT {stats['train_silent']})",
        f"- sft_dev: {stats['dev_n']} (SPEAK {stats['dev_speak']}, SILENT {stats['dev_silent']}) held out from harvest, seed={SEED}",
        f"- sft_test: {stats['test_n']} Nivas gold (SPEAK {stats['test_speak']}, SILENT {stats['test_silent']})",
        f"- train_10k_ids: {TRAIN_10K_IDS} ({len(harvest_ids)} harvested ids; 200 test ids excluded)",
        "",
        "label_gold on label_queue/audit_200 was not overwritten.",
        "",
    ]
    PILOT_V2_2_HARVEST_MD.write_text("\n".join(lines), encoding="utf-8")
    PILOT_V2_HARVEST_MD.write_text("\n".join(lines), encoding="utf-8")
    return stats


def run_remote(items: list[dict], need_speak: int, need_silent: int) -> None:
    import modal

    from soma_data.modal_teacher import Teacher, app

    done = {r["window_id"] for r in _load_jsonl(PILOT_V2_2_LABELS_JSONL) if r.get("window_id")}
    done |= {r["window_id"] for r in _load_jsonl(PILOT_V2_2_FAILURES_JSONL) if r.get("window_id")}
    speak, silent = harvest_counts(_load_jsonl(PILOT_V2_2_LABELS_JSONL))
    pending = [it for it in items if it["window_id"] not in done]
    console.print(f"harvest already speak={speak} silent={silent} pending={len(pending)}")
    if speak >= need_speak and silent >= need_silent:
        return
    with modal.enable_output():
        with app.run():
            teacher = Teacher()
            health = teacher.health_info.remote()
            console.print(Panel(json.dumps(health, indent=2), title="TEACHER_READY harvest v2.2"))
            for i, item in enumerate(pending, 1):
                if speak >= need_speak and silent >= need_silent:
                    console.print("quotas filled, stopping")
                    break
                rec = _remote_one(teacher, item)
                if rec.get("raw_ok"):
                    _append(PILOT_V2_2_LABELS_JSONL, rec)
                    lab = str(rec.get("label_silver") or "").upper()
                    if lab == "SPEAK":
                        speak += 1
                    elif lab == "SILENT":
                        silent += 1
                    tag = lab
                else:
                    _append(PILOT_V2_2_FAILURES_JSONL, rec)
                    tag = rec.get("error")
                if i % 25 == 0 or i == 1:
                    console.print(
                        f"{i}/{len(pending)} {item['window_id']} {tag} "
                        f"speak={speak}/{need_speak} silent={silent}/{need_silent}"
                    )


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    ensure_dirs()
    _assert_gate1()
    held = test_ids()
    if len(held) != 200:
        # audit file may have exactly 200; ids file should too
        console.print(f"held-out test ids n={len(held)}")
    qmap = queue_map()
    ids = candidate_ids(held)
    console.print(f"candidate pool {len(ids)} (test {len(held)} excluded)")
    status = detect_modal()
    if not status.get("usable"):
        console.print(modal_setup_instructions())
        raise SystemExit(2)
    items = []
    for wid in ids:
        row = qmap.loc[wid].to_dict()
        items.append(build_item(row))
    run_remote(items, HARVEST_SPEAK_N + DEV_PER_CLASS, HARVEST_SILENT_N + DEV_PER_CLASS)
    labels = _load_jsonl(PILOT_V2_2_LABELS_JSONL)
    stats = export_sft(labels, qmap, held)
    console.print(
        f"HARVEST done train={stats['train_n']} dev={stats['dev_n']} test={stats['test_n']} "
        f"→ {PILOT_V2_2_HARVEST_MD}"
    )


if __name__ == "__main__":
    main()
