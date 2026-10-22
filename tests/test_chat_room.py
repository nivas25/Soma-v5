"""Room lines and typing. The gate stays at zero until the room is idle."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from soma_data.config import ROOT
from soma_data.chat_app import create_app
from soma_data.room_gate import open_question_line, question_still_open, room_gate
from soma_data.speak import draft_one

CLEAN = "how do I check which version of ubuntu I am running?"
_SNIPPET = (
    "DESCRIPTION lsb_release prints distribution-specific information. "
    "-a --all Show all of the above information, including the release number."
)


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


def _client(clock: _Clock, calls: dict[str, int]) -> TestClient:
    def gate(*_args: object, **_kwargs: object) -> str:
        calls["n"] += 1
        return "SPEAK"

    return TestClient(create_app(gate=gate, idle_s=4, clock=clock))


def test_room_gate_speaks_on_an_open_ubuntu_question():
    assert room_gate(f"omar: {CLEAN}") == "SPEAK"


def test_room_gate_is_silent_when_the_line_is_not_ubuntu():
    assert room_gate("nina: nice weather today") == "SILENT"
    assert room_gate("Nivas: Hi") == "SILENT"


def test_room_gate_speaks_on_a_permission_typo():
    asked = "Nivas: What is the command to change the persmision for group for my folder"
    assert room_gate(asked) == "SPEAK"
    follow = asked + "\nNivas: What to do /"
    assert room_gate(follow) == "SPEAK"
    owned = asked + "\nsoma: Use `chmod g+rwx folder` after chgrp.\nNivas: What to do /"
    assert room_gate(owned) == "SILENT"
    assert room_gate("Sai: Soo say me any comand what to do") == "SPEAK"


def test_join_and_post_store_a_human_line_without_calling_the_gate():
    clock = _Clock()
    calls = {"n": 0}
    client = _client(clock, calls)
    joined = client.post("/api/join", json={"room": "ubuntu", "nick": "omar"})
    assert joined.status_code == 200
    assert joined.json()["members"] == ["omar"]
    assert joined.json()["idle"] is False

    other = client.post("/api/join", json={"room": "ubuntu", "nick": "nina"})
    assert other.json()["members"] == ["nina", "omar"]

    posted = client.post("/api/rooms/ubuntu/lines", json={"nick": "omar", "text": "Hi"})
    assert posted.status_code == 200
    line = posted.json()["lines"][-1]
    assert line["nick"] == "omar"
    assert line["text"] == "Hi"
    assert line["reply_to"] is None
    assert "gate" not in line
    assert all(item["nick"] != "soma" for item in posted.json()["lines"])
    assert posted.json()["idle"] is False
    assert calls["n"] == 0


def test_typing_blocks_idle_and_a_line_during_typing_does_not_call_the_gate():
    clock = _Clock()
    calls = {"n": 0}
    client = _client(clock, calls)
    client.post("/api/join", json={"room": "ubuntu", "nick": "omar"})
    client.post("/api/join", json={"room": "ubuntu", "nick": "nina"})
    client.post("/api/rooms/ubuntu/lines", json={"nick": "omar", "text": "Hi"})

    typing = client.post("/api/rooms/ubuntu/typing", json={"nick": "nina", "typing": True})
    assert typing.json()["typing"] == ["nina"]
    assert typing.json()["idle"] is False

    during = client.post("/api/rooms/ubuntu/lines", json={"nick": "omar", "text": "still here"})
    assert during.json()["typing"] == ["nina"]
    assert all(item["nick"] != "soma" for item in during.json()["lines"])
    assert calls["n"] == 0

    cleared = client.post("/api/rooms/ubuntu/typing", json={"nick": "nina", "typing": False})
    assert cleared.json()["typing"] == []
    assert cleared.json()["idle"] is False
    assert calls["n"] == 0

    clock.t += 3
    room = client.get("/api/rooms/ubuntu").json()
    assert room["typing"] == []
    assert room["idle"] is False
    assert all(item["nick"] != "soma" for item in room["lines"])
    assert calls["n"] == 0


@pytest.mark.skipif(not (ROOT / "web" / "dist").is_dir(), reason="web/dist is not built")
def test_built_ui_is_served():
    client = TestClient(create_app())
    page = client.get("/")
    assert page.status_code == 200
    assert "SOMA room" in page.text
    assert 'id="root"' in page.text


def test_open_question_is_the_latest_unanswered_line():
    disk = "Arun: how do I check free disk space on ubuntu?"
    answered = disk + "\nSai: try `df -h`"
    assert open_question_line(answered) == ""
    latest = answered + "\nNivas: how do I install nginx on ubuntu?"
    assert open_question_line(latest) == "Nivas: how do I install nginx on ubuntu?"
    assert question_still_open(latest)


def test_draft_one_turns_a_bare_command_into_a_sentence():
    seen: dict[str, str] = {}

    def complete(prompt: str) -> str:
        seen["prompt"] = prompt
        return '{"reply":"`df -h`"}'

    window = "Arun: how do I check free disk space on ubuntu?"
    assert draft_one(window, complete) == "Run `df -h`."
    assert "how do I check free disk space on ubuntu?" in seen["prompt"]
    assert draft_one(window, lambda _prompt: '{"reply":"NONE"}') == ""


def test_draft_one_cleans_a_fenced_command_and_drops_a_placeholder():
    version = "omar: how do I check which version of ubuntu I am running?"
    assert draft_one(version, lambda _prompt: '{"reply":"```ubuntu lsb_release -d```"}') == "Run `lsb_release -d`."
    assert draft_one(version, lambda _prompt: '{"reply":"the line"}') == ""
    either = draft_one(
        version,
        lambda _prompt: '{"reply":"`lsb_release -d` OR `ubuntu-version`"}',
    )
    assert either == "Run `lsb_release -d`."
    nginx = (
        "Arun: how do I check free disk space on ubuntu?\n"
        "Sai: try `df -h`\n"
        "Nivas: how do I install nginx on ubuntu?"
    )
    reply = draft_one(nginx, lambda _prompt: '{"reply":"`sudo apt-get install nginx`"}')
    assert reply == "Run `sudo apt-get install nginx`."


def test_draft_one_skips_the_model_when_a_human_already_answered():
    called = {"n": 0}

    def complete(_prompt: str) -> str:
        called["n"] += 1
        return '{"reply":"Run `df -h`."}'

    window = "Arun: how do I check free disk space on ubuntu?\nSai: try `df -h`"
    assert draft_one(window, complete) == ""
    assert called["n"] == 0


def test_stranger_cannot_post():
    client = TestClient(create_app())
    client.post("/api/join", json={"room": "ubuntu", "nick": "omar"})
    denied = client.post("/api/rooms/ubuntu/lines", json={"nick": "nina", "text": "hello"})
    assert denied.status_code == 403
