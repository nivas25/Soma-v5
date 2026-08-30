from __future__ import annotations

import pandas as pd

from soma_data.export import format_sft_input, sample_label_queue


def test_sft_input_shape():
    row = pd.Series(
        {
            "last_speaker": "Xophe",
            "question_open": True,
            "addressed_to": None,
            "assistant_named": False,
            "n_speakers_in_window": 3,
            "chat_block": "Ann: nvidia black screen\nKen: snap using 4GB\nXophe: where do I report minor bugs?",
        }
    )
    text = format_sft_input(row)
    assert text.startswith("[ROOM]\n")
    assert "last_speaker: Xophe" in text
    assert "question_open: yes" in text
    assert "addressed_to: group" in text
    assert "assistant_named: no" in text
    assert "[CHAT]\nAnn: nvidia black screen" in text


def test_sample_queue_over_cap_includes_others():
    rows = []
    for i in range(200):
        rows.append(
            {
                "window_id": f"w{i}",
                "last_is_question": i < 80,
                "addressed_to": "bob" if 80 <= i < 160 else None,
                "split": "train",
            }
        )
    df = pd.DataFrame(rows)
    q = sample_label_queue(df, cap=50, seed=0, other_fraction=0.35)
    assert len(q) == 50
    n_other = int((~q["last_is_question"] & q["addressed_to"].isna()).sum())
    assert n_other >= 10


def test_sample_queue_keeps_all_questions_when_under_cap():
    rows = []
    for i in range(20):
        rows.append(
            {
                "window_id": f"w{i}",
                "last_is_question": i < 5,
                "addressed_to": "bob" if 5 <= i < 8 else None,
                "split": "train",
            }
        )
    df = pd.DataFrame(rows)
    q = sample_label_queue(df, cap=100, seed=42, other_fraction=0.35)
    assert int(q["last_is_question"].sum()) == 5
    assert len(q) <= 100
    assert len(q) > 5  # others mixed in
