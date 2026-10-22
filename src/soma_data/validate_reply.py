"""Fail-closed check for a reply that is allowed to leave the gate.

A reply may quote a command only when that command is a substring of the
window. Denylisted commands are never emitted, including inside a quote.
"""

from __future__ import annotations

import re

_DENY = (
    re.compile(r"(?i)\brm\s+-[a-z]*r[a-z]*f\b|\brm\s+-(?:rf|fr)\b"),
    re.compile(r"(?i)\bmkfs(?:\.\w+)?\b"),
    re.compile(r"(?i)\bdd\s+if="),
    re.compile(r"(?i)\bchmod\s+0*777\b"),
    re.compile(r":\(\)\s*\{"),
    re.compile(r"(?i)\bshutdown\b"),
    re.compile(r"(?i)\b(?:curl|wget)\b[^|\n]{0,120}\|\s*(?:ba)?sh\b"),
    re.compile(r"(?i)\binit\s+[06]\b"),
    re.compile(r"(?i)\bkill\s+-9\s+-?1\b"),
)
_CMD = re.compile(
    r"(?i)(?:sudo\s+)*(?:aptitude|apt-get|apt|dpkg|chmod|chown|chgrp|addgroup|"
    r"delgroup|usermod|useradd|groupadd|mount|umount|systemctl|service|"
    r"mkfs(?:\.\w+)?|iptables|ufw|rm|dd)\b[^;&|\n`\"]*"
)

OPEN_REPLY = (
    "This ask is still open in the window. "
    "I am not adding a command that is not already in the chat."
)


def denied(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in _DENY)


def redact(text: str) -> str:
    out = text or ""
    for pattern in _DENY:
        out = pattern.sub("[blocked]", out)
    return out


def command_spans(text: str) -> list[str]:
    return [match.group(0).strip() for match in _CMD.finditer(text or "") if match.group(0).strip()]


def check_reply(chat: str, action: str, reply: str) -> tuple[bool, str]:
    """Return (ok, reason). SILENT must be empty. Every command must be in the window."""
    action = (action or "").upper()
    reply = reply or ""
    if action == "SILENT":
        if reply.strip():
            return False, "silent_must_be_empty"
        return True, ""
    if not reply.strip():
        return False, "speak_reply_empty"
    if denied(reply):
        return False, "denied_command"
    window = chat or ""
    for span in command_spans(reply):
        if span not in window:
            return False, "ungrounded_command"
    if reply == OPEN_REPLY and command_spans(reply):
        return False, "fallback_contains_command"
    return True, ""
