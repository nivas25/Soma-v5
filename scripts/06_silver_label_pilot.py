"""Silver-label the frozen 2,000-window pilot.

One window per Modal .remote() call. transformers generate, temperature 0.
Resume-safe: already-written window_ids in labels/failures jsonl are skipped.

  uv run python scripts/06_silver_label_pilot.py          # dry-run 3, then remaining
  uv run python scripts/06_silver_label_pilot.py --poll   # resume (same loop)
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger
from rich.console import Console
from rich.panel import Panel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soma_data.config import (  # noqa: E402
    LABEL_QUEUE_CSV,
    PILOT_2K_FAILURES_JSONL,
    PILOT_2K_IDS,
    PILOT_2K_LABELS_JSONL,
    PILOT_2K_LABELS_PARQUET,
    PILOT_2K_MANIFEST,
    PILOT_2K_RAW_DIR,
    PILOT_2K_RESULTS_MD,
    PROMPT_VERSION,
    SILVER_DIR,
    TEACHER_MAX_NEW_TOKENS,
    TEACHER_RETRIES,
    TEACHER_TEMPERATURE,
    TEACHER_TOP_P,
    ensure_dirs,
)
from soma_data.pilot_select import load_frozen_ids  # noqa: E402
from soma_data.teacher import detect_modal, modal_setup_instructions  # noqa: E402
from soma_data.teacher_prompt import TEACHER_SYSTEM_PROMPT, build_user_payload  # noqa: E402

console = Console()
HEALTH_PATH = SILVER_DIR / "pilot_2k_health.json"
DRY_PATH = SILVER_DIR / "pilot_2k_dry_run.json"
PROGRESS_PATH = SILVER_DIR / "pilot_2k_progress.json"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _done_ids() -> set[str]:
    ids: set[str] = set()
    for path in (PILOT_2K_LABELS_JSONL, PILOT_2K_FAILURES_JSONL):
        for rec in _load_jsonl(path):
            if rec.get("window_id"):
                ids.add(rec["window_id"])
    return ids


def _append_jsonl(path: Path, rec: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


def _commit_rec(rec: dict[str, Any]) -> None:
    wid = rec.get("window_id") or "unknown"
    raw = rec.get("raw_text") or ""
    name = wid.replace(":", "__").replace("/", "_")
    PILOT_2K_RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = PILOT_2K_RAW_DIR / f"{name}.txt"
    raw_path.write_text(raw, encoding="utf-8")
    if rec.get("raw_ok"):
        _append_jsonl(PILOT_2K_LABELS_JSONL, rec)
    else:
        _append_jsonl(PILOT_2K_FAILURES_JSONL, rec)


def _queue_map() -> pd.DataFrame:
    df = pd.read_csv(LABEL_QUEUE_CSV, dtype=str, keep_default_na=False)
    return df.drop_duplicates("window_id").set_index("window_id", drop=False)


def _stratum_of(man: dict[str, Any]) -> dict[str, str]:
    return {r["window_id"]: r["stratum"] for r in man.get("strata", [])}


def build_payloads(ids: list[str]) -> list[dict[str, Any]]:
    qmap = _queue_map()
    missing = [i for i in ids if i not in qmap.index]
    if missing:
        raise AssertionError(f"{len(missing)} frozen ids not in label_queue")
    out = []
    for wid in ids:
        row = qmap.loc[wid].to_dict()
        out.append(
            {
                "window_id": wid,
                "user_payload": build_user_payload(row),
                "chat_block": row.get("chat_block") or "",
                "last_speaker": row.get("last_speaker") or "",
                "last_is_question": row.get("last_is_question") or "",
                "addressed_to": row.get("addressed_to") or "",
                "guideline_hint": row.get("guideline_hint") or "",
                "split": row.get("split") or "",
                "date": row.get("date") or "",
                "t_id": row.get("t_id") or "",
            }
        )
    return out


def patch_manifest_inference() -> None:
    """Update sampling/model metadata only. Never touch frozen window_ids."""
    man = json.loads(PILOT_2K_MANIFEST.read_text(encoding="utf-8"))
    ids_before = list(man["window_ids"])
    man.setdefault("inference", {})
    man["inference"]["temperature"] = TEACHER_TEMPERATURE
    man["inference"]["top_p"] = TEACHER_TOP_P
    man["inference"]["max_new_tokens"] = TEACHER_MAX_NEW_TOKENS
    man["inference"]["json_only"] = True
    man["inference"]["one_window_per_prompt"] = True
    man["inference"]["engine"] = "transformers.AutoModelForCausalLM.generate"
    stale = str(man.get("model_id") or "")
    if "72B" in stale or "AWQ" in stale:
        man["model_id"] = None
        man["model_revision"] = None
        man["quantization"] = None
        man["gpu"] = None
        man.pop("model_filled_at_utc", None)
    if man["window_ids"] != ids_before:
        raise AssertionError("refusing to write manifest: window_ids would change")
    PILOT_2K_MANIFEST.write_text(json.dumps(man, indent=2), encoding="utf-8")


def write_raw_from_labels() -> None:
    PILOT_2K_RAW_DIR.mkdir(parents=True, exist_ok=True)
    for rec in _load_jsonl(PILOT_2K_LABELS_JSONL) + _load_jsonl(PILOT_2K_FAILURES_JSONL):
        wid = rec.get("window_id") or "unknown"
        raw = rec.get("raw_text") or ""
        name = wid.replace(":", "__").replace("/", "_")
        (PILOT_2K_RAW_DIR / f"{name}.txt").write_text(raw, encoding="utf-8")


def integrity_ok(ids: list[str]) -> tuple[bool, str]:
    labels = _load_jsonl(PILOT_2K_LABELS_JSONL)
    fails = _load_jsonl(PILOT_2K_FAILURES_JSONL)
    lab_ids = [r["window_id"] for r in labels]
    fail_ids = [r["window_id"] for r in fails]
    all_done = lab_ids + fail_ids
    extra = set(all_done) - set(ids)
    missing = set(ids) - set(all_done)
    if extra:
        return False, f"extra ids: {len(extra)}"
    if len(lab_ids) != len(set(lab_ids)) or len(fail_ids) != len(set(fail_ids)):
        return False, "duplicate ids in labels or failures"
    overlap = set(lab_ids) & set(fail_ids)
    if overlap:
        return False, f"id in both labels and failures: {len(overlap)}"
    msg = f"success={len(labels)} fail={len(fails)} missing={len(missing)} extra={len(extra)}"
    complete = (len(labels) + len(fails) == len(ids)) and not missing and not extra
    return complete, msg


def write_parquet_from_jsonl() -> None:
    rows = _load_jsonl(PILOT_2K_LABELS_JSONL)
    if not rows:
        return
    cols = [
        "window_id",
        "label_silver",
        "reason",
        "model_id",
        "backend",
        "prompt_version",
        "latency_ms",
        "retries",
        "raw_ok",
        "chat_block",
        "last_speaker",
        "last_is_question",
        "addressed_to",
        "guideline_hint",
        "split",
        "date",
        "t_id",
    ]
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    df[cols].to_parquet(PILOT_2K_LABELS_PARQUET, index=False)


def _last_line(chat: str) -> str:
    lines = [ln for ln in str(chat).splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def write_results_md(ids: list[str], man: dict[str, Any], health: dict[str, Any] | None, dry_raw: list[str]) -> None:
    labels = _load_jsonl(PILOT_2K_LABELS_JSONL)
    fails = _load_jsonl(PILOT_2K_FAILURES_JSONL)
    n_ok = len(labels)
    n_fail = len(fails)
    speak = [r for r in labels if r.get("label_silver") == "SPEAK"]
    silent = [r for r in labels if r.get("label_silver") == "SILENT"]
    stratum = _stratum_of(man)
    by_stratum: dict[str, list[dict]] = {"question": [], "addressed_not_question": [], "other": []}
    for r in labels:
        by_stratum.setdefault(stratum.get(r["window_id"], "other"), []).append(r)

    def _rate(rows: list[dict]) -> str:
        if not rows:
            return "n=0"
        s = sum(1 for r in rows if r.get("label_silver") == "SPEAK")
        return f"SPEAK {s}/{len(rows)} ({100 * s / len(rows):.1f}%)"

    hint_buckets: dict[str, list[dict]] = {}
    for r in labels:
        hint_buckets.setdefault(r.get("guideline_hint") or "(empty)", []).append(r)

    def _disagree(r: dict) -> bool:
        hint = (r.get("guideline_hint") or "").lower()
        lab = r.get("label_silver")
        if lab == "SPEAK" and ("thanks" in hint or "addressed to human" in hint):
            return True
        if lab == "SILENT" and "question + no clear addressee" in hint:
            return True
        return False

    disagrees = [r for r in labels if _disagree(r)]
    inf = man.get("inference") or {}
    lines = [
        "# SOMA gate — silver-label PILOT (2,000 windows)",
        "",
        f"Generated (UTC): {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Model / backend",
        "",
        f"- backend: **{(health or {}).get('backend') or man.get('backend') or 'modal'}**",
        f"- engine: `{(health or {}).get('engine') or inf.get('engine') or 'transformers.AutoModelForCausalLM.generate'}`",
        f"- model_id: `{(health or {}).get('model_id') or man.get('model_id')}`",
        f"- revision: `{(health or {}).get('model_revision') or man.get('model_revision')}`",
        f"- gpu: `{(health or {}).get('gpu') or man.get('gpu')}`",
        f"- quantization: `{(health or {}).get('quantization') or man.get('quantization')}`",
        f"- prompt_version: `{PROMPT_VERSION}`",
        f"- inference: temperature={inf.get('temperature')}, top_p={inf.get('top_p')}, max_new_tokens={inf.get('max_new_tokens')}, do_sample=False",
        "- one window per prompt / per `.remote()`: **yes**",
        "- stack: **transformers** (no vLLM, no FlashInfer, no nvcc, no 72B-AWQ)",
        "- writes: **resume-safe local jsonl** (skip ids already in labels/failures)",
        "",
        "## 2000 = success + fail",
        "",
        f"- frozen ids: {len(ids)}",
        f"- success (parsed SPEAK/SILENT): **{n_ok}**",
        f"- fail (timeout/parse after {TEACHER_RETRIES} retries): **{n_fail}**",
        f"- success + fail: **{n_ok + n_fail}**",
        f"- integrity: `{integrity_ok(ids)[1]}`",
        "",
        "## Overall rates (successes only)",
        "",
        f"- SPEAK: **{len(speak)}** / {n_ok} ({(100 * len(speak) / n_ok if n_ok else 0):.1f}%)",
        f"- SILENT: **{len(silent)}** / {n_ok} ({(100 * len(silent) / n_ok if n_ok else 0):.1f}%)",
        "",
        "## Speak rate by stratum",
        "",
        f"- question (last_is_question): {_rate(by_stratum.get('question', []))}",
        f"- addressed, not question: {_rate(by_stratum.get('addressed_not_question', []))}",
        f"- other: {_rate(by_stratum.get('other', []))}",
        "",
        "## Speak rate vs guideline_hint (hint is NOT gold)",
        "",
        "| hint | n | SPEAK % |",
        "|---|---:|---:|",
    ]
    for hint, rows in sorted(hint_buckets.items(), key=lambda kv: -len(kv[1])):
        s = sum(1 for r in rows if r.get("label_silver") == "SPEAK")
        pct = 100 * s / len(rows) if rows else 0
        lines.append(f"| {hint} | {len(rows)} | {pct:.1f} |")

    def _ex_block(title: str, rows: list[dict], k: int = 8) -> None:
        lines.append("")
        lines.append(f"## {title}")
        lines.append("")
        for r in rows[:k]:
            lines.append(f"- `{r['window_id']}` **{r.get('label_silver')}** — last: `{_last_line(r.get('chat_block', ''))}`")
            lines.append(f"  - reason: {r.get('reason')}")

    _ex_block("8 example SPEAK windows", speak)
    _ex_block("8 example SILENT windows", silent)
    _ex_block("8 disagreements with guideline_hint", disagrees)
    lines += ["", "## Failures", ""]
    if not fails:
        lines.append("- none")
    else:
        from collections import Counter

        c = Counter(str(r.get("error", "?"))[:80] for r in fails)
        for err, n in c.most_common(12):
            lines.append(f"- n={n}: `{err}`")
    lines += ["", "## Dry-run raw JSON (first 3)", ""]
    for i, raw in enumerate(dry_raw, 1):
        snippet = (raw or "")[:500].replace("```", "`'`")
        lines.append(f"{i}. `{snippet}`")
        lines.append("")
    lines += [
        "## Resume",
        "",
        "Id file is frozen and will not be reshuffled. Re-run skips written ids.",
        "",
        "```bash",
        "uv run python scripts/06_silver_label_pilot.py --poll",
        "```",
        "",
        "## Warning",
        "",
        "These are **SILVER** labels from a teacher LLM, **not gold**.",
        "Do not copy them into `label_gold` on `label_queue.csv` (that column is human-only).",
        "Humans must audit 100–200 of these windows next before any 30k/223k job.",
        "Do not claim zero hallucination. Do not train LoRA on this pilot alone.",
        "",
        f"System prompt prefix: `{TEACHER_SYSTEM_PROMPT[:80]}…`",
        "",
    ]
    PILOT_2K_RESULTS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("wrote {}", PILOT_2K_RESULTS_MD)


def _update_manifest_model(info: dict[str, Any]) -> None:
    man = json.loads(PILOT_2K_MANIFEST.read_text(encoding="utf-8"))
    ids_before = list(man["window_ids"])
    for k in ("model_id", "model_revision", "backend", "gpu", "quantization"):
        if info.get(k) is not None:
            man[k] = info.get(k)
    man["model_filled_at_utc"] = datetime.now(timezone.utc).isoformat()
    if man["window_ids"] != ids_before:
        raise AssertionError("refusing to write manifest: window_ids would change")
    PILOT_2K_MANIFEST.write_text(json.dumps(man, indent=2), encoding="utf-8")


def finalize(ids: list[str]) -> None:
    write_raw_from_labels()
    write_parquet_from_jsonl()
    man = json.loads(PILOT_2K_MANIFEST.read_text(encoding="utf-8"))
    health = None
    if HEALTH_PATH.exists():
        health = json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
        _update_manifest_model(health)
        man = json.loads(PILOT_2K_MANIFEST.read_text(encoding="utf-8"))
    dry_raw: list[str] = []
    if DRY_PATH.exists():
        dry = json.loads(DRY_PATH.read_text(encoding="utf-8"))
        dry_raw = [d.get("raw_text") or "" for d in dry]
        for d in dry:
            console.print(Panel((d.get("raw_text") or "")[:800], title=f"DRY RAW {d.get('window_id')}"))
    write_results_md(ids, man, health, dry_raw)


def _write_progress(n: int, n_ok: int, n_fail: int, health: dict[str, Any], status: str) -> None:
    PROGRESS_PATH.write_text(
        json.dumps(
            {
                "status": status,
                "n": n,
                "n_ok": n_ok,
                "n_fail": n_fail,
                "n_done": n_ok + n_fail,
                "updated_unix": time.time(),
                **health,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _remote_one(teacher, item: dict[str, Any]) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(3):
        try:
            return teacher.label_one.remote(item)
        except Exception as exc:  # noqa: BLE001
            last = exc
            logger.warning("remote {} attempt {}: {}: {}", item["window_id"], attempt + 1, type(exc).__name__, exc)
            time.sleep(2 * (attempt + 1))
    return {
        "window_id": item["window_id"],
        "error": f"remote {type(last).__name__}: {last}",
        "backend": "modal",
        "prompt_version": PROMPT_VERSION,
        "retries": TEACHER_RETRIES,
        "raw_ok": False,
        "raw_text": "",
        "split": item.get("split") or "",
        "date": item.get("date") or "",
        "t_id": item.get("t_id") or "",
    }


def run_teacher(ids: list[str], payloads: list[dict[str, Any]]) -> str:
    import modal

    from soma_data.modal_teacher import Teacher, app

    done = _done_ids()
    remaining = [p for p in payloads if p["window_id"] not in done]
    n_ok = len(_load_jsonl(PILOT_2K_LABELS_JSONL))
    n_fail = len(_load_jsonl(PILOT_2K_FAILURES_JSONL))
    console.print(f"pending={len(remaining)} already_ok={n_ok} already_fail={n_fail}")

    if not remaining:
        finalize(ids)
        return "complete"

    dry_needed = n_ok == 0
    dry_items = remaining[:3] if dry_needed else []
    rest = remaining[3:] if dry_needed else remaining

    with modal.enable_output():
        with app.run():
            teacher = Teacher()
            health = teacher.health_info.remote()
            HEALTH_PATH.write_text(json.dumps(health, indent=2), encoding="utf-8")
            _update_manifest_model(health)
            console.print(Panel(json.dumps(health, indent=2), title="TEACHER_READY"))

            dry_raw: list[dict[str, Any]] = []
            for i, item in enumerate(dry_items, 1):
                rec = _remote_one(teacher, item)
                dry_raw.append(
                    {
                        "window_id": item["window_id"],
                        "raw_text": rec.get("raw_text") or "",
                        "raw_ok": rec.get("raw_ok"),
                        "error": rec.get("error"),
                    }
                )
                console.print(
                    Panel(
                        (rec.get("raw_text") or rec.get("error") or "")[:800],
                        title=f"DRY {i}/3 {item['window_id']} ok={rec.get('raw_ok')}",
                    )
                )
                _commit_rec(rec)
                if rec.get("raw_ok"):
                    n_ok += 1
                else:
                    n_fail += 1
            if dry_items:
                DRY_PATH.write_text(json.dumps(dry_raw, indent=2), encoding="utf-8")
                ok_dry = sum(1 for d in dry_raw if d.get("raw_ok"))
                if ok_dry < len(dry_items):
                    _write_progress(len(payloads), n_ok, n_fail, health, "dry_fail")
                    finalize(ids)
                    return "dry_fail"

            for i, item in enumerate(rest, 1):
                rec = _remote_one(teacher, item)
                _commit_rec(rec)
                if rec.get("raw_ok"):
                    n_ok += 1
                    tag = rec.get("label_silver")
                else:
                    n_fail += 1
                    tag = rec.get("error")
                n_done = n_ok + n_fail
                console.print(f"{n_done}/{len(payloads)} {item['window_id']} {tag}")
                if n_done % 25 == 0 or i == len(rest):
                    _write_progress(len(payloads), n_ok, n_fail, health, "running")

    _write_progress(len(payloads), n_ok, n_fail, health if HEALTH_PATH.exists() else {}, "complete")
    finalize(ids)
    return "complete"


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    ensure_dirs()

    for p in (LABEL_QUEUE_CSV, PILOT_2K_IDS, PILOT_2K_MANIFEST):
        if not p.exists():
            raise FileNotFoundError(f"missing {p}. Run 05_select_pilot_2k.py first.")
        console.print(f"[green]ok[/green] {p.name} ({p.stat().st_size:,} bytes)")

    ids = load_frozen_ids()
    if len(ids) != 2000:
        raise AssertionError(f"frozen ids={len(ids)} != 2000")
    man = json.loads(PILOT_2K_MANIFEST.read_text(encoding="utf-8"))
    if man["window_ids"] != ids:
        raise AssertionError("manifest.window_ids != pilot_2k_ids.txt")
    console.print(f"frozen ids={len(ids)} seed={man['seed']} (will not reshuffle)")

    patch_manifest_inference()

    status = detect_modal()
    console.print(Panel(json.dumps({k: status[k] for k in status if k != "error"}, indent=2), title="Modal detect"))
    if not status.get("usable"):
        console.print(modal_setup_instructions())
        raise SystemExit(2)

    payloads = build_payloads(ids)
    console.print(f"payloads={len(payloads)} max_new_tokens={TEACHER_MAX_NEW_TOKENS}")
    result = run_teacher(ids, payloads)
    ok, msg = integrity_ok(ids)
    console.print(f"job status={result} integrity={msg}")
    if result == "dry_fail":
        console.print("[red]dry-run JSON parse was not solid — not labelling the remaining windows[/red]")
        raise SystemExit(3)
    if not ok:
        console.print("[yellow]incomplete — re-run 06 / --poll to resume (skips written ids)[/yellow]")
        raise SystemExit(4)
    console.print("[green]pilot 2k complete[/green]")


if __name__ == "__main__":
    main()
