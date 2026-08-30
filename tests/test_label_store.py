from pathlib import Path

import pandas as pd

from soma_data.label_store import AuditStore, format_copy_text, parse_chat


def test_format_copy_text_nivas_shape():
    row = {
        "window_id": "ubuntu:test:2005-07-06:0:0:274",
        "date": "06-07-2005",
        "last_speaker": "jeroen_",
        "last_line": "jeroen_: curut, no, what Synaptic suggests",
        "chat_block": "ukato: or close to it\njeroen_: curut, no, what Synaptic suggests",
    }
    text = format_copy_text(row)
    assert text.startswith("ubuntu:test:2005-07-06:0:0:27406-07-2005last jeroen_\n")
    assert "ukato\nor close to it" in text
    assert "jeroen_\ncurut, no, what Synaptic suggests" in text
    assert text.endswith("Decide after this line\njeroen_: curut, no, what Synaptic suggests")


def test_format_copy_text_keeps_nick_text_pairs():
    row = {
        "window_id": "id:1",
        "date": "",
        "last_speaker": "bob",
        "last_line": "bob: still stuck",
        "chat_block": "alice\nhi\nbob\nstill stuck",
    }
    text = format_copy_text(row)
    assert "alice\nhi\nbob\nstill stuck" in text
    assert text.startswith("id:1last bob\n")


def test_parse_chat_highlights_last_line():
    chat = "alice: hi\nbob: anyone?\nalice: still stuck"
    msgs = parse_chat(chat, "alice: still stuck")
    assert len(msgs) == 3
    assert msgs[0]["nick"] == "alice"
    assert msgs[-1]["is_last"] is True
    assert msgs[0]["is_last"] is False


def test_reset_on_first_launch_keeps_silver(tmp_path: Path):
    src = tmp_path / "audit.csv"
    bak = tmp_path / "audit.bak.csv"
    pd.DataFrame(
        [
            {
                "window_id": "id:1",
                "chat_block": "a: hi\nb: help?",
                "last_line": "b: help?",
                "last_speaker": "b",
                "date": "2005-01-01",
                "label_silver": "SPEAK",
                "reason": "unanswered",
                "judge_reason": "draft reason",
                "label_gold": "SPEAK",
                "reviewed_by": "nivas",
                "review_ok": "Y",
                "agree_with_silver": "Y",
                "notes": "rubber",
            }
        ]
    ).to_csv(src, index=False)
    store = AuditStore(src, bak)
    assert bak.exists()
    assert store.reset_happened is True
    row = store.df.iloc[0]
    assert row["label_silver"] == "SPEAK"
    assert row["grok_draft"] == "SPEAK"
    assert row["label_gold"] == ""
    assert row["reviewed_by"] == ""
    assert row["review_ok"] == ""
    assert row["agree_with_silver"] == ""


def test_second_launch_does_not_reset(tmp_path: Path):
    src = tmp_path / "audit.csv"
    bak = tmp_path / "audit.bak.csv"
    pd.DataFrame(
        [{"window_id": "id:1", "label_gold": "", "review_ok": "", "label_silver": "SILENT", "chat_block": "a: x"}]
    ).to_csv(src, index=False)
    bak.write_text("already", encoding="utf-8")
    store = AuditStore(src, bak)
    assert store.reset_happened is False


def test_save_label_writes_reviewer(tmp_path: Path):
    src = tmp_path / "audit.csv"
    bak = tmp_path / "audit.bak.csv"
    pd.DataFrame(
        [
            {
                "window_id": "id:1",
                "chat_block": "u: how?",
                "last_line": "u: how?",
                "label_silver": "SPEAK",
                "label_gold": "",
                "review_ok": "",
                "reviewed_by": "",
                "agree_with_silver": "",
                "notes": "",
            }
        ]
    ).to_csv(src, index=False)
    bak.write_text("x", encoding="utf-8")
    store = AuditStore(src, bak)
    out = store.save_label(0, "SILENT", "unsure")
    assert out["saved"]["label_gold"] == "SILENT"
    reloaded = pd.read_csv(src, dtype=str, keep_default_na=False)
    assert reloaded.loc[0, "reviewed_by"] == "nivas"
    assert reloaded.loc[0, "review_ok"] == "Y"
    assert reloaded.loc[0, "agree_with_silver"] == "N"
    assert reloaded.loc[0, "notes"] == "unsure"
    assert reloaded.loc[0, "reviewed_at"]


def test_friend_reviewer_writes_done_files(tmp_path: Path, monkeypatch):
    from soma_data import label_store as ls

    src = tmp_path / "manu_200.csv"
    bak = tmp_path / "manu_200.bak.csv"
    pd.DataFrame(
        [
            {
                "window_id": "id:1",
                "chat_block": "u: how?",
                "last_line": "u: how?",
                "label_silver": "",
                "label_gold": "",
                "review_ok": "",
                "reviewed_by": "",
                "labeler": "",
                "agree_with_silver": "",
                "notes": "",
            }
        ]
    ).to_csv(src, index=False)
    monkeypatch.setattr(ls, "FRIENDS_DIR", tmp_path)
    store = ls.AuditStore(
        src,
        bak,
        reviewer="manu",
        skip_reset=True,
        hide_teacher_hints=True,
    )
    out = store.save_label(0, "SPEAK")
    assert out["saved"]["reviewed_by"] == "manu"
    assert out["saved"]["hints"] is None
    assert out["complete"] is True
    done = pd.read_csv(tmp_path / "manu_done.csv", dtype=str, keep_default_na=False)
    assert done.loc[0, "label_gold"] == "SPEAK"
    assert done.loc[0, "reviewed_by"] == "manu"
    assert (tmp_path / "manu_done.jsonl").exists()
