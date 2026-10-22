"""A passing draft is one soma line. A newer human line drops it."""

from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from soma_data.chat_app import create_app
from soma_data.config import ROOT
from soma_data.speak import DraftResult


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


def _app(clock: _Clock, reply):
    def gate(_instruction: str, _user_input: str) -> str:
        return "SPEAK"

    app = create_app(gate=gate, reply=reply, idle_s=4, clock=clock)
    client = TestClient(app)
    client.timeout = None
    return app, client


def test_passing_reply_is_a_soma_line_quoting_the_question():
    draft = "type `df -h` in the terminal"
    clock = _Clock()
    _app_obj, client = _app(clock, lambda _window, _person, _question: DraftResult(draft, "", draft))
    client.post("/api/join", json={"room": "ubuntu", "nick": "omar"})
    posted = client.post(
        "/api/rooms/ubuntu/lines",
        json={"nick": "omar", "text": "how do I check free disk space on ubuntu?"},
    )
    question = posted.json()["lines"][-1]
    clock.t += 4
    page = client.get("/api/rooms/ubuntu")
    assert page.status_code == 200
    lines = page.json()["lines"]
    assert [line["nick"] for line in lines] == ["omar", "soma"]
    soma = lines[1]
    assert soma["reply_to"] == question["id"]
    assert soma["text"] == draft
    assert set(soma) == {"id", "nick", "text", "reply_to"}
    again = client.get("/api/rooms/ubuntu")
    assert [line["nick"] for line in again.json()["lines"]] == ["omar", "soma"]
    assert _app_obj.state.rooms["ubuntu"].drafts[question["id"]].text == draft


def test_human_message_after_speak_and_before_append_adds_no_soma_line():
    clock = _Clock()
    started = threading.Event()
    release = threading.Event()

    def reply(_window: str, _person: str, _question: str) -> DraftResult:
        started.set()
        assert release.wait(timeout=10)
        return DraftResult("type `df -h` in the terminal", "", "")

    app, client = _app(clock, reply)
    client.post("/api/join", json={"room": "ubuntu", "nick": "omar"})
    client.post(
        "/api/rooms/ubuntu/lines",
        json={"nick": "omar", "text": "how do I check free disk space on ubuntu?"},
    )
    clock.t += 4
    held: dict[str, object] = {}

    def fetch() -> None:
        other = TestClient(app)
        other.timeout = None
        held["page"] = other.get("/api/rooms/ubuntu")

    worker = threading.Thread(target=fetch)
    worker.start()
    assert started.wait(timeout=10)
    posted = client.post("/api/rooms/ubuntu/lines", json={"nick": "omar", "text": "still here"})
    assert posted.status_code == 200
    release.set()
    worker.join(timeout=10)
    assert not worker.is_alive()
    page = held["page"]
    assert page.status_code == 200
    lines = page.json()["lines"]
    assert [line["text"] for line in lines] == [
        "how do I check free disk space on ubuntu?",
        "still here",
    ]
    assert all(line["nick"] != "soma" for line in lines)
    assert app.state.rooms["ubuntu"].drafts == {}


def test_built_soma_line_does_not_contain_gate_labels():
    import subprocess

    script = r"""
import { createServer } from "vite"
import react from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { fileURLToPath } from "node:url"

const root = fileURLToPath(new URL("./", import.meta.url))
const server = await createServer({
  root,
  configFile: fileURLToPath(new URL("./vite.config.ts", import.meta.url)),
  server: { middlewareMode: true },
  appType: "custom",
  logLevel: "error",
})
try {
  const mod = await server.ssrLoadModule("/src/LineRow.tsx")
  const lines = [
    { id: 1, nick: "omar", text: "how do I check free disk space on ubuntu?", reply_to: null },
    { id: 2, nick: "soma", text: "type `df -h` in the terminal", reply_to: 1 },
  ]
  const html = renderToStaticMarkup(react.createElement(mod.LineRow, { line: lines[1], lines }))
  process.stdout.write(html)
} finally {
  await server.close()
}
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=str(ROOT / "web"),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    html = result.stdout
    assert "SOMA" in html
    assert "how do I check free disk space on ubuntu?" in html
    assert "type `df -h` in the terminal" in html
    assert "bg-[#e4eee8]" in html
    assert "border-l-2" in html
    assert "SPEAK" not in html
    assert "SILENT" not in html
    assert "bg-black" not in html
