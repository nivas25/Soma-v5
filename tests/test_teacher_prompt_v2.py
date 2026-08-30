from soma_data.config import AUDIT_200_IDS
from soma_data.teacher_prompt_v2 import (
    PROMPT_VERSION,
    TEACHER_SYSTEM_PROMPT_V2,
    build_chat_messages,
    build_user_payload_v2,
    few_shot_window_ids,
)


def test_v2_constants():
    assert PROMPT_VERSION == "pilot_v2"
    assert "technical hint" not in TEACHER_SYSTEM_PROMPT_V2.lower()
    assert "guideline_hint" not in TEACHER_SYSTEM_PROMPT_V2
    assert "still-broken" in TEACHER_SYSTEM_PROMPT_V2 or "still-broken" in TEACHER_SYSTEM_PROMPT_V2.replace(" ", "")


def test_payload_has_no_hint_and_grok_shape():
    row = {
        "window_id": "ubuntu:train:2005-01-01:0:0:1",
        "last_speaker": "bob",
        "last_is_question": "True",
        "last_is_thanks": "False",
        "addressed_to": "",
        "last_line": "bob: how do I apt-get?",
        "chat_block": "ann: hi\nbob: how do I apt-get?",
        "guideline_hint": "question + no clear addressee",
    }
    p = build_user_payload_v2(row)
    assert "guideline_hint" not in p
    assert "WINDOW_ID: ubuntu:train:2005-01-01:0:0:1" in p
    assert "LAST: bob: how do I apt-get?" in p
    assert "addressed_to=" in p
    assert "Decide AFTER the last line. JSON only." in p


def test_few_shots_not_audit_ids():
    ids = few_shot_window_ids()
    assert ids
    assert all(i.startswith("shot:") for i in ids)
    frozen = set()
    if AUDIT_200_IDS.exists():
        frozen = {ln.strip() for ln in AUDIT_200_IDS.read_text(encoding="utf-8").splitlines() if ln.strip()}
    assert ids.isdisjoint(frozen)


def test_chat_messages_order():
    msgs = build_chat_messages("LIVE")
    assert msgs[0]["role"] == "system"
    assert msgs[-1] == {"role": "user", "content": "LIVE"}
    # 1 system + 8*2 shots + 1 live user
    assert len(msgs) == 1 + 16 + 1
    assert msgs[1]["role"] == "user"
    assert msgs[2]["role"] == "assistant"
    assert '"label":"SILENT"' in msgs[2]["content"]
