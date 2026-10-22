"""Group-chat room.

A posted line is stored at once. When nobody is typing and the last human
line is at least SOMA_IDLE_S seconds old (default 4), the room calls the
deployed soma-gate once for that line. The token, raw text, and payload
stay on the room, keyed by line id. They are not fields on the chat line.
On SPEAK, soma-reply drafts one line. A passing draft is appended as a
line from soma that quotes the human line the gate ran on. If that line
is no longer the latest human line, or generation changed, the draft is
dropped and nothing is appended. The room view is that thread. A Gate
button mounts a second column listing each stored gate result. A new
human line or a typing post bumps generation and drops an in-flight
result. A restart clears every room.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from soma_data.config import ROOT, WINDOW_SIZE
from soma_data.parse_irc import extract_addressed_to, has_question, is_thanks
from soma_data.teacher_prompt_v2_2 import SFT_INSTRUCTION_V2_2, build_user_payload_v2_2

_NICK = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,19}$")
_ROOM = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,31}$")
_TYPING_S = 1.5


@dataclass
class ChatLine:
    id: int
    nick: str
    text: str
    reply_to: int | None = None


@dataclass
class GateRecord:
    """Off-thread gate result for one human line. `token` is None on failure."""

    token: str | None
    raw: str | None
    payload: str
    error: str | None


@dataclass
class Room:
    name: str
    members: set[str] = field(default_factory=set)
    lines: list[ChatLine] = field(default_factory=list)
    typing_until: dict[str, float] = field(default_factory=dict)
    last_activity: float | None = None
    next_id: int = 1
    generation: int = 0
    inflight: set[tuple[int, int]] = field(default_factory=set)
    settled: set[tuple[int, int]] = field(default_factory=set)
    results: dict[int, GateRecord] = field(default_factory=dict)
    drafts: dict[int, object] = field(default_factory=dict)
    stages: dict[int, list[dict[str, str]]] = field(default_factory=dict)


@dataclass
class _Job:
    room: Room
    key: tuple[int, int]
    instruction: str
    payload: str


class JoinIn(BaseModel):
    room: str
    nick: str


class LineIn(BaseModel):
    nick: str
    text: str = Field(min_length=1, max_length=500)


class TypingIn(BaseModel):
    nick: str
    typing: bool = True


def _nick(value: str) -> str:
    nick = (value or "").strip()
    if nick.lower() == "soma" or not _NICK.match(nick):
        raise HTTPException(400, "nick must start with a letter and is not soma")
    return nick


def _room_name(value: str) -> str:
    name = (value or "").strip()
    if not _ROOM.match(name):
        raise HTTPException(400, "room must start with a letter")
    return name


def _idle_seconds() -> float:
    raw = (os.environ.get("SOMA_IDLE_S") or "4").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 4.0


def _typing_nicks(room: Room, now: float) -> list[str]:
    return sorted(nick for nick, until in room.typing_until.items() if until > now)


def _is_idle(room: Room, now: float, idle_s: float) -> bool:
    human = any(line.nick != "soma" for line in room.lines)
    quiet = room.last_activity is not None and (now - room.last_activity) >= idle_s
    return not _typing_nicks(room, now) and human and quiet


def _latest_human(room: Room) -> ChatLine | None:
    for line in reversed(room.lines):
        if line.nick != "soma":
            return line
    return None


def _window(room: Room, last: ChatLine) -> list[ChatLine]:
    end = next(i for i, line in enumerate(room.lines) if line.id == last.id) + 1
    return room.lines[:end][-WINDOW_SIZE:]


def _row(room: Room, last: ChatLine) -> dict:
    window = _window(room, last)
    return {
        "window_id": f"room:{room.name}:{last.id}",
        "last_speaker": last.nick,
        "last_is_question": has_question(last.text),
        "last_is_thanks": is_thanks(last.text),
        "addressed_to": extract_addressed_to(last.text),
        "last_line": f"{last.nick}: {last.text}",
        "chat_block": "\n".join(f"{line.nick}: {line.text}" for line in window),
    }


def _token(raw: str) -> str:
    """Same mapping as _generate_labels: anything else is SILENT."""
    from soma_data.modal_lora import _parse_pred

    parsed = _parse_pred(raw)
    if parsed not in {"SPEAK", "SILENT"}:
        return "SILENT"
    return parsed


def _quiet_label(idle_s: float) -> str:
    shown = int(idle_s) if idle_s == int(idle_s) else idle_s
    return f"Idle reached (no typing, {shown}s quiet)."


def _add_stage(room: Room, line_id: int, label: str, detail: str = "") -> None:
    room.stages.setdefault(line_id, []).append({"label": label, "detail": detail})


def _gates(room: Room) -> list[dict]:
    rows: list[dict] = []
    for line in room.lines:
        if line.nick == "soma":
            continue
        record = room.results.get(line.id)
        stages = room.stages.get(line.id) or []
        if record is None and not stages:
            continue
        rows.append(
            {
                "line_id": line.id,
                "nick": line.nick,
                "token": None if record is None else record.token,
                "raw": None if record is None else record.raw,
                "input": "" if record is None else record.payload,
                "error": None if record is None else record.error,
                "stages": [dict(stage) for stage in stages],
            }
        )
    return rows


def _public(room: Room, now: float, idle_s: float) -> dict:
    return {
        "room": room.name,
        "members": sorted(room.members),
        "typing": _typing_nicks(room, now),
        "idle": _is_idle(room, now, idle_s),
        "lines": [
            {"id": line.id, "nick": line.nick, "text": line.text, "reply_to": line.reply_to}
            for line in room.lines
        ],
        "gates": _gates(room),
    }


def create_app(
    gate: Callable[[str, str], str] | None = None,
    reply: Callable[[str, str, str], object] | None = None,
    idle_s: float | None = None,
    clock: Callable[[], float] | None = None,
    complete: Callable[[str], str] | None = None,
) -> FastAPI:
    """`gate` receives the v2.2 instruction and payload and returns raw text.

    The default calls the deployed soma-gate class. A restart clears rooms.
    """
    rooms: dict[str, Room] = {}
    lock = threading.Lock()
    lock_idle = _idle_seconds() if idle_s is None else idle_s
    now = clock or time.time

    def live(instruction: str, user_input: str) -> str:
        from soma_data.modal_gate import gate_raw

        return gate_raw(instruction, user_input)

    call = gate if gate is not None else live
    app = FastAPI(title="SOMA chat", docs_url=None, redoc_url=None)
    app.state.gate = call
    app.state.rooms = rooms
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    def take(name: str) -> Room:
        room = rooms.get(name.lower())
        if room is None:
            raise HTTPException(404, "room not found")
        return room

    def touch(room: Room) -> None:
        room.last_activity = now()

    def bump(room: Room) -> None:
        room.generation += 1

    def claim(room: Room) -> _Job | None:
        with lock:
            if not _is_idle(room, now(), lock_idle):
                return None
            last = _latest_human(room)
            if last is None:
                return None
            key = (last.id, room.generation)
            if key in room.settled or key in room.inflight:
                return None
            payload = build_user_payload_v2_2(_row(room, last))
            _add_stage(room, last.id, _quiet_label(lock_idle))
            _add_stage(room, last.id, "Payload built (last 12 lines, flags).", payload)
            room.inflight.add(key)
            return _Job(room, key, SFT_INSTRUCTION_V2_2, payload)

    def store(job: _Job, raw: str | None, error: str | None) -> GateRecord | None:
        with lock:
            room = job.room
            room.inflight.discard(job.key)
            line_id, gen = job.key
            last = _latest_human(room)
            if room.generation != gen or last is None or last.id != line_id:
                if error is not None:
                    _add_stage(room, line_id, f"Gate call failed ({error}).", "Nothing was posted.")
                else:
                    _add_stage(room, line_id, f"Gate call returned {_token(raw or '')}.", raw or "")
                _add_stage(room, line_id, "Dropped. A later human message arrived.")
                return None
            room.settled.add(job.key)
            if error is not None:
                record = GateRecord(None, None, job.payload, error)
                _add_stage(room, line_id, f"Gate call failed ({error}).", "Nothing was posted.")
                _add_stage(room, line_id, f"Final: dropped ({error}).")
            else:
                token = _token(raw or "")
                record = GateRecord(token, raw or "", job.payload, None)
                _add_stage(room, line_id, f"Gate call returned {token}.", raw or "")
                if token != "SPEAK":
                    _add_stage(room, line_id, f"Final: dropped ({token}).")
            room.results[line_id] = record
            return record

    def draft_for(room: Room, line_id: int, gen: int) -> None:
        from soma_data.speak import checked_draft

        def trace(label: str, detail: str = "") -> None:
            with lock:
                _add_stage(room, line_id, label, detail)

        with lock:
            if line_id in room.drafts:
                return
            if room.generation != gen:
                _add_stage(room, line_id, "Dropped. A later human message arrived.")
                return
            last = _latest_human(room)
            if last is None or last.id != line_id:
                _add_stage(room, line_id, "Dropped. A later human message arrived.")
                return
            window = "\n".join(f"{line.nick}: {line.text}" for line in _window(room, last))
            person = last.nick
            question = last.text
            _add_stage(room, line_id, "Draft requested.")
        if reply is not None:
            result = reply(window, person, question)
        else:
            result = checked_draft(window, person, question, complete=complete, trace=trace)
        with lock:
            if room.generation != gen:
                _add_stage(room, line_id, "Draft discarded. A later human message arrived before append.")
                return
            last = _latest_human(room)
            if last is None or last.id != line_id:
                _add_stage(room, line_id, "Draft discarded. A later human message arrived before append.")
                return
            room.drafts[line_id] = result
            text = str(getattr(result, "text", "") or "")
            if not text:
                reason = str(getattr(result, "reason", "") or "empty")
                _add_stage(room, line_id, f"Final: dropped ({reason}).")
                return
            room.lines.append(ChatLine(room.next_id, "soma", text, line_id))
            room.next_id += 1
            _add_stage(room, line_id, f"Final: posted as reply to line {line_id}.")

    def respond(room: Room) -> dict:
        job = claim(room)
        if job is not None:
            raw: str | None = None
            error: str | None = None
            try:
                got = call(job.instruction, job.payload)
                raw = got if isinstance(got, str) else str(got)
            except Exception as exc:
                error = type(exc).__name__
                raw = None
            record = store(job, raw, error)
            if record is not None and record.error is None and record.token == "SPEAK":
                draft_for(room, job.key[0], job.key[1])
        with lock:
            return _public(room, now(), lock_idle)

    @app.post("/api/join")
    def join(body: JoinIn) -> dict:
        name = _room_name(body.room)
        nick = _nick(body.nick)
        with lock:
            room = rooms.get(name.lower())
            if room is None:
                room = Room(name=name)
                rooms[name.lower()] = room
            room.members.add(nick)
        return respond(room)

    @app.get("/api/rooms/{name}")
    def read_room(name: str) -> dict:
        with lock:
            room = take(_room_name(name))
        return respond(room)

    @app.post("/api/rooms/{name}/lines")
    def post_line(name: str, body: LineIn) -> dict:
        nick = _nick(body.nick)
        text = " ".join(body.text.split())
        if not text:
            raise HTTPException(400, "empty line")
        with lock:
            room = take(_room_name(name).lower())
            if nick not in room.members:
                raise HTTPException(403, "join the room first")
            room.lines.append(ChatLine(room.next_id, nick, text, None))
            room.next_id += 1
            bump(room)
            touch(room)
        return respond(room)

    @app.post("/api/rooms/{name}/typing")
    def set_typing(name: str, body: TypingIn) -> dict:
        nick = _nick(body.nick)
        with lock:
            room = take(_room_name(name).lower())
            if nick not in room.members:
                raise HTTPException(403, "join the room first")
            bump(room)
            touch(room)
            if body.typing:
                room.typing_until[nick] = now() + _TYPING_S
            else:
                room.typing_until.pop(nick, None)
        return respond(room)

    dist = ROOT / "web" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="ui")
    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8787, log_level="info")


if __name__ == "__main__":
    main()
