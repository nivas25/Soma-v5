"""Local SPEAK/SILENT decision for the group-chat room.

This runs in the chat process on this machine. It does not call Modal and it
does not load the frozen LoRA. It follows the shipped v2.2 idea: an open
Ubuntu or Linux how-to with no helper yet. Typos like "persmision" still count.
"""

from __future__ import annotations

import re

from soma_data.parse_irc import is_thanks
from soma_data.speak_validate import command_surfaces

_GREET = re.compile(r"(?i)^(hi|hey|hello|yo|wb|sup|hola)[.!]*$")
_ASK = re.compile(
    r"(?i)(\?|\b(?:how|what|why|where|which|can|could|does|do i|anyone|is there|has anyone)\b)"
)
_SUPPORT = re.compile(
    r"(?i)\b(?:ubuntu|linux|debian|apt(?:-get)?|aptitude|nginx|version|disk|boot|"
    r"wifi|wi-fi|driver|package|partition|sudo|permissions?|install|release|grub|"
    r"kernel|folders?|director(?:y|ies)|files?|groups?|owners?|commands?|"
    r"chmod|chown|chgrp|error|terminal)\b"
)
_FOLLOW = re.compile(r"(?i)\b(?:what to do|what next|any commands?|what commands?|what should)\b")
_ANSWER = re.compile(
    r"(?i)\b(?:sudo|apt-get|aptitude|apt|chmod|chown|chgrp|df|lsb_release|because|try|run)\b"
)
_TYPOS = (
    ("persmisions", "permissions"),
    ("persmision", "permission"),
    ("permisions", "permissions"),
    ("permision", "permission"),
    ("permisson", "permission"),
    ("commmand", "command"),
    ("comand", "command"),
    ("ubunut", "ubuntu"),
    ("ubunto", "ubuntu"),
)


def _norm(text: str) -> str:
    out = (text or "").lower()
    for bad, good in _TYPOS:
        out = out.replace(bad, good)
    return out


def _split(line: str) -> tuple[str, str]:
    if ":" not in line:
        return "", line.strip()
    nick, body = line.split(":", 1)
    return nick.strip(), body.strip()


def _support_ask(body: str) -> bool:
    text = _norm(body).strip()
    if not text or _GREET.match(text):
        return False
    return bool(_ASK.search(text) and _SUPPORT.search(text))


def _open_support(lines: list[str], before: int) -> bool:
    """True when a how-to before `before` still has no helper after it."""
    target: int | None = None
    for index, line in enumerate(lines[:before]):
        speaker, body = _split(line)
        if speaker.lower() == "soma":
            continue
        if _support_ask(body):
            target = index
    if target is None:
        return False
    asker, _body = _split(lines[target])
    for line in lines[target + 1 : before]:
        speaker, body = _split(line)
        if not speaker or speaker.lower() in {asker.lower(), ""}:
            continue
        if speaker.lower() == "soma" or _ANSWER.search(_norm(body)):
            return False
    return True


def is_human_answer(body: str) -> bool:
    """A later line from someone else that already helps. Greetings do not count."""
    text = _norm(body).strip()
    if not text or _GREET.match(text) or _support_ask(body):
        return False
    return bool(command_surfaces(text) or _ANSWER.search(text))


def _lines(chat: str) -> list[str]:
    return [ln.strip() for ln in (chat or "").splitlines() if ln.strip()][-12:]


def _latest_open(lines: list[str]) -> int | None:
    """Index of the latest support ask that nobody has answered yet."""
    target: int | None = None
    for index, line in enumerate(lines):
        speaker, body = _split(line)
        if speaker.lower() == "soma":
            continue
        if _support_ask(body):
            target = index
    if target is None:
        return None
    asker, _body = _split(lines[target])
    for line in lines[target + 1 :]:
        speaker, body = _split(line)
        if not speaker or speaker.lower() == asker.lower():
            continue
        if speaker.lower() == "soma" or is_human_answer(body):
            return None
    return target


def question_still_open(chat: str) -> bool:
    """True when the latest support question has no human or SOMA answer after it."""
    return _latest_open(_lines(chat)) is not None


def open_question_line(chat: str) -> str:
    """The latest unanswered support line, nick included. Empty when none is open."""
    lines = _lines(chat)
    index = _latest_open(lines)
    if index is None:
        return ""
    return lines[index]


def room_gate(chat: str) -> str:
    """Return SPEAK or SILENT. SILENT is the default."""
    lines = [ln.strip() for ln in (chat or "").splitlines() if ln.strip()][-12:]
    if not lines:
        return "SILENT"
    _speaker, last_body = _split(lines[-1])
    if is_thanks(last_body) or _GREET.match(_norm(last_body).strip()):
        return "SILENT"
    asking = _support_ask(last_body) or (_FOLLOW.search(_norm(last_body)) and _open_support(lines, len(lines) - 1))
    if not asking:
        return "SILENT"
    # The last line is the ask. A helper after it would be a later line, which
    # cannot exist yet. Earlier soma lines do not close a new question.
    return "SPEAK"
