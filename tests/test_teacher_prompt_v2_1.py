from soma_data.config import AUDIT_200_IDS
from soma_data.teacher_prompt_v2_1 import (
    PROMPT_VERSION,
    TEACHER_SYSTEM_PROMPT_V2_1,
    build_chat_messages,
    build_user_payload_v2_1,
    few_shot_window_ids,
    helper_still_in_window,
)


def test_v2_1_quieter_than_v2():
    assert PROMPT_VERSION == "pilot_v2.1"
    assert "even if it says Nick" not in TEACHER_SYSTEM_PROMPT_V2_1
    assert "helper still present" in TEACHER_SYSTEM_PROMPT_V2_1.lower() or "already spoke in the window" in TEACHER_SYSTEM_PROMPT_V2_1
    msgs = build_chat_messages("LIVE")
    joined = "\n".join(m["content"] for m in msgs if m["role"] == "assistant")
    assert '"label":"SPEAK","reason":"named helper but last step failed"' not in joined
    assert "enrico still in window" in joined


def test_payload_helper_flag_and_no_hint():
    row = {
        "window_id": "x:1",
        "last_speaker": "sktrdie",
        "last_is_question": "False",
        "last_is_thanks": "False",
        "addressed_to": "enrico",
        "last_line": "sktrdie: enrico: nothing happens",
        "chat_block": "enrico: try a terminal\nsktrdie: enrico: nothing happens",
        "guideline_hint": "addressed to human",
    }
    p = build_user_payload_v2_1(row)
    assert "guideline_hint" not in p
    assert "helper_in_window=yes" in p
    assert helper_still_in_window(row) is True


def test_few_shots_not_audit_ids():
    ids = few_shot_window_ids()
    assert all(i.startswith("shot:") for i in ids)
    frozen = set()
    if AUDIT_200_IDS.exists():
        frozen = {ln.strip() for ln in AUDIT_200_IDS.read_text(encoding="utf-8").splitlines() if ln.strip()}
    assert ids.isdisjoint(frozen)
