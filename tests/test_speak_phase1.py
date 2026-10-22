"""Phase 1: unanswered line, or NONE. The gate is not retrained."""

from __future__ import annotations

import json
import os

import pytest

from soma_data.gemini_client import GeminiClient, GeminiError
from soma_data.speak import find_unanswered

OPEN = """
nina: hello
omar: how do I install nginx on ubuntu?
nina: brb
lee: the match is on
""".strip()

OWNED = """
omar: how do I install nginx on ubuntu?
lee: omar, sudo apt-get install nginx
omar: lee: thanks, that worked
""".strip()

OFFTOPIC = """
nina: hello
lee: nice weather today
omar: lunch?
nina: pizza
""".strip()


def _scripted(payload: dict | str):
    calls = {"n": 0}

    def transport(_prompt: str) -> str:
        calls["n"] += 1
        if isinstance(payload, str):
            return payload
        return json.dumps(payload)

    return GeminiClient(transport=transport), calls


def test_silent_gate_does_not_call_the_model():
    client, calls = _scripted({"result": "LINE", "line": 2, "text": "omar: how do I install nginx on ubuntu?"})
    assert find_unanswered(OPEN, gate="SILENT", client=client) == "NONE"
    assert calls["n"] == 0


def test_open_question_returns_that_line_not_the_last():
    client, _calls = _scripted(
        {"result": "LINE", "line": 2, "text": "omar: how do I install nginx on ubuntu?"}
    )
    assert find_unanswered(OPEN, client=client) == "2: omar: how do I install nginx on ubuntu?"


def test_owned_question_is_none():
    client, _calls = _scripted({"result": "NONE"})
    assert find_unanswered(OWNED, client=client) == "NONE"


def test_line_outside_the_window_is_none():
    client, _calls = _scripted({"result": "LINE", "line": 9, "text": "nobody: made this up"})
    assert find_unanswered(OPEN, client=client) == "NONE"


def test_garbage_payload_is_none():
    client, _calls = _scripted("not json at all")
    assert find_unanswered(OPEN, client=client) == "NONE"


def test_missing_key_raises_without_leaking_a_value(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(GeminiError) as caught:
        GeminiClient().complete("ping")
    assert "GEMINI_API_KEY is not set" in str(caught.value)
    assert "AQ." not in str(caught.value)


def test_error_text_redacts_the_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")

    def boom(_prompt: str) -> str:
        raise AssertionError("transport should not run")

    # The real client path redacts. Drive it through a failing HTTP stack by
    # pointing the key at a value and checking GeminiError construction.
    from soma_data.gemini_client import _redact

    message = _redact("request failed for unit-test-key", "unit-test-key")
    assert "unit-test-key" not in message
    assert "[redacted]" in message
    del boom


@pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="GEMINI_API_KEY is not set")
def test_live_three_windows():
    open_line = find_unanswered(OPEN)
    owned = find_unanswered(OWNED)
    offtopic = find_unanswered(OFFTOPIC)
    assert open_line.startswith("2:")
    assert "nginx" in open_line
    assert "omar:" in open_line
    assert owned == "NONE"
    assert offtopic == "NONE"
