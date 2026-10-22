"""Thread-scoped command clashes inside one 12-line window.

Two commands in the same window are not a clash. Ubuntu IRC windows mix
threads. A clash requires the same addressee (or a shared package/path when
neither line names one) plus a real disagreement: different tools for the
same thing, opposite polarity, or the addressee saying the advice failed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from soma_data.teacher_prompt_v2_2 import nicks_in_chat, parse_chat_lines

_CMD = re.compile(
    r"(?i)(?P<surface>(?:sudo\s+)*(?P<verb>aptitude|apt-get|apt|dpkg|chmod|chown|chgrp|"
    r"addgroup|delgroup|usermod|useradd|groupadd|mount|umount|systemctl|service|"
    r"mkfs(?:\.\w+)?|iptables|ufw|rm|dd|strace|lspci|lsusb|uname|dmesg|lsmod|"
    r"modprobe|ifconfig|iwconfig|ping|lshw)\b(?P<args>[^;&|\n`\"]*))"
)
_NEG = re.compile(r"(?i)\b(don'?t|do not|never|avoid)\b")
_ASK = re.compile(
    r"(?i)^(can|could|how|what|which|should i|do i|anyone|is there|has anyone)\b"
)
_FAIL = re.compile(
    r"(?i)\b("
    r"didn'?t work|did not work|still broken|still fails?|still not|"
    r"no dice|not working|does(?:n'?t| not) work|no luck|nothing happens|"
    r"didn'?t accept|did not accept|hangs"
    r")\b"
)
_ACTION = re.compile(
    r"(?i)\b(install|remove|purge|hold|start|stop|enable|disable|add|delete|del)\b"
)
_OPPOSITE = {
    "install": "remove",
    "remove": "install",
    "purge": "install",
    "start": "stop",
    "stop": "start",
    "enable": "disable",
    "disable": "enable",
    "add": "delete",
    "delete": "add",
    "del": "add",
}
_STOP = frozenset(
    {
        "install",
        "remove",
        "purge",
        "update",
        "upgrade",
        "hold",
        "start",
        "stop",
        "enable",
        "disable",
        "the",
        "a",
        "an",
        "it",
        "to",
        "for",
        "with",
        "and",
        "or",
        "then",
        "just",
        "use",
        "try",
        "please",
        "package",
        "pack",
        "this",
        "that",
        "your",
        "you",
        "in",
        "on",
        "of",
        "from",
        "example",
    }
)


@dataclass(frozen=True)
class Proposal:
    speaker: str
    line: str
    surface: str
    verb: str
    action: str
    operands: frozenset[str]
    negative: bool
    group: str


@dataclass(frozen=True)
class Conflict:
    kind: str
    line_a: str
    line_b: str


def _stem(token: str) -> str:
    t = token.lower().strip(".,'\"`()[]")
    for suffix in (".deb", ".rpm"):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
    return t


def _operands(args: str) -> frozenset[str]:
    found: set[str] = set()
    for path in re.findall(r"/[A-Za-z0-9_./+-]+", args):
        found.add(path.lower())
    for raw in re.findall(r"[A-Za-z0-9][A-Za-z0-9+._:-]*", args):
        if raw.startswith("-"):
            continue
        stem = _stem(raw)
        if len(stem) < 2 or stem in _STOP or stem.isdigit():
            continue
        found.add(stem)
    return frozenset(found)


_DIAG = frozenset(
    {
        "strace",
        "lspci",
        "lsusb",
        "uname",
        "dmesg",
        "lsmod",
        "modprobe",
        "ifconfig",
        "iwconfig",
        "ping",
        "lshw",
    }
)
_BARE = frozenset({"uname", "dmesg", "lsmod", "lspci", "lsusb", "ifconfig", "lshw"})
_CLIP_ACTION = re.compile(
    r"(?i)^(install|remove|purge|update|upgrade|dist-upgrade|autoremove|search|"
    r"clean|check|configure|start|stop|restart|enable|disable|status)$"
)
_CLIP_FLAG = re.compile(r"(?i)^(?:-{1,2}[A-Za-z0-9][A-Za-z0-9-]*|if=\S+|of=\S+|bs=\S+|count=\S+)$")
_PKG = re.compile(r"(?i)^[A-Za-z0-9][A-Za-z0-9+._:^-]{0,48}$")


def _clip_args(verb: str, args: str) -> str | None:
    """Keep a command tail. Stop at the first ordinary English word.

    Returns "" for a legal bare command, None when this mention is prose.
    """
    tokens = [tok.strip("\"'`,") for tok in (args or "").split() if tok.strip("\"'`,")]
    if verb in _DIAG:
        if not tokens:
            return "" if verb in _BARE else None
        one = tokens[0]
        if _CLIP_FLAG.match(one) or one.startswith("/") or _PKG.match(one):
            return one
        return "" if verb in _BARE else None
    if verb in {"rm", "dd"} and re.search(r"(?i)-\w|\bif=|/[A-Za-z0-9]", args or "") is None:
        return None
    kept: list[str] = []
    seen_action = False
    for tok in tokens:
        if _CLIP_FLAG.match(tok) or tok.startswith("/") or re.match(r"^\d{3,4}$", tok):
            kept.append(tok)
            continue
        if _CLIP_ACTION.match(tok):
            kept.append(tok)
            seen_action = True
            continue
        if seen_action and _PKG.match(tok) and tok.lower() not in _STOP:
            kept.append(tok)
            continue
        break
    if not kept:
        return None
    return " ".join(kept)


def _exact(text: str, surface: str) -> str | None:
    idx = text.lower().find(surface.lower())
    if idx < 0:
        return None
    return text[idx : idx + len(surface)]


def _early(text: str, verb: str) -> bool:
    body = re.sub(r"^\S+[:,]\s+", "", text.strip())
    return bool(re.match(rf"(?i)(?:please\s+|try\s+|sudo\s+)*{re.escape(verb)}\b", body))


def _addressee(text: str, nicks: set[str]) -> str:
    match = re.match(r"^(\S+)[:,]\s+", text)
    if not match:
        return ""
    token = match.group(1)
    by_lower = {n.lower(): n for n in nicks}
    return by_lower.get(token.lower(), "")


def _is_ask(text: str) -> bool:
    body = re.sub(r"^\S+[:,]\s+", "", text.strip())
    if body.endswith("?"):
        return True
    return bool(_ASK.match(body))


def proposals(chat: str) -> list[Proposal]:
    nicks = nicks_in_chat(chat)
    out: list[Proposal] = []
    for speaker, text in parse_chat_lines(chat):
        if not speaker or _is_ask(text):
            continue
        group = _addressee(text, nicks).lower()
        for match in _CMD.finditer(text):
            verb = match.group("verb").lower()
            args = match.group("args") or ""
            if verb in _DIAG and not _early(text, verb):
                continue
            clipped = _clip_args(verb, args)
            if clipped is None:
                continue
            sudo = bool(re.search(r"(?i)sudo\s+$", text[max(0, match.start("verb") - 8) : match.start("verb")]))
            drafted = f"{'sudo ' if sudo else ''}{verb}" + (f" {clipped}" if clipped else "")
            surface = _exact(text, drafted)
            if surface is None:
                continue
            before = text[max(0, match.start() - 40) : match.start()]
            action_match = _ACTION.search(clipped)
            out.append(
                Proposal(
                    speaker=speaker,
                    line=f"{speaker}: {text}".strip(),
                    surface=surface,
                    verb=verb,
                    action=(action_match.group(1).lower() if action_match else ""),
                    operands=_operands(clipped),
                    negative=bool(_NEG.search(before)),
                    group=group,
                )
            )
    return out


def _same_thread(a: Proposal, b: Proposal) -> bool:
    if a.group and a.group == b.group:
        return True
    if not a.group and not b.group and (a.operands & b.operands):
        return True
    return False


def _clashes(a: Proposal, b: Proposal) -> str:
    if a.speaker.lower() == b.speaker.lower():
        return ""
    if not _same_thread(a, b):
        return ""
    shared = a.operands & b.operands
    if a.negative != b.negative and (shared or a.verb == b.verb):
        return "opposite"
    if shared and a.verb != b.verb:
        return "tool_clash"
    if shared and a.action and b.action and _OPPOSITE.get(a.action) == b.action:
        return "opposite"
    if a.verb == "chmod" and b.verb == "chmod" and shared and a.surface.lower() != b.surface.lower():
        return "tool_clash"
    return ""


def _failed_advice(chat: str, found: list[Proposal]) -> Conflict | None:
    nicks = nicks_in_chat(chat)
    lines = parse_chat_lines(chat)
    best: tuple[int, Conflict] | None = None
    for index, (speaker, text) in enumerate(lines):
        if not speaker or not _FAIL.search(text):
            continue
        for earlier in found:
            if earlier.speaker.lower() == speaker.lower():
                continue
            told_this_speaker = earlier.group == speaker.lower()
            answers_helper = _addressee(text, nicks).lower() == earlier.speaker.lower()
            if not told_this_speaker and not answers_helper:
                continue
            clash = Conflict("failed_advice", earlier.line, f"{speaker}: {text}".strip())
            if best is None or index >= best[0]:
                best = (index, clash)
    return best[1] if best else None


def find_conflict(chat: str) -> Conflict | None:
    found = proposals(chat)
    failed = _failed_advice(chat, found)
    best: tuple[int, Conflict] | None = None
    # Later line index is the order in `found`, which follows the window.
    line_at = {p.line: i for i, p in enumerate(found)}
    for i, left in enumerate(found):
        for right in found[i + 1 :]:
            kind = _clashes(left, right)
            if not kind:
                continue
            at = line_at.get(right.line, i)
            if best is None or at >= best[0]:
                best = (at, Conflict(kind, left.line, right.line))
    chosen = best[1] if best else None
    if failed is None:
        return chosen
    if chosen is None:
        return failed
    # The disagreement closest to the decision line wins.
    order = [ln.strip() for ln in chat.splitlines() if ln.strip()]

    def at(line: str) -> int:
        target = line.strip()
        for index, item in enumerate(order):
            if item == target:
                return index
        return -1

    return failed if at(failed.line_b) >= at(chosen.line_b) else chosen
