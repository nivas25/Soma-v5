"""Live Modal reply checks. The draft stays off the thread. No Gemini."""

from __future__ import annotations

from fastapi.testclient import TestClient

from soma_data.chat_app import create_app


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


def _settle(room: str, lines: list[tuple[str, str]]):
    clock = _Clock()
    app = create_app(idle_s=4, clock=clock)
    client = TestClient(app)
    client.timeout = None
    joined: set[str] = set()
    for nick, text in lines:
        if nick not in joined:
            joined_at = client.post("/api/join", json={"room": room, "nick": nick})
            assert joined_at.status_code == 200
            joined.add(nick)
        posted = client.post(f"/api/rooms/{room}/lines", json={"nick": nick, "text": text})
        assert posted.status_code == 200
        assert posted.json()["idle"] is False
    clock.t += 4
    page = client.get(f"/api/rooms/{room}")
    assert page.status_code == 200
    body = page.json()
    assert body["idle"] is True
    assert [item["text"] for item in body["lines"]] == [text for _, text in lines]
    assert all(item["nick"] != "soma" for item in body["lines"])
    assert all(set(item) == {"id", "nick", "text", "reply_to"} for item in body["lines"])
    last_id = body["lines"][-1]["id"]
    gate = app.state.rooms[room].results[last_id]
    draft = app.state.rooms[room].drafts.get(last_id)
    print(f"GATE {gate.token} RAW {gate.raw!r}", flush=True)
    if draft is None:
        print("DRAFT missing", flush=True)
    else:
        print(f"DRAFT reason={draft.reason!r} text={draft.text!r} raw={draft.raw!r}", flush=True)
    return gate, draft


def test_clean_open_question_stores_the_draft():
    gate, draft = _settle("clean", [("omar", "how do I check free disk space on ubuntu?")])
    assert gate.token == "SPEAK", gate.raw
    assert draft is not None
    assert draft.reason == "", (draft.reason, draft.raw)
    assert draft.text
    assert "df" in draft.text.lower()


def test_repeated_command_is_dropped():
    gate, draft = _settle(
        "repeat",
        [
            ("omar", "I tried `df -h /` yesterday"),
            ("omar", "how do I check free disk space on ubuntu?"),
        ],
    )
    assert gate.token == "SPEAK", gate.raw
    assert draft is not None
    assert draft.text == ""
    assert draft.reason == "overlap", (draft.reason, draft.raw)


def test_dangerous_command_is_dropped():
    gate, draft = _settle("danger", [("omar", "is mkfs.ext4 /dev/sda1 the way to format this ubuntu disk?")])
    assert gate.token == "SPEAK", gate.raw
    assert draft is not None
    assert draft.text == ""
    assert draft.reason == "denied", (draft.reason, draft.raw)


def test_none_stores_nothing():
    gate, draft = _settle(
        "quiet",
        [
            ("nina", "`df -h`"),
            ("sai", "no, that is wrong, use `du -sh /`"),
            ("omar", "how do I check free disk space on ubuntu?"),
        ],
    )
    assert gate.token == "SPEAK", gate.raw
    assert draft is not None
    assert draft.text == ""
    assert draft.reason == "none", (draft.reason, draft.raw)
