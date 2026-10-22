"""What to say after the gate has already said SPEAK.

The gate label is an input. This module does not retrain it and does not
flip SILENT into a reply. A draft is shown only after the three checks pass.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass

from soma_data.gemini_client import GeminiClient, GeminiError, parse_model_json
from soma_data.room_gate import open_question_line
from soma_data.speak_validate import (
    command_already_in_window,
    contradicts,
    docs_allow,
    draft_is_denied,
)

_NONE = "NONE"

_FIND = """You select one unanswered Ubuntu support question from an IRC window.
The SPEAK/SILENT gate already ran. Do not relabel it.

Lines are numbered. A question may sit on any line, not only the last.
Return NONE when any of these is true:
- there is no question
- the question is not about Ubuntu or Linux support
- a helper already owns it: someone else later gives steps, a command, or an explanation to the asker
- two helpers already disagree about the answer
- the line is thanks, a joke, small talk, or off-topic

Return JSON only, no markdown:
{"result":"NONE"}
or
{"result":"LINE","line":1,"text":"the exact window line, including the nick"}

WINDOW:
{window}
"""


def window_lines(window: str) -> list[str]:
    """Non-empty lines, capped at the last 12."""
    lines = [ln.strip() for ln in (window or "").splitlines() if ln.strip()]
    return lines[-12:]


def _format(lines: list[str]) -> str:
    return "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1))


def _align(lines: list[str], line_no: object, text: object) -> tuple[int, str] | None:
    quoted = str(text or "").strip()
    quoted = re.sub(r"^\d+\.\s+", "", quoted)
    if isinstance(line_no, int) or (isinstance(line_no, str) and str(line_no).isdigit()):
        number = int(line_no)
        if 1 <= number <= len(lines):
            candidate = lines[number - 1]
            if not quoted or quoted == candidate or quoted in candidate or candidate in quoted:
                return number, candidate
    if quoted:
        for index, line in enumerate(lines, 1):
            if quoted == line or quoted in line or line in quoted:
                return index, line
    return None


def find_unanswered(
    window: str,
    *,
    gate: str = "SPEAK",
    client: GeminiClient | None = None,
) -> str:
    """Return `NONE` or `<n>: <exact line>`.

    SILENT never calls the model. A bad model payload returns NONE.
    """
    if (gate or "").strip().upper() != "SPEAK":
        return _NONE
    lines = window_lines(window)
    if not lines:
        return _NONE
    model = client or GeminiClient()
    try:
        raw = model.complete(_FIND.replace("{window}", _format(lines)))
        payload = parse_model_json(raw)
    except (GeminiError, ValueError, TypeError):
        return _NONE
    result = str(payload.get("result") or "").strip().upper()
    if result != "LINE":
        return _NONE
    matched = _align(lines, payload.get("line"), payload.get("text"))
    if matched is None:
        return _NONE
    number, text = matched
    return f"{number}: {text}"


_DRAFT = """Draft ONE short IRC reply to the question on this line only.
LINE: {question}

Rules:
- Ubuntu or Linux support. One or two sentences. One line.
- Answer only that question.
- Do not repeat a command that already appears in the window.
- Do not contradict a fact the user stated or a helper line.
- If a helper already answered, or two helpers disagree, return NONE.
- If the question is not Ubuntu support, return NONE.

Return JSON only: {"reply":"the line"} or {"reply":"NONE"}

WINDOW:
{window}
"""


@dataclass(frozen=True)
class SpeakOutcome:
    gate: str
    question: str
    draft: str
    reply: str
    reason: str

    @property
    def shown(self) -> bool:
        return bool(self.reply)


_ONE = """You are SOMA in a group chat.
Write one or two short sentences answering this question:
{question}
Put one shell command in single backticks. Do not give a second command.
Do not repeat a command already written in the window.
JSON only: {"reply":"..."}

WINDOW:
{window}
"""


def draft_one(window: str, complete) -> str:
    """One model call for the open question. Empty string means stay quiet."""
    lines = window_lines(window)
    question = open_question_line(window)
    if not lines or not question:
        return ""
    prompt = _ONE.replace("{question}", question).replace("{window}", _format(lines))
    try:
        draft = _speakable(_reply_from_raw(complete(prompt)))
    except Exception as exc:
        print(f"soma draft skipped: {type(exc).__name__}", file=sys.stderr)
        return ""
    if not draft:
        return ""
    if draft_is_denied(draft):
        print("soma draft blocked: denied", file=sys.stderr)
        return ""
    if command_already_in_window(draft, window):
        print("soma draft blocked: overlap", file=sys.stderr)
        return ""
    return draft


def _clean_draft(text: str) -> str:
    line = " ".join((text or "").strip().split())
    line = re.sub(r"^(?:helper|bot|soma)\s*:\s*", "", line, flags=re.I)
    if not line or line.upper() == "NONE":
        return ""
    return line[:400]


_REPLY = """You are in a real Ubuntu support room. Reply to one person, as a person already in the room.

Reply only to {person}. Their open question is:
{question}

Rules:
- Answer only that question.
- One or two short sentences. If a command is needed, put that one command in single backticks inside the JSON string. No second command. No pipes. No lecture.
- Sound like a person in the room. No "Sure,". No "As an AI". No "Here's how."
- If the window already has a helper on that question, or two helpers disagree, output exactly {"reply":"NONE"}.
- If you are not sure the command is right, output exactly {"reply":"NONE"}.

WINDOW:
{window}

After you read the window, apply these in order:
- If two different people disagree with each other, output exactly {"reply":"NONE"}.
- If someone else already answered {person}'s question, output exactly {"reply":"NONE"}.
- If you are not sure the command is right, output exactly {"reply":"NONE"}.
- Otherwise answer only that question. One or two short sentences. One command in single backticks if one is needed. No second command. No pipes. No lecture. No "Sure,". No "As an AI". No "Here's how."

JSON only. No markdown. No code fence. The first character is {.
"""


@dataclass(frozen=True)
class DraftResult:
    """Checked reply. Empty `text` means nothing is stored."""

    text: str
    reason: str
    raw: str


class _Completer:
    def __init__(self, complete: Callable[[str], str]) -> None:
        self._complete = complete

    def complete(self, prompt: str) -> str:
        return self._complete(prompt)


def _modal_complete(prompt: str) -> str:
    from soma_data.modal_reply import modal_complete

    return modal_complete(prompt)


_CAUTION = "This will erase data. Be careful."
_DESTRUCTIVE_QUESTION = re.compile(
    r"(?i)("
    r"\berase\b.{0,60}\b(?:disk|drive|filesystem|partition|root)\b|"
    r"\bwipe\b.{0,60}\b(?:disk|drive|filesystem|partition|root)\b|"
    r"\bformat\b.{0,40}\b(?:disk|drive|root)\b|"
    r"\boverwrite\b.{0,40}\broot\b|"
    r"root filesystem|"
    r"whole disk"
    r")"
)


def _asks_destructive(question: str) -> bool:
    from soma_data.validate_reply import denied

    text = question or ""
    return denied(text) or _DESTRUCTIVE_QUESTION.search(text) is not None


def _cautioned(draft: str) -> str:
    """Caution first. A denied command may follow, never as the whole reply."""
    from soma_data.speak_validate import command_surfaces
    from soma_data.validate_reply import denied

    text = (draft or "").strip()
    if denied(text):
        surfaces = command_surfaces(text)
        if surfaces:
            return f"{_CAUTION} `{surfaces[0]}`"
        return _CAUTION
    if not text or text.lower().startswith("this will erase data"):
        return _CAUTION if not text else text
    return f"{_CAUTION} {text}"


def checked_draft(
    window: str,
    person: str,
    question: str,
    complete: Callable[[str], str] | None = None,
    trace: Callable[[str, str], None] | None = None,
) -> DraftResult:
    """Modal reply, then _clean_draft, denied, overlap, contradicts. No docs."""
    from soma_data.validate_reply import denied

    def mark(label: str, detail: str = "") -> None:
        if trace is not None:
            trace(label, detail)

    call = complete or _modal_complete
    prompt = (
        _REPLY.replace("{person}", person)
        .replace("{question}", question)
        .replace("{window}", _format(window_lines(window)))
    )
    try:
        raw = call(prompt)
    except Exception as exc:
        return DraftResult("", type(exc).__name__, "")
    raw = raw if isinstance(raw, str) else str(raw)
    try:
        payload = parse_model_json(raw)
    except (ValueError, TypeError):
        return DraftResult("", "not_json", raw)
    reply = str(payload.get("reply") or "").strip()
    if not reply or reply.upper() == "NONE":
        mark("Draft text, or NONE.", "NONE")
        if not _asks_destructive(question):
            return DraftResult("", "none", raw)
        cleaned = _cautioned("")
    else:
        mark("Draft text, or NONE.", reply)
        cleaned = _clean_draft(reply)
        if not cleaned:
            mark("clean: fail", "")
            if not _asks_destructive(question):
                return DraftResult("", "clean", raw)
            cleaned = _cautioned("")
        else:
            mark("clean: pass", "")
            if denied(cleaned) or _asks_destructive(question):
                cleaned = _cautioned(cleaned)
            else:
                mark("denied: pass", "")
    if command_already_in_window(cleaned, window):
        mark("overlap: fail", "")
        return DraftResult("", "overlap", raw)
    mark("overlap: pass", "")
    if contradicts(window, cleaned, _Completer(call)):
        mark("contradicts: fail", "")
        return DraftResult("", "contradicts", raw)
    mark("contradicts: pass", "")
    return DraftResult(cleaned, "", raw)


def _reply_from_raw(raw: str) -> str:
    """Prefer JSON. A short plain sentence still counts if the model skips JSON."""
    text = (raw or "").strip()
    try:
        payload = parse_model_json(text)
    except (ValueError, TypeError):
        if text.startswith("{") or "\n" in text:
            return ""
        return _clean_draft(text)
    return _clean_draft(str(payload.get("reply") or ""))


def _command_verbs() -> set[str]:
    from soma_data.speak_validate import _VERBS

    return {item.lower() for item in _VERBS}


def _clip_inner(inner: str) -> str:
    """Keep sudo plus the real command. Drop words the model stuffed in front."""
    tokens = [token for token in inner.replace("`", " ").split() if token]
    verbs = _command_verbs()
    for index, token in enumerate(tokens):
        if token.lower() == "sudo":
            continue
        if token.lower() in verbs:
            start = index - 1 if index > 0 and tokens[index - 1].lower() == "sudo" else index
            return " ".join(tokens[start:])
    return " ".join(tokens)


def _speakable(draft: str) -> str:
    """A bare command becomes a sentence. Fences and placeholder echoes are cleaned."""
    text = re.sub(r"`{2,}", "`", (draft or "").strip())
    text = re.sub(
        r"`([^`]*)`",
        lambda match: f"`{_clip_inner(match.group(1))}`" if match.group(1).strip() else match.group(0),
        text,
    )
    if text.lower() in {"the line", "...", "reply"} or not re.search(r"[A-Za-z0-9]", text):
        return ""
    text = re.split(r"\s+\bOR\b\s+", text, maxsplit=1, flags=re.I)[0].strip()
    bare = re.fullmatch(r"`([^`]+)`\.?", text.strip())
    if bare and bare.group(1).strip():
        return f"Run `{bare.group(1).strip()}`."
    return text


def compose_reply(
    window: str,
    *,
    gate: str = "SPEAK",
    client: GeminiClient | None = None,
    fetch=None,
) -> SpeakOutcome:
    """Draft one reply and silence it unless every check that runs has passed.

    `reply` is the only text that may be shown. `draft` is retained for tests.
    """
    label = (gate or "").strip().upper()
    if label != "SPEAK":
        return SpeakOutcome("SILENT", _NONE, "", "", "gate_silent")
    question = find_unanswered(window, gate="SPEAK", client=client)
    if question == _NONE:
        return SpeakOutcome("SPEAK", _NONE, "", "", "no_unanswered")
    model = client or GeminiClient()
    try:
        prompt = _DRAFT.replace("{question}", question).replace("{window}", _format(window_lines(window)))
        payload = parse_model_json(model.complete(prompt))
        draft = _clean_draft(str(payload.get("reply") or ""))
    except (GeminiError, ValueError, TypeError):
        return SpeakOutcome("SPEAK", question, "", "", "no_draft")
    if not draft:
        return SpeakOutcome("SPEAK", question, "", "", "no_draft")
    if draft_is_denied(draft):
        return SpeakOutcome("SPEAK", question, draft, "", "denied_command")
    if command_already_in_window(draft, window):
        return SpeakOutcome("SPEAK", question, draft, "", "command_in_window")
    if contradicts(window, draft, model):
        return SpeakOutcome("SPEAK", question, draft, "", "contradicts")
    if not docs_allow(draft, model, fetch=fetch):
        return SpeakOutcome("SPEAK", question, draft, "", "doc_unsupported")
    return SpeakOutcome("SPEAK", question, draft, draft, "")
