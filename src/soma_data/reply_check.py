"""Keep a generated IRC line only when it is about this window.

The model is allowed to name a command that was not typed in the chat.
That is the point of calling it. The line is dropped when it ignores the
window, or when it tells someone to run a destructive command.
"""

from __future__ import annotations

import re

_DENY = (
    re.compile(r"(?i)\brm\s+-[a-z]*r[a-z]*f\b|\brm\s+-(?:rf|fr)\b"),
    re.compile(r"(?i)\bmkfs(?:\.\w+)?\b"),
    re.compile(r"(?i)\bdd\s+if="),
    re.compile(r"(?i)\bchmod\s+0*777\b"),
    re.compile(r":\(\)\s*\{"),
    re.compile(r"(?i)\bshutdown\b|\breboot\b|\binit\s+[06]\b"),
    re.compile(r"(?i)\b(?:curl|wget)\b[^|\n]{0,120}\|\s*(?:ba)?sh\b"),
    re.compile(r"(?i)\bkill\s+-9\s+-?1\b"),
)
_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
        "you",
        "your",
        "have",
        "from",
        "what",
        "when",
        "where",
        "how",
        "can",
        "could",
        "would",
        "should",
        "just",
        "like",
        "its",
        "it's",
        "not",
        "but",
        "are",
        "was",
        "were",
        "has",
        "had",
        "does",
        "did",
        "any",
        "anyone",
        "about",
        "into",
        "than",
        "then",
        "them",
        "they",
        "there",
        "here",
        "please",
        "thanks",
        "thank",
        "hello",
        "help",
        "need",
        "know",
        "want",
        "something",
        "ubuntu",
    }
)
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9+._/-]{2,}")


def denied(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in _DENY)


def _words(text: str) -> set[str]:
    out = set()
    for raw in _WORD.findall(text or ""):
        word = raw.lower().strip(".,:;")
        if len(word) < 3 or word in _STOP:
            continue
        out.add(word)
    return out


def clean_draft(text: str) -> str:
    line = " ".join((text or "").strip().split())
    line = re.sub(r"^(?:helper|bot|soma)\s*:\s*", "", line, flags=re.I)
    if line.upper() in {"SPEAK", "SILENT"}:
        return ""
    return line[:500]


def check_generated(chat: str, last_line: str, draft: str, judge: str = "") -> tuple[bool, str, str]:
    """Return (keep, reason, cleaned).

    A destructive command is never kept. Otherwise the same model must have
    said RELEVANT. Word overlap is not required: "lsb_release -a" answers
    "which ubuntu version" without repeating those words.
    """
    cleaned = clean_draft(draft)
    if not cleaned:
        return False, "empty", ""
    if denied(cleaned):
        return False, "denied_command", ""
    label = (judge or "").strip().upper()
    if label.startswith("RELEVANT"):
        return True, "", cleaned
    if label.startswith("NOT"):
        return False, "not_about_this_chat", ""
    # No judge verdict yet. Do not ship the line.
    del chat, last_line
    return False, "no_judge", ""
