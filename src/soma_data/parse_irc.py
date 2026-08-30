"""Parse Ubuntu IRC / Kummerfeld `raw` lines into structured messages.

Log conventions (irclogs.ubuntu.com, 2004–2018, matching this corpus):

    [HH:MM] <nick> message text
    === nick [ident@host]  has joined #ubuntu
    === nick [ident@host]  has left #ubuntu ["reason"]
    === nick [ident@host]  has quit [reason]
    === nick is now known as newnick
    === nick action text          # CTCP ACTION /me  (NOT system)
    [HH:MM] * nick action text    # less common action form

`is_system` is JOIN / PART / QUIT / NICK / KICK / MODE / TOPIC only.
`/me` actions stay in the chat stream (they are turns, not presence events).
"""

from __future__ import annotations

from typing import Any

import regex as re
from pydantic import BaseModel, Field, field_validator

try:
    from pandas import isna as pd_isna
except ImportError:  # pragma: no cover
    def pd_isna(value: Any) -> bool:
        return False

# RFC 2812-ish nick class, plus the address-pattern the spec froze.
NICK_CLASS = r"[A-Za-z0-9_\-\[\]\\^{}|`]+"

PRIVMSG_RE = re.compile(
    r"^\[(?P<time>\d{2}:\d{2})\]\s+<(?P<nick>[^>]+)>\s?(?P<text>.*)$"
)
ACTION_STAR_RE = re.compile(
    r"^\[(?P<time>\d{2}:\d{2})\]\s+\*\s+(?P<nick>\S+)\s+(?P<text>.*)$"
)
ACTION_STAR_NOTIME_RE = re.compile(r"^\*\s+(?P<nick>\S+)\s+(?P<text>.*)$")

# Hostmask JOIN/PART/QUIT. Extra spaces after ] are common in ubuntu logger.
SYSTEM_HOST_RE = re.compile(
    r"^===\s+(?P<nick>\S+)\s+\[(?P<host>[^\]]*)\]\s+"
    r"has\s+(?P<event>joined|left|quit)\b.*$",
    re.IGNORECASE,
)
SYSTEM_NOHOST_RE = re.compile(
    r"^===\s+(?P<nick>\S+)\s+has\s+(?P<event>joined|left|quit)\b.*$",
    re.IGNORECASE,
)
SYSTEM_NICKCHANGE_RE = re.compile(
    r"^===\s+(?P<nick>\S+)\s+is now known as\s+(?P<new>\S+)\s*$",
    re.IGNORECASE,
)
SYSTEM_KICK_RE = re.compile(
    r"^===\s+.*\b(kicked|has kicked)\b.*$",
    re.IGNORECASE,
)
SYSTEM_MODE_TOPIC_RE = re.compile(
    r"^===\s+.*("
    r"changed the topic|set the topic|sets mode|has set the topic|"
    r"gives .+ status|brings voice|removes voice|channel operator|"
    r"topic for #"
    r").*$",
    re.IGNORECASE,
)
EQUALS_LINE_RE = re.compile(r"^===\s+(?P<nick>\S+)\s+(?P<text>.*)$")

# Elsner/Charniak #linux logger (channel_two) + Ubuntu ChanServ mode lines.
SYSTEM_ENTERED_RE = re.compile(
    r"^===\s+(?P<nick>\S+)\s+entered the room\.?\s*$",
    re.IGNORECASE,
)
SYSTEM_LEFT_ROOM_RE = re.compile(
    r"^===\s+(?P<nick>\S+)\s+left the room\b.*$",
    re.IGNORECASE,
)
SYSTEM_MODE_LINE_RE = re.compile(r"^===\s+mode/", re.IGNORECASE)

# IRC NOTICE (spam and bot notices in ubuntu logs):
#   [HH:MM] (nick/#channel) text
#   [HH:MM] -nick:#channel- text
NOTICE_PAREN_RE = re.compile(
    r"^\[(?P<time>\d{2}:\d{2})\]\s+\((?P<nick>[^/#]+)/#[^)]+\)\s?(?P<text>.*)$"
)
NOTICE_DASH_RE = re.compile(
    r"^\[(?P<time>\d{2}:\d{2})\]\s+-(?P<nick>[^:]+):#[^-]+-\s?(?P<text>.*)$"
)

# Spec: ^([A-Za-z0-9_\-\[\]\\^{}|`]+):  — we additionally reject `http://` etc.
ADDRESS_RE = re.compile(rf"^({NICK_CLASS}):(?!/)")

THANKS_RE = re.compile(r"thanks|thx|works now|fixed|solved", re.IGNORECASE)


class ParsedIrcMessage(BaseModel):
    """One IRC line after regex parse. Gold SPEAK/SILENT is not a field."""

    config: str
    split: str
    date: str
    original_id: int
    raw: str
    ascii: str | None = None
    tokenized: str | None = None
    connections: list[int] = Field(default_factory=list)
    time_hhmm: str | None = None
    speaker: str | None = None
    text: str = ""
    is_system: bool = False
    is_action: bool = False
    addressed_to: str | None = None
    has_question: bool = False
    parse_ok: bool = True
    row_idx: int = 0
    slice_id: int = 0
    run_id: int = 0

    @field_validator("connections", mode="before")
    @classmethod
    def _coerce_connections(cls, value: Any) -> list[int]:
        return _as_int_list(value)

    @field_validator("addressed_to", "speaker", "time_hhmm", "ascii", "tokenized", mode="before")
    @classmethod
    def _nan_to_none(cls, value: Any) -> Any:
        if value is None:
            return None
        try:
            if value != value:  # NaN
                return None
        except Exception:
            pass
        if isinstance(value, float) and pd_isna(value):
            return None
        return value

    def display_line(self) -> str:
        """One labelling-UI line: `Nick: text` (or `* nick action`)."""
        nick = self.speaker or "UNKNOWN"
        if self.is_action:
            body = self.text.strip()
            return f"* {nick} {body}".rstrip()
        return f"{nick}: {self.text}"


def extract_addressed_to(text: str) -> str | None:
    if not text:
        return None
    m = ADDRESS_RE.match(text)
    if not m:
        return None
    nick = m.group(1)
    # Guard: `http:`, `ftp:`, `C:` drive paths are not IRC addressing.
    if nick.lower() in {"http", "https", "ftp", "ftps", "file", "irc"}:
        return None
    if len(nick) == 1 and nick.isalpha() and (len(text) > 2 and text[1] == ":"):
        # Single-letter + colon is usually a drive / ratio, not a nick.
        rest = text[2:]
        if rest.startswith("\\") or rest.startswith("/") or (rest and rest[0].isdigit()):
            return None
    return nick


def has_question(text: str) -> bool:
    return "?" in (text or "")


def is_thanks(text: str) -> bool:
    return bool(THANKS_RE.search(text or ""))


def _system_match(raw: str) -> tuple[bool, str | None, str]:
    """Return (is_system, speaker, text) for === lines that are presence/meta."""
    m = SYSTEM_HOST_RE.match(raw)
    if m:
        return True, m.group("nick"), raw
    m = SYSTEM_NICKCHANGE_RE.match(raw)
    if m:
        return True, m.group("nick"), raw
    m = SYSTEM_NOHOST_RE.match(raw)
    if m:
        return True, m.group("nick"), raw
    m = SYSTEM_ENTERED_RE.match(raw)
    if m:
        return True, m.group("nick"), raw
    m = SYSTEM_LEFT_ROOM_RE.match(raw)
    if m:
        return True, m.group("nick"), raw
    if SYSTEM_MODE_LINE_RE.match(raw) or SYSTEM_KICK_RE.match(raw) or SYSTEM_MODE_TOPIC_RE.match(raw):
        m2 = EQUALS_LINE_RE.match(raw)
        return True, (m2.group("nick") if m2 else None), raw
    return False, None, raw


def parse_raw_line(raw: str | None) -> dict[str, Any]:
    """Parse a single `raw` field. Never raises on junk; sets parse_ok=False."""
    original = raw if raw is not None else ""
    line = original.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    # Ubuntu logs sometimes pad a space before "has joined".
    stripped = line.strip()

    empty = {
        "time_hhmm": None,
        "speaker": None,
        "text": stripped,
        "is_system": False,
        "is_action": False,
        "addressed_to": None,
        "has_question": False,
        "parse_ok": False,
    }
    if not stripped:
        empty["is_system"] = True  # blank log line: keep id for runs, drop from windows
        return empty

    m = NOTICE_PAREN_RE.match(stripped) or NOTICE_DASH_RE.match(stripped)
    if m:
        text = m.group("text") or ""
        return {
            "time_hhmm": m.group("time"),
            "speaker": m.group("nick"),
            "text": text,
            "is_system": True,
            "is_action": False,
            "addressed_to": None,
            "has_question": has_question(text),
            "parse_ok": True,
        }

    m = PRIVMSG_RE.match(stripped)
    if m:
        text = m.group("text") or ""
        return {
            "time_hhmm": m.group("time"),
            "speaker": m.group("nick"),
            "text": text,
            "is_system": False,
            "is_action": False,
            "addressed_to": extract_addressed_to(text),
            "has_question": has_question(text),
            "parse_ok": True,
        }

    m = ACTION_STAR_RE.match(stripped)
    if m:
        text = m.group("text") or ""
        return {
            "time_hhmm": m.group("time"),
            "speaker": m.group("nick"),
            "text": text,
            "is_system": False,
            "is_action": True,
            "addressed_to": extract_addressed_to(text),
            "has_question": has_question(text),
            "parse_ok": True,
        }

    if stripped.startswith("==="):
        is_sys, speaker, text = _system_match(stripped)
        if is_sys:
            return {
                "time_hhmm": None,
                "speaker": speaker,
                "text": text,
                "is_system": True,
                "is_action": False,
                "addressed_to": None,
                "has_question": False,
                "parse_ok": True,
            }
        m = EQUALS_LINE_RE.match(stripped)
        if m:
            text = m.group("text") or ""
            return {
                "time_hhmm": None,
                "speaker": m.group("nick"),
                "text": text,
                "is_system": False,
                "is_action": True,
                "addressed_to": extract_addressed_to(text),
                "has_question": has_question(text),
                "parse_ok": True,
            }
        return {
            "time_hhmm": None,
            "speaker": None,
            "text": stripped,
            "is_system": True,
            "is_action": False,
            "addressed_to": None,
            "has_question": False,
            "parse_ok": False,
        }

    m = ACTION_STAR_NOTIME_RE.match(stripped)
    if m:
        text = m.group("text") or ""
        return {
            "time_hhmm": None,
            "speaker": m.group("nick"),
            "text": text,
            "is_system": False,
            "is_action": True,
            "addressed_to": extract_addressed_to(text),
            "has_question": has_question(text),
            "parse_ok": True,
        }

    # Fallback: keep the line, mark parse failure.
    return {
        "time_hhmm": None,
        "speaker": None,
        "text": stripped,
        "is_system": False,
        "is_action": False,
        "addressed_to": None,
        "has_question": has_question(stripped),
        "parse_ok": False,
    }


def parse_hub_row(
    row: dict[str, Any],
    *,
    config: str,
    split: str,
    date: str,
    row_idx: int = 0,
) -> ParsedIrcMessage:
    parsed = parse_raw_line(row.get("raw"))
    connections = _as_int_list(row.get("connections"))
    return ParsedIrcMessage(
        config=config,
        split=split,
        date=date,
        original_id=int(row["id"]),
        raw=row.get("raw") or "",
        ascii=row.get("ascii"),
        tokenized=row.get("tokenized"),
        connections=connections,
        row_idx=row_idx,
        **parsed,
    )


def _as_int_list(value: Any) -> list[int]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    try:
        return [int(x) for x in list(value)]
    except TypeError:
        return []
