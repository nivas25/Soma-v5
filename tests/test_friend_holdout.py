from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from soma_data.config import (
    FRIEND_400_IDS,
    MANU_200_CSV,
    PUNITH_200_CSV,
    SFT_DEV_JSONL,
    SFT_TEST_JSONL,
    SFT_TRAIN_1TO1_JSONL,
    SFT_TRAIN_1TO3_JSONL,
)


def _ids_jsonl(path: Path) -> set[str]:
    ids = set()
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        ids.add(json.loads(ln)["window_id"])
    return ids


@pytest.mark.skipif(not MANU_200_CSV.exists(), reason="run scripts/16_freeze_friends_and_splits.py first")
def test_friend_sheets_empty_gold_and_disjoint():
    manu = pd.read_csv(MANU_200_CSV, dtype=str, keep_default_na=False)
    punith = pd.read_csv(PUNITH_200_CSV, dtype=str, keep_default_na=False)
    assert len(manu) == 200
    assert len(punith) == 200
    for df in (manu, punith):
        assert df["label_gold"].str.strip().eq("").all()
        assert df["labeler"].str.strip().eq("").all()
        assert df["review_ok"].str.strip().eq("").all()
        assert df["label_silver"].str.strip().eq("").all()
        assert df["reviewed_by"].str.strip().eq("").all()
    m = set(manu["window_id"])
    p = set(punith["window_id"])
    assert not m & p
    listed = [ln.strip() for ln in FRIEND_400_IDS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert listed[:200] == manu["window_id"].tolist()
    assert listed[200:] == punith["window_id"].tolist()


@pytest.mark.skipif(not SFT_TRAIN_1TO3_JSONL.exists(), reason="run freeze script first")
def test_split_overlaps_are_zero_vs_test_and_friends():
    t1 = _ids_jsonl(SFT_TRAIN_1TO1_JSONL)
    t3 = _ids_jsonl(SFT_TRAIN_1TO3_JSONL)
    te = _ids_jsonl(SFT_TEST_JSONL)
    fr = {ln.strip() for ln in FRIEND_400_IDS.read_text(encoding="utf-8").splitlines() if ln.strip()}
    assert len(t1) == 10200
    assert len(t3) == 20400
    assert len(te) == 200
    assert len(fr) == 400
    assert not t1 & te
    assert not t3 & te
    assert not t1 & fr
    assert not t3 & fr
    assert not te & fr
    assert SFT_DEV_JSONL.read_text(encoding="utf-8").startswith("# friends 400")
