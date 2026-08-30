from __future__ import annotations

import pandas as pd

from soma_data.audit_select import assign_audit_bucket, select_audit


def _row(i: int, *, lab: str, hint: str, ok: bool = True) -> dict:
    rec = {
        "window_id": f"id:{i:04d}",
        "label_silver": lab,
        "guideline_hint": hint,
        "raw_ok": ok,
        "chat_block": f"nick: line {i}",
    }
    if not ok:
        rec["error"] = "parse"
        rec["label_silver"] = ""
    return rec


def test_bucket_assignment():
    assert assign_audit_bucket(_row(1, lab="SPEAK", hint="addressed to human")) == "speak_addressed"
    assert assign_audit_bucket(_row(2, lab="SILENT", hint="question + no clear addressee")) == "silent_open_q"
    assert assign_audit_bucket(_row(3, lab="SILENT", hint="thanks")) == "silent_thanks"
    assert assign_audit_bucket(_row(4, lab="SPEAK", hint="x", ok=False)) == "fail"
    assert assign_audit_bucket({"label_silver": "SPEAK", "guideline_hint": "other", "error": float("nan")}) == "speak_other"


def test_select_is_deterministic_sorted_unique():
    rows = []
    rows.append(_row(0, lab="", hint="", ok=False))
    for i in range(1, 80):
        rows.append(_row(i, lab="SPEAK", hint="question + no clear addressee"))
    for i in range(80, 120):
        rows.append(_row(i, lab="SPEAK", hint="addressed to human"))
    for i in range(120, 200):
        rows.append(_row(i, lab="SILENT", hint="question + no clear addressee"))
    for i in range(200, 320):
        rows.append(_row(i, lab="SILENT", hint="addressed to human"))
    df = pd.DataFrame(rows)
    a, _ = select_audit(df, seed=42, n=50)
    b, _ = select_audit(df, seed=42, n=50)
    assert a["window_id"].tolist() == b["window_id"].tolist()
    assert a["window_id"].tolist() == sorted(a["window_id"].tolist())
    assert a["window_id"].nunique() == len(a)
    assert len(a) == 50
