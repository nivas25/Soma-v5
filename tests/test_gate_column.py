"""The gate column is off until the Gate button. It lists stored tokens only."""

from __future__ import annotations

import json
import subprocess

from fastapi.testclient import TestClient

from soma_data.chat_app import create_app
from soma_data.config import ROOT
from soma_data.speak import DraftResult


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


def test_gate_column_stays_unmounted_until_the_button():
    clock = _Clock()

    def gate(_instruction: str, _user_input: str) -> str:
        return "speak now"

    app = create_app(
        gate=gate,
        reply=lambda _window, _person, _question: DraftResult("", "", ""),
        idle_s=4,
        clock=clock,
    )
    client = TestClient(app)
    client.timeout = None
    client.post("/api/join", json={"room": "ubuntu", "nick": "omar"})
    client.post("/api/join", json={"room": "ubuntu", "nick": "nina"})
    posted = client.post(
        "/api/rooms/ubuntu/lines",
        json={"nick": "omar", "text": "how do I check free disk space on ubuntu?"},
    )
    question = posted.json()["lines"][-1]
    clock.t += 4
    client.get("/api/rooms/ubuntu")
    fresh = client.post(
        "/api/rooms/ubuntu/lines",
        json={"nick": "nina", "text": "I will look it up"},
    )
    page = fresh.json()
    record = app.state.rooms["ubuntu"].results[question["id"]]
    assert record.token == "SPEAK"
    assert record.raw == "speak now"
    assert [row["line_id"] for row in page["gates"]] == [question["id"]]
    assert page["gates"][0]["token"] == record.token
    assert page["gates"][0]["input"] == record.payload

    script = r"""
import { readFileSync } from "node:fs"
import { Window } from "happy-dom"
import { createServer } from "vite"
import { fileURLToPath } from "node:url"
import react, { act } from "react"
import { createRoot } from "react-dom/client"

const state = JSON.parse(readFileSync(0, "utf8"))
const rootDir = fileURLToPath(new URL("./", import.meta.url))
const server = await createServer({
  root: rootDir,
  configFile: fileURLToPath(new URL("./vite.config.ts", import.meta.url)),
  server: { middlewareMode: true },
  appType: "custom",
  logLevel: "error",
})
try {
  const appMod = await server.ssrLoadModule("/src/App.tsx")
  const win = new Window()
  function assign(name, value) {
    try {
      Object.defineProperty(globalThis, name, { value, configurable: true, writable: true })
    } catch {
      // Node owns a few of these, such as navigator.
    }
  }
  assign("window", win)
  assign("document", win.document)
  assign("HTMLElement", win.HTMLElement)
  assign("Element", win.Element)
  assign("Node", win.Node)
  assign("DocumentFragment", win.DocumentFragment)
  assign("MutationObserver", win.MutationObserver)
  assign("ResizeObserver", win.ResizeObserver)
  assign("getComputedStyle", win.getComputedStyle.bind(win))
  assign("requestAnimationFrame", win.requestAnimationFrame.bind(win))
  assign("cancelAnimationFrame", win.cancelAnimationFrame.bind(win))
  assign("IS_REACT_ACT_ENVIRONMENT", true)
  const proto = win.HTMLElement.prototype
  if (!proto.hasPointerCapture) proto.hasPointerCapture = () => false
  if (!proto.setPointerCapture) proto.setPointerCapture = () => {}
  if (!proto.releasePointerCapture) proto.releasePointerCapture = () => {}
  if (!proto.scrollIntoView) proto.scrollIntoView = () => {}
  const container = win.document.createElement("div")
  document.body.appendChild(container)
  const root = createRoot(container)
  await act(async () => {
    root.render(react.createElement(appMod.RoomScreen, {
      state,
      draft: "",
      busy: false,
      error: "",
      onDraft() {},
      onSubmit(event) { event.preventDefault() },
      onTyping() {},
    }))
  })
  const main = container.querySelector("main")
  const first = { children: main.children.length, text: main.textContent }
  const button = [...container.querySelectorAll("button")].find((el) => el.textContent === "Gate")
  if (!button) throw new Error("Gate button missing")
  await act(async () => {
    button.click()
  })
  const column = main.children.length > 1 ? main.children[1].textContent : ""
  process.stdout.write(JSON.stringify({ first, column, children: main.children.length }))
} finally {
  await server.close()
}
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=str(ROOT / "web"),
        input=json.dumps(page),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    painted = json.loads(result.stdout)
    assert painted["first"]["children"] == 1
    assert record.token not in painted["first"]["text"]
    assert record.raw not in painted["first"]["text"]
    assert question["text"] in painted["first"]["text"]
    fresh_line = page["lines"][-1]
    assert fresh_line["text"] in painted["first"]["text"]
    assert painted["children"] == 2
    column = painted["column"]
    assert record.token in column
    assert record.raw in column
    assert record.payload in column
    assert f"{question['id']} {question['nick']}" in column
    assert f"{fresh_line['id']} {fresh_line['nick']}" not in column
