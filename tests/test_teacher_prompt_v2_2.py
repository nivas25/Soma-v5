from soma_data.config import AUDIT_200_IDS
from soma_data.teacher_prompt_v2_2 import (
    PROMPT_VERSION,
    TEACHER_SYSTEM_PROMPT_V2_2,
    build_chat_messages,
    build_user_payload_v2_2,
    few_shot_window_ids,
    helper_in_window,
)


def test_version_and_law():
    assert PROMPT_VERSION == "pilot_v2.2"
    assert "helper_in_window=yes" in TEACHER_SYSTEM_PROMPT_V2_2
    assert "brand-new group how-to" in TEACHER_SYSTEM_PROMPT_V2_2
    msgs = build_chat_messages("LIVE")
    joined = "\n".join(m["content"] for m in msgs if m["role"] == "assistant")
    assert "helper still present after failed step" in joined
    assert "last speaker is the helper diagnosing" in joined
    assert "new group how-to, ada thread has no helper" in joined


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
    p = build_user_payload_v2_2(row)
    assert "guideline_hint" not in p
    assert "helper_in_window=yes" in p
    assert helper_in_window(row) is True


def test_few_shots_not_audit_ids():
    ids = few_shot_window_ids()
    assert all(i.startswith("shot:") for i in ids)
    frozen = set()
    if AUDIT_200_IDS.exists():
        frozen = {ln.strip() for ln in AUDIT_200_IDS.read_text(encoding="utf-8").splitlines() if ln.strip()}
    assert ids.isdisjoint(frozen)


def test_stuck_no_nick_helper_yes():
    row = {
        "window_id": "shot:x",
        "last_speaker": "sean_",
        "last_is_question": "False",
        "last_is_thanks": "False",
        "addressed_to": "",
        "last_line": "sean_: I did, and it didn't accept",
        "chat_block": (
            "bluefox: sean_, open a terminal, type su and the password\n"
            "sean_: I did, and it didn't accept"
        ),
    }
    assert helper_in_window(row) is True
    assert "helper_in_window=yes" in build_user_payload_v2_2(row)


def test_helper_diagnostic_last_speaker():
    row = {
        "window_id": "shot:y",
        "last_speaker": "pat",
        "last_is_question": "True",
        "last_is_thanks": "False",
        "addressed_to": "",
        "last_line": "pat: mina, does it fully boot then reboot?",
        "chat_block": "mina: my machine reboots by itself\npat: mina, does it fully boot then reboot?",
    }
    assert helper_in_window(row) is True


def test_hanging_howto_helper_no_even_in_busy_room():
    row = {
        "window_id": "shot:z",
        "last_speaker": "ada",
        "last_is_question": "True",
        "last_is_thanks": "False",
        "addressed_to": "",
        "last_line": "ada: can I install this package with apt?",
        "chat_block": (
            "gil: othernick, try sudo apt-get update\n"
            "othernick: gil: thanks\n"
            "ada: can I install this package with apt?"
        ),
    }
    assert helper_in_window(row) is False
    assert "helper_in_window=no" in build_user_payload_v2_2(row)


def test_two_answers_to_last_speaker():
    row = {
        "window_id": "shot:w",
        "last_speaker": "mira",
        "last_is_question": "False",
        "last_is_thanks": "False",
        "addressed_to": "",
        "last_line": "mira: no dice",
        "chat_block": (
            "mira: flash will not play in firefox\n"
            "lex: mira: reinstall the plugin from synaptic\n"
            "mira: no dice"
        ),
    }
    assert helper_in_window(row) is True
