"""Upload 1to3+test to Modal volume and spawn detached LoRA train. Laptop can die."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import modal  # noqa: E402
from soma_data.config import (  # noqa: E402
    SFT_TEST_JSONL,
    SFT_TRAIN_1TO3_JSONL,
)
from soma_data.modal_lora import app, train_run, train_vol  # noqa: E402


def _load(path: Path) -> list[dict]:
    rows = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        rows.append(json.loads(ln))
    return rows


def verify_local() -> None:
    if not SFT_TRAIN_1TO3_JSONL.exists():
        raise SystemExit("missing sft_train_1to3.jsonl — freeze 1:3 first")
    tr = _load(SFT_TRAIN_1TO3_JSONL)
    te = _load(SFT_TEST_JSONL)
    print("LOCAL n_train", len(tr), dict(Counter(r["output"] for r in tr)))
    print("LOCAL n_test", len(te), dict(Counter(r["output"] for r in te)))
    ot = {r["window_id"] for r in tr} & {r["window_id"] for r in te}
    print("LOCAL overlap_train_test", len(ot))
    bad = [r["window_id"] for r in tr + te if r.get("output") not in {"SPEAK", "SILENT"}]
    print("LOCAL bad_outputs", len(bad))
    print("LOCAL raw_example_keys", sorted(tr[0].keys()))
    print("LOCAL raw_example_output", tr[0]["output"])
    print("LOCAL raw_example_input_head", tr[0]["input"][:280])
    if ot:
        raise SystemExit("FAIL overlap")
    if bad:
        raise SystemExit("FAIL labels")
    if len(tr) != 20400:
        raise SystemExit(f"FAIL train n={len(tr)}")


def main() -> None:
    verify_local()
    print("UPLOAD soma-lora-train …")
    with train_vol.batch_upload(force=True) as batch:
        batch.put_file(str(SFT_TRAIN_1TO3_JSONL), "data/sft_train_1to3.jsonl")
        batch.put_file(str(SFT_TEST_JSONL), "data/sft_test.jsonl")
    print("UPLOAD done — spawning detached Trainer.train() on H100")
    with modal.enable_output():
        with app.run(detach=True) as running:
            call = train_run.spawn()
            cid = getattr(call, "object_id", None) or str(call)
            aid = getattr(running, "app_id", None) or getattr(app, "app_id", None)
            print(f"DETACHED_APP_ID={aid}")
            print(f"DETACHED_CALL_ID={cid}")
            print(f"https://modal.com/apps/nivas3347r/main/{aid}")
            print("YES close the lid. The train LOOP is inside one Modal function, not local .remote() per step.")


if __name__ == "__main__":
    main()
