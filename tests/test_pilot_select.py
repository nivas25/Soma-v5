from __future__ import annotations

import pandas as pd

from soma_data.pilot_select import assign_strata, select_pilot


def _row(i: int, *, q: bool, addr: str) -> dict:
    return {
        "window_id": f"id:{i:04d}",
        "last_is_question": str(q),
        "addressed_to": addr,
        "split": "train",
    }


def test_strata_disjoint():
    df = pd.DataFrame(
        [
            _row(1, q=True, addr="bob"),
            _row(2, q=True, addr=""),
            _row(3, q=False, addr="ann"),
            _row(4, q=False, addr=""),
        ]
    )
    s = assign_strata(df)
    assert s.tolist() == ["question", "question", "addressed_not_question", "other"]


def test_select_is_deterministic_and_sorted():
    rows = []
    for i in range(50):
        rows.append(_row(i, q=i < 20, addr="bob" if 20 <= i < 35 else ""))
    df = pd.DataFrame(rows)
    a, _ = select_pilot(df, seed=42, n=12, targets={"question": 4, "addressed_not_question": 4, "other": 4})
    b, _ = select_pilot(df, seed=42, n=12, targets={"question": 4, "addressed_not_question": 4, "other": 4})
    assert a["window_id"].tolist() == b["window_id"].tolist()
    assert a["window_id"].tolist() == sorted(a["window_id"].tolist())
    assert len(a) == 12
    assert a["window_id"].nunique() == 12
