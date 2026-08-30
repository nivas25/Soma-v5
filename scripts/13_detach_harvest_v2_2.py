"""Snapshot local harvest jsonl, upload to Modal volume, spawn detached GPU loop.

Resume-only: never truncates labels. Skips done window_ids. Target 5100 SPEAK.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soma_data.config import (  # noqa: E402
    HARVEST_SILENT_N,
    HARVEST_SPEAK_N,
    PILOT_V2_2_FAILURES_JSONL,
    PILOT_V2_2_LABELS_JSONL,
)
from soma_data.modal_teacher import harvest_vol  # noqa: E402

NEED_SPEAK = HARVEST_SPEAK_N + 100
NEED_SILENT = HARVEST_SILENT_N + 100
PENDING_LOCAL = ROOT / "data" / "interim" / "harvest_pending_v2_2.jsonl"
BAK_DIR = ROOT / "data" / "silver" / "harvest_detach_bak"


def _load_harvest12():
    spec = importlib.util.spec_from_file_location(
        "harvest12", ROOT / "scripts" / "12_harvest_pilot_v2_2.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _ids_and_counts(path: Path) -> tuple[set[str], int, int]:
    done: set[str] = set()
    speak = silent = 0
    if not path.exists():
        return done, speak, silent
    with path.open(encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rec = json.loads(ln)
            except json.JSONDecodeError:
                continue
            wid = rec.get("window_id") or ""
            if not wid or wid in done:
                continue
            done.add(wid)
            lab = str(rec.get("label_silver") or "").strip().upper()
            if rec.get("raw_ok") and lab == "SPEAK":
                speak += 1
            elif rec.get("raw_ok") and lab == "SILENT":
                silent += 1
    return done, speak, silent


def snapshot_and_pending() -> tuple[int, int, int]:
    BAK_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PILOT_V2_2_LABELS_JSONL, BAK_DIR / "pilot_v2_2_labels.jsonl")
    if PILOT_V2_2_FAILURES_JSONL.exists():
        shutil.copy2(PILOT_V2_2_FAILURES_JSONL, BAK_DIR / "pilot_v2_2_failures.jsonl")
    h = _load_harvest12()
    done, speak, silent = _ids_and_counts(PILOT_V2_2_LABELS_JSONL)
    fail_done, _, _ = _ids_and_counts(PILOT_V2_2_FAILURES_JSONL)
    done |= fail_done
    print(f"SNAPSHOT speak={speak}/{NEED_SPEAK} silent={silent}/{NEED_SILENT} done={len(done)}")
    if speak < 1000:
        raise SystemExit(f"REFUSE restart-from-zero: speak={speak}")
    held = h.test_ids()
    qmap = h.queue_map()
    ids = h.candidate_ids(held)
    PENDING_LOCAL.parent.mkdir(parents=True, exist_ok=True)
    n_pend = 0
    with PENDING_LOCAL.open("w", encoding="utf-8") as fh:
        for wid in ids:
            if wid in done:
                continue
            row = qmap.loc[wid].to_dict()
            fh.write(json.dumps(h.build_item(row), ensure_ascii=False) + "\n")
            n_pend += 1
    print(f"PENDING wrote {n_pend} items → {PENDING_LOCAL}")
    return speak, silent, n_pend


def upload() -> None:
    print("UPLOAD soma-harvest volume …")
    with harvest_vol.batch_upload(force=True) as batch:
        batch.put_file(str(PILOT_V2_2_LABELS_JSONL), "pilot_v2_2_labels.jsonl")
        if PILOT_V2_2_FAILURES_JSONL.exists():
            batch.put_file(str(PILOT_V2_2_FAILURES_JSONL), "pilot_v2_2_failures.jsonl")
        batch.put_file(str(PENDING_LOCAL), "pending_items.jsonl")
    print("UPLOAD done")


def main() -> None:
    t0 = time.time()
    speak, silent, n_pend = snapshot_and_pending()
    if speak >= NEED_SPEAK and silent >= NEED_SILENT:
        print("quotas already filled; not spawning")
        return
    if n_pend <= 0:
        raise SystemExit("no pending items")
    upload()
    print(f"prep {time.time() - t0:.1f}s — spawning detached harvest")
    spawn_detached()


def spawn_detached() -> None:
    import modal

    from soma_data.modal_teacher import Teacher, app

    with modal.enable_output():
        with app.run(detach=True) as running:
            T = Teacher.with_options(timeout=10 * 60 * 60, max_containers=1)
            call = T().harvest_until.spawn()
            cid = getattr(call, "object_id", None) or str(call)
            aid = getattr(running, "app_id", None) or getattr(app, "app_id", None)
            print(f"DETACHED_APP_ID={aid}")
            print(f"DETACHED_CALL_ID={cid}")
            print("YES you can close the lid. Loop is inside one Modal GPU function; resume-only.")


if __name__ == "__main__":
    main()
