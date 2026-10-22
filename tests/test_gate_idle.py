"""Idle calls the deployed soma-gate once per human line. No reply text."""

from __future__ import annotations

from fastapi.testclient import TestClient

from soma_data.chat_app import create_app
from soma_data.modal_gate import gate_raw
from soma_data.parse_irc import extract_addressed_to, has_question, is_thanks
from soma_data.teacher_prompt_v2_2 import SFT_INSTRUCTION_V2_2, build_user_payload_v2_2


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


def _row(line_id: int, last_nick: str, last_text: str, chat: str) -> dict:
    return {
        "window_id": f"room:ubuntu:{line_id}",
        "last_speaker": last_nick,
        "last_is_question": has_question(last_text),
        "last_is_thanks": is_thanks(last_text),
        "addressed_to": extract_addressed_to(last_text),
        "last_line": f"{last_nick}: {last_text}",
        "chat_block": chat,
    }


def test_live_gate_runs_once_per_human_line_and_posts_nothing():
    clock = _Clock()
    calls = {"n": 0}
    seen: list[tuple[str, str]] = []
    failures: list[str] = []

    def gate(instruction: str, user_input: str) -> str:
        calls["n"] += 1
        seen.append((instruction, user_input))
        print(f"CALL {calls['n']}", flush=True)
        try:
            return gate_raw(instruction, user_input)
        except Exception as exc:
            failures.append(f"{type(exc).__name__}: {exc}")
            raise

    app = create_app(gate=gate, idle_s=4, clock=clock)
    client = TestClient(app)
    client.timeout = None
    client.post("/api/join", json={"room": "ubuntu", "nick": "omar"})

    first_text = "how do I check free disk space on ubuntu?"
    posted = client.post("/api/rooms/ubuntu/lines", json={"nick": "omar", "text": first_text})
    assert posted.status_code == 200
    assert posted.json()["idle"] is False
    assert calls["n"] == 0
    first = posted.json()["lines"][-1]
    assert first["reply_to"] is None
    assert set(first) == {"id", "nick", "text", "reply_to"}

    clock.t += 4
    idle = client.get("/api/rooms/ubuntu")
    assert idle.status_code == 200
    body = idle.json()
    assert body["idle"] is True
    assert calls["n"] == 1, failures
    assert all(item["nick"] != "soma" for item in body["lines"])
    assert all(set(item) == {"id", "nick", "text", "reply_to"} for item in body["lines"])

    record = app.state.rooms["ubuntu"].results[first["id"]]
    assert record.error is None, failures
    assert record.token in {"SPEAK", "SILENT"}
    assert record.raw
    expected = build_user_payload_v2_2(_row(first["id"], "omar", first_text, f"omar: {first_text}"))
    assert seen[0][0] == SFT_INSTRUCTION_V2_2
    assert seen[0][1] == expected
    assert record.payload == expected
    assert f"WINDOW_ID: room:ubuntu:{first['id']}" in record.payload

    again = client.get("/api/rooms/ubuntu")
    assert again.status_code == 200
    assert again.json()["idle"] is True
    assert calls["n"] == 1
    assert app.state.rooms["ubuntu"].results[first["id"]].raw == record.raw

    clock.t += 4
    later = client.get("/api/rooms/ubuntu")
    assert later.json()["idle"] is True
    assert calls["n"] == 1

    second_text = "how do I install nginx on ubuntu?"
    nxt = client.post("/api/rooms/ubuntu/lines", json={"nick": "omar", "text": second_text})
    assert nxt.status_code == 200
    assert nxt.json()["idle"] is False
    assert calls["n"] == 1
    second = nxt.json()["lines"][-1]
    assert second["id"] != first["id"]
    assert all(item["nick"] != "soma" for item in nxt.json()["lines"])

    clock.t += 4
    follow = client.get("/api/rooms/ubuntu")
    assert follow.status_code == 200
    assert follow.json()["idle"] is True
    assert calls["n"] == 2, failures
    assert all(item["nick"] != "soma" for item in follow.json()["lines"])
    assert [item["text"] for item in follow.json()["lines"]] == [first_text, second_text]

    chat = f"omar: {first_text}\nomar: {second_text}"
    second_expected = build_user_payload_v2_2(_row(second["id"], "omar", second_text, chat))
    stored = app.state.rooms["ubuntu"].results[second["id"]]
    assert stored.error is None, failures
    assert stored.token in {"SPEAK", "SILENT"}
    assert stored.payload == second_expected
    assert seen[1][0] == SFT_INSTRUCTION_V2_2
    assert seen[1][1] == second_expected
    assert app.state.rooms["ubuntu"].results[first["id"]].payload == expected
    print(f"LABEL1 {record.token} RAW1 {record.raw!r}", flush=True)
    print(f"LABEL2 {stored.token} RAW2 {stored.raw!r}", flush=True)
