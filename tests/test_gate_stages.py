"""Gate panel stages are the steps the room actually ran."""

from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from soma_data.chat_app import create_app
from soma_data.speak import DraftResult

DISK = "how do I check free disk space on ubuntu?"
MEMORY = "how do I see memory usage on ubuntu?"
DISK_DRAFT = "type `df -h` in the terminal"
MEMORY_DRAFT = "type `free -h` in the terminal"


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


def _labels(page: dict, line_id: int) -> list[str]:
    row = next(item for item in page["gates"] if item["line_id"] == line_id)
    return [stage["label"] for stage in row["stages"]]


def _detail(page: dict, line_id: int, label: str) -> str:
    row = next(item for item in page["gates"] if item["line_id"] == line_id)
    return next(stage["detail"] for stage in row["stages"] if stage["label"] == label)


def _passed(line_id: int) -> list[str]:
    return [
        "Idle reached (no typing, 4s quiet).",
        "Payload built (last 12 lines, flags).",
        "Gate call returned SPEAK.",
        "Draft requested.",
        "Draft text, or NONE.",
        "clean: pass",
        "denied: pass",
        "overlap: pass",
        "contradicts: pass",
        f"Final: posted as reply to line {line_id}.",
    ]


def test_disk_space_and_memory_show_the_stages_that_ran():
    clock = _Clock()

    def complete(prompt: str) -> str:
        if prompt.startswith("Does this reply contradict"):
            return '{"contradicts":"NO"}'
        if "memory usage" in prompt:
            return '{"reply":"type `free -h` in the terminal"}'
        return '{"reply":"type `df -h` in the terminal"}'

    app = create_app(gate=lambda _instruction, _payload: "SPEAK", complete=complete, idle_s=4, clock=clock)
    client = TestClient(app)
    client.timeout = None
    client.post("/api/join", json={"room": "ubuntu", "nick": "arun"})
    client.post("/api/join", json={"room": "ubuntu", "nick": "nivas"})
    disk = client.post("/api/rooms/ubuntu/lines", json={"nick": "arun", "text": DISK}).json()["lines"][-1]
    clock.t += 4
    first = client.get("/api/rooms/ubuntu").json()
    assert _labels(first, disk["id"]) == _passed(disk["id"])
    assert _detail(first, disk["id"], "Draft text, or NONE.") == DISK_DRAFT
    assert "helper_in_window=" in _detail(first, disk["id"], "Payload built (last 12 lines, flags).")
    assert DISK in _detail(first, disk["id"], "Payload built (last 12 lines, flags).")
    soma = first["lines"][-1]
    assert soma["nick"] == "soma"
    assert soma["reply_to"] == disk["id"]
    assert soma["text"] == DISK_DRAFT

    memory = client.post("/api/rooms/ubuntu/lines", json={"nick": "nivas", "text": MEMORY}).json()["lines"][-1]
    clock.t += 4
    second = client.get("/api/rooms/ubuntu").json()
    assert _labels(second, memory["id"]) == _passed(memory["id"])
    assert _detail(second, memory["id"], "Draft text, or NONE.") == MEMORY_DRAFT
    assert MEMORY in _detail(second, memory["id"], "Payload built (last 12 lines, flags).")
    posted = [line for line in second["lines"] if line["nick"] == "soma"]
    assert [line["reply_to"] for line in posted] == [disk["id"], memory["id"]]
    assert posted[1]["text"] == MEMORY_DRAFT


def test_blocked_draft_shows_the_failing_check():
    clock = _Clock()

    def gate(_instruction: str, payload: str) -> str:
        if "how do I check free disk space" in payload:
            return "SPEAK"
        return "SILENT"

    def complete(prompt: str) -> str:
        if prompt.startswith("Does this reply contradict"):
            return '{"contradicts":"NO"}'
        return '{"reply":"use `df -h`"}'

    app = create_app(gate=gate, complete=complete, idle_s=4, clock=clock)
    client = TestClient(app)
    client.timeout = None
    client.post("/api/join", json={"room": "ubuntu", "nick": "omar"})
    earlier = client.post(
        "/api/rooms/ubuntu/lines",
        json={"nick": "omar", "text": "I tried `df -h /` yesterday"},
    ).json()["lines"][-1]
    clock.t += 4
    quiet = client.get("/api/rooms/ubuntu").json()
    assert _labels(quiet, earlier["id"]) == [
        "Idle reached (no typing, 4s quiet).",
        "Payload built (last 12 lines, flags).",
        "Gate call returned SILENT.",
        "Final: dropped (SILENT).",
    ]
    question = client.post("/api/rooms/ubuntu/lines", json={"nick": "omar", "text": DISK}).json()["lines"][-1]
    clock.t += 4
    page = client.get("/api/rooms/ubuntu").json()
    labels = _labels(page, question["id"])
    assert labels == [
        "Idle reached (no typing, 4s quiet).",
        "Payload built (last 12 lines, flags).",
        "Gate call returned SPEAK.",
        "Draft requested.",
        "Draft text, or NONE.",
        "clean: pass",
        "denied: pass",
        "overlap: fail",
        "Final: dropped (overlap).",
    ]
    assert "contradicts: pass" not in labels
    assert "contradicts: fail" not in labels
    assert all(line["nick"] != "soma" for line in page["lines"])


def _hold_get(app, clock: _Clock):
    started = threading.Event()
    release = threading.Event()
    client = TestClient(app)
    client.timeout = None
    client.post("/api/join", json={"room": "ubuntu", "nick": "omar"})
    question = client.post("/api/rooms/ubuntu/lines", json={"nick": "omar", "text": DISK}).json()["lines"][-1]
    clock.t += 4
    held: dict[str, object] = {}

    def fetch() -> None:
        other = TestClient(app)
        other.timeout = None
        held["page"] = other.get("/api/rooms/ubuntu")

    worker = threading.Thread(target=fetch)
    worker.start()
    assert started.wait(timeout=10)
    watcher = TestClient(app)
    watcher.timeout = None
    mid = watcher.get("/api/rooms/ubuntu").json()
    return started, release, client, question, held, worker, mid


def test_panel_shows_idle_and_payload_before_the_gate_returns():
    clock = _Clock()
    started = threading.Event()
    release = threading.Event()

    def gate(_instruction: str, _payload: str) -> str:
        started.set()
        assert release.wait(timeout=10)
        return "SPEAK"

    app = create_app(
        gate=gate,
        reply=lambda _window, _person, _question: DraftResult("", "", ""),
        idle_s=4,
        clock=clock,
    )
    client = TestClient(app)
    client.timeout = None
    client.post("/api/join", json={"room": "ubuntu", "nick": "omar"})
    question = client.post("/api/rooms/ubuntu/lines", json={"nick": "omar", "text": DISK}).json()["lines"][-1]
    clock.t += 4
    held: dict[str, object] = {}

    def fetch() -> None:
        other = TestClient(app)
        other.timeout = None
        held["page"] = other.get("/api/rooms/ubuntu")

    worker = threading.Thread(target=fetch)
    worker.start()
    assert started.wait(timeout=10)
    watcher = TestClient(app)
    watcher.timeout = None
    mid = watcher.get("/api/rooms/ubuntu").json()
    assert _labels(mid, question["id"]) == [
        "Idle reached (no typing, 4s quiet).",
        "Payload built (last 12 lines, flags).",
    ]
    release.set()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert "Gate call returned SPEAK." in _labels(held["page"].json(), question["id"])


def test_later_human_line_discards_the_draft_before_append():
    clock = _Clock()
    started = threading.Event()
    release = threading.Event()

    def reply(_window: str, _person: str, _question: str) -> DraftResult:
        started.set()
        assert release.wait(timeout=10)
        return DraftResult(DISK_DRAFT, "", DISK_DRAFT)

    app = create_app(gate=lambda _instruction, _payload: "SPEAK", reply=reply, idle_s=4, clock=clock)
    client = TestClient(app)
    client.timeout = None
    client.post("/api/join", json={"room": "ubuntu", "nick": "omar"})
    question = client.post("/api/rooms/ubuntu/lines", json={"nick": "omar", "text": DISK}).json()["lines"][-1]
    clock.t += 4
    held: dict[str, object] = {}

    def fetch() -> None:
        other = TestClient(app)
        other.timeout = None
        held["page"] = other.get("/api/rooms/ubuntu")

    worker = threading.Thread(target=fetch)
    worker.start()
    assert started.wait(timeout=10)
    watcher = TestClient(app)
    watcher.timeout = None
    mid = watcher.get("/api/rooms/ubuntu").json()
    assert "Draft requested." in _labels(mid, question["id"])
    assert "Final: posted as reply to line" not in " ".join(_labels(mid, question["id"]))
    client.post("/api/rooms/ubuntu/lines", json={"nick": "omar", "text": "still here"})
    release.set()
    worker.join(timeout=10)
    assert not worker.is_alive()
    done = held["page"].json()
    assert "Draft discarded. A later human message arrived before append." in _labels(done, question["id"])
    assert all(line["nick"] != "soma" for line in done["lines"])
