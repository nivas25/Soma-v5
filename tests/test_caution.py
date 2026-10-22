"""A risky request is posted with a caution. A normal disk question is not."""

from __future__ import annotations

from fastapi.testclient import TestClient

from soma_data.chat_app import create_app

ERASE = "how do I erase the whole disk including the root filesystem?"
DISK = "how do I check free disk space on ubuntu?"
DISK_DRAFT = "type `df -h` in the terminal"
CAUTION = "This will erase data. Be careful."


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


def _complete(prompt: str) -> str:
    if prompt.startswith("Does this reply contradict"):
        return '{"contradicts":"NO"}'
    question = ""
    marker = "Their open question is:\n"
    if marker in prompt:
        question = prompt.split(marker, 1)[1].split("\n", 1)[0]
    if question == ERASE:
        return '{"reply":"yes, `mkfs.ext4 /dev/sda1` is the correct command."}'
    return '{"reply":"type `df -h` in the terminal"}'


def test_erase_disk_posts_a_caution_and_df_is_unchanged():
    clock = _Clock()
    app = create_app(gate=lambda _instruction, _payload: "SPEAK", complete=_complete, idle_s=4, clock=clock)
    client = TestClient(app)
    client.timeout = None
    client.post("/api/join", json={"room": "ubuntu", "nick": "omar"})
    question = client.post("/api/rooms/ubuntu/lines", json={"nick": "omar", "text": ERASE}).json()["lines"][-1]
    clock.t += 4
    page = client.get("/api/rooms/ubuntu").json()
    soma = page["lines"][-1]
    assert soma["nick"] == "soma"
    assert soma["reply_to"] == question["id"]
    assert soma["text"].startswith(CAUTION)
    assert "mkfs.ext4 /dev/sda1" in soma["text"]
    assert soma["text"].index(CAUTION) < soma["text"].index("mkfs")
    assert soma["text"].strip() != "`mkfs.ext4 /dev/sda1`"
    assert soma["text"].strip() != "mkfs.ext4 /dev/sda1"

    disk = client.post("/api/rooms/ubuntu/lines", json={"nick": "omar", "text": DISK}).json()["lines"][-1]
    clock.t += 4
    later = client.get("/api/rooms/ubuntu").json()
    reply = next(line for line in later["lines"] if line["reply_to"] == disk["id"])
    assert reply["nick"] == "soma"
    assert reply["text"] == DISK_DRAFT
    assert CAUTION not in reply["text"]


def test_overlap_still_drops_a_repeated_dangerous_command():
    clock = _Clock()

    def gate(_instruction: str, payload: str) -> str:
        if "erase the whole disk" in payload.split("LAST:", 1)[-1]:
            return "SPEAK"
        return "SILENT"

    app = create_app(gate=gate, complete=_complete, idle_s=4, clock=clock)
    client = TestClient(app)
    client.timeout = None
    client.post("/api/join", json={"room": "ubuntu", "nick": "omar"})
    client.post(
        "/api/rooms/ubuntu/lines",
        json={"nick": "omar", "text": "I tried `mkfs.ext4 /dev/sda1` yesterday"},
    )
    clock.t += 4
    client.get("/api/rooms/ubuntu")
    question = client.post("/api/rooms/ubuntu/lines", json={"nick": "omar", "text": ERASE}).json()["lines"][-1]
    clock.t += 4
    page = client.get("/api/rooms/ubuntu").json()
    assert all(line["reply_to"] != question["id"] for line in page["lines"])
    assert all(line["nick"] != "soma" for line in page["lines"])
