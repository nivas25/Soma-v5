"""Start or stop the SOMA room and both Modal apps.

  uv run python scripts/soma_ctl.py up
  uv run python scripts/soma_ctl.py down

`up` deploys soma-gate and soma-reply, calls each once so the GPU loads,
and starts the local room on port 8787 if it is not already running.
`down` stops both Modal apps and the local room process.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".soma"
PID_FILE = STATE / "chat.pid"
LOG_FILE = STATE / "chat.log"
PORT = 8787
URL = f"http://127.0.0.1:{PORT}/"
ADAPTER = ROOT / "models" / "soma-gate-lora-best" / "best_adapter" / "adapter_model.safetensors"

# Windows process-creation flags. DETACHED_PROCESS keeps the room alive
# after this script exits.
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_DETACHED_PROCESS = 0x00000008
_CREATE_NO_WINDOW = 0x08000000


def _say(text: str) -> None:
    print(text, flush=True)


def _run(args: list[str]) -> int:
    _say("+ " + " ".join(args))
    completed = subprocess.run(args, cwd=ROOT)
    return int(completed.returncode)


def _powershell(script: str) -> str:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return (completed.stdout or "").strip()


def _listening_pids() -> list[int]:
    raw = _powershell(
        f"(Get-NetTCPConnection -LocalPort {PORT} -State Listen "
        "-ErrorAction SilentlyContinue).OwningProcess"
    )
    found: list[int] = []
    for part in raw.replace(",", " ").split():
        if part.isdigit():
            found.append(int(part))
    return sorted(set(found))


def _command_line(pid: int) -> str:
    return _powershell(
        f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"
    )


def _parent_pid(pid: int) -> int | None:
    raw = _powershell(
        f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").ParentProcessId"
    )
    return int(raw) if raw.isdigit() else None


def _is_chat(command: str) -> bool:
    text = command.lower().replace("\\", "/")
    return "soma_data.chat_app" in text or "soma_data/chat_app" in text


def _chat_pids() -> list[int]:
    """Listener and its parent when either command line is the room server."""
    pids: list[int] = []
    for pid in _listening_pids():
        command = _command_line(pid)
        parent = _parent_pid(pid)
        parent_command = _command_line(parent) if parent else ""
        if _is_chat(command) or _is_chat(parent_command):
            if parent and _is_chat(parent_command):
                pids.append(parent)
            pids.append(pid)
    if PID_FILE.is_file():
        raw = PID_FILE.read_text(encoding="utf-8").strip()
        if raw.isdigit():
            pids.append(int(raw))
    return sorted(set(pids))


def _kill(pid: int) -> None:
    _say(f"stop pid {pid}")
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def _page_ok() -> bool:
    try:
        with urllib.request.urlopen(URL, timeout=3) as response:
            return int(response.status) == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _wait_for_page(seconds: float = 30) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if _page_ok():
            return True
        time.sleep(0.5)
    return False


def _require_adapter() -> None:
    if not ADAPTER.is_file():
        raise SystemExit(
            "Missing gate adapter. Expected "
            f"{ADAPTER}. soma-gate cannot deploy without it."
        )


def _build_page() -> None:
    index = ROOT / "web" / "dist" / "index.html"
    if index.is_file():
        _say(f"page already built: {index}")
        return
    _say("web/dist is missing. Building the page.")
    code = subprocess.run(
        ["npm", "run", "build"],
        cwd=ROOT / "web",
    ).returncode
    if code != 0 or not index.is_file():
        raise SystemExit("npm run build did not write web/dist/index.html")


def _deploy() -> None:
    code = _run([sys.executable, "-m", "modal", "deploy", "src/soma_data/modal_gate.py"])
    if code != 0:
        raise SystemExit(code)
    code = _run([sys.executable, "-m", "modal", "deploy", "src/soma_data/modal_reply.py"])
    if code != 0:
        raise SystemExit(code)


def _warm() -> None:
    """One real call to each app. This does not post into the room."""
    _say("warming soma-gate")
    from soma_data.modal_gate import gate_raw
    from soma_data.teacher_prompt_v2_2 import SFT_INSTRUCTION_V2_2

    payload = (
        "WINDOW_ID: room:ubuntu:0\n"
        "last_speaker=nivas question=yes thanks=no addressed_to=none\n"
        "helper_in_window=no\n"
        "LAST: nivas: how do I check free disk space on ubuntu?\n"
        "\n"
        "CHAT:\n"
        "nivas: how do I check free disk space on ubuntu?\n"
        "\n"
        "Decide AFTER the last line. JSON only."
    )
    raw = gate_raw(SFT_INSTRUCTION_V2_2, payload)
    _say(f"gate warm returned: {raw!r}")

    _say("warming soma-reply")
    from soma_data.modal_reply import modal_complete

    reply = modal_complete(
        'Their open question is:\nhow do I check free disk space on ubuntu?\n'
        'Answer with one JSON object: {"reply":"warm"}'
    )
    _say(f"reply warm returned: {reply!r}")


def _start_server() -> None:
    existing = _chat_pids()
    if existing and _page_ok():
        _say(
            "room server is already listening on "
            f"{URL} (pid {existing[-1]}). Leaving it running so the room stays."
        )
        return
    if _listening_pids() and not existing:
        raise SystemExit(
            f"port {PORT} is in use by a process that is not soma_data.chat_app. "
            "Stop that process, then run up again."
        )
    STATE.mkdir(parents=True, exist_ok=True)
    log = LOG_FILE.open("ab")
    flags = 0
    if os.name == "nt":
        flags = _CREATE_NEW_PROCESS_GROUP | _DETACHED_PROCESS | _CREATE_NO_WINDOW
    _say("starting room server")
    proc = subprocess.Popen(
        [sys.executable, "-m", "soma_data.chat_app"],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        close_fds=True,
    )
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    _say(f"room pid {proc.pid} log {LOG_FILE}")
    if not _wait_for_page():
        raise SystemExit(f"room server did not answer {URL}. See {LOG_FILE}")


def up() -> None:
    _require_adapter()
    _build_page()
    _deploy()
    _warm()
    _start_server()
    if not _page_ok():
        raise SystemExit(f"{URL} did not return 200")
    _say("")
    _say(f"SOMA is up: {URL}")
    _say("Join room ubuntu. Any nick except soma.")
    _say("Stop everything: uv run python scripts/soma_ctl.py down")


def down() -> None:
    gate = _run([sys.executable, "-m", "modal", "app", "stop", "soma-gate", "-y"])
    reply = _run([sys.executable, "-m", "modal", "app", "stop", "soma-reply", "-y"])
    for pid in _chat_pids():
        _kill(pid)
    if PID_FILE.is_file():
        PID_FILE.unlink()
    time.sleep(1)
    if _page_ok() or _listening_pids():
        raise SystemExit(f"port {PORT} is still answering. Not all chat processes stopped.")
    if gate != 0 or reply != 0:
        raise SystemExit("Modal stop returned a non-zero status. See the lines above.")
    _say("SOMA is stopped. Modal apps soma-gate and soma-reply are stopped, and port 8787 is free.")
    _say("The in-memory room is cleared.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start or stop SOMA.")
    parser.add_argument("action", choices=("up", "down"))
    args = parser.parse_args()
    if args.action == "up":
        up()
    else:
        down()


if __name__ == "__main__":
    main()
