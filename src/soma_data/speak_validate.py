"""Three checks for a draft reply. Any failure forces silence.

(a) string overlap — the command already appears in the window.
(b) one model call — does the reply contradict a user fact or a helper line?
(c) optional — an official Ubuntu man-page snippet must support the command.
    Skipped only when no snippet can be retrieved.
"""

from __future__ import annotations

import html
import re
from typing import Callable

import httpx

from soma_data.gemini_client import GeminiClient, GeminiError, parse_model_json
from soma_data.validate_reply import denied

_VERBS = (
    "lsb_release",
    "apt-get",
    "aptitude",
    "dpkg",
    "apt",
    "hostnamectl",
    "timedatectl",
    "journalctl",
    "systemctl",
    "dumpe2fs",
    "tune2fs",
    "lsblk",
    "fdisk",
    "parted",
    "netplan",
    "nmcli",
    "ifconfig",
    "iwconfig",
    "modprobe",
    "adduser",
    "usermod",
    "groupadd",
    "useradd",
    "mount",
    "umount",
    "ufw",
    "iptables",
    "uname",
    "df",
    "du",
    "ls",
    "cat",
    "ip",
    "ss",
    "ping",
    "free",
    "top",
    "htop",
    "snap",
)
_VERB = "|".join(sorted(_VERBS, key=len, reverse=True))
_SURFACE = re.compile(
    rf"(?i)(?P<surface>(?:sudo\s+)*(?:{_VERB})\b(?P<args>[^`\n;]*))"
)
_TICK = re.compile(r"`([^`]+)`")
_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "to",
        "the",
        "or",
        "then",
        "so",
        "you",
        "your",
        "this",
        "that",
        "if",
        "for",
        "with",
        "on",
        "in",
        "of",
        "it",
        "is",
        "please",
        "try",
        "run",
        "use",
        "using",
        "from",
        "into",
        "by",
        "at",
    }
)
_MAN8 = frozenset(
    {
        "apt",
        "apt-get",
        "aptitude",
        "dpkg",
        "mount",
        "umount",
        "systemctl",
        "ufw",
        "adduser",
        "usermod",
        "useradd",
        "groupadd",
        "modprobe",
        "netplan",
        "nmcli",
        "ip",
        "fdisk",
        "parted",
        "tune2fs",
        "dumpe2fs",
    }
)
_MAN5 = {
    "os-release": "os-release",
    "fstab": "fstab",
    "passwd": "passwd",
    "sudoers": "sudoers",
}
_CONTRADICT = """Does this reply contradict a fact the user stated or a helper line in the window?
Answer YES when the reply disagrees with a number, cause, or instruction a user or a helper already stated.
If two helper lines disagree, a reply that states either side contradicts the other helper line. Answer YES.
A new command that the window never mentioned is not, by itself, a contradiction.
Return JSON only: {"contradicts":"YES"} or {"contradicts":"NO"}

WINDOW:
{window}

REPLY:
{reply}
"""
_SUPPORT = """Does this official Ubuntu snippet support this command as used in the reply?
COMMAND: {command}
YES when the snippet documents that command, or the file it reads, and the reply does not contradict the snippet.
A flag listed as showing the release, the description, or all of that information does support a reply about the Ubuntu version.
NO when the snippet is about a different command, or contradicts the reply.
Return JSON only: {"supports":"YES"} or {"supports":"NO"}

SNIPPET:
{snippet}

REPLY:
{reply}
"""


_ACTION = frozenset(
    {
        "install",
        "remove",
        "purge",
        "update",
        "upgrade",
        "search",
        "show",
        "list",
        "status",
        "start",
        "stop",
        "enable",
        "disable",
        "restart",
        "hold",
        "autoremove",
        "clean",
        "check",
        "all",
    }
)


def _clip(surface: str) -> str:
    """Keep the command. Drop the English that follows it."""
    tokens: list[str] = []
    for raw in (surface or "").split():
        word = raw.strip(".,'\"()[]`")
        if word:
            tokens.append(word)
    kept: list[str] = []
    for word in tokens:
        lower = word.lower()
        if lower in _STOP:
            break
        if lower == "sudo" and not kept:
            kept.append(word)
            continue
        if not any(part.lower() != "sudo" for part in kept):
            kept.append(word)
            continue
        if word.startswith("-") or word.startswith("/"):
            kept.append(word)
            continue
        if lower in _ACTION:
            kept.append(word)
            continue
        if kept[-1].lower() in _ACTION:
            kept.append(word)
            break
        if not word.isalpha():
            kept.append(word)
            continue
        break
    return " ".join(kept).strip()


def command_surfaces(text: str) -> list[str]:
    """Command spans a reply tells someone to run, longest first, de-duplicated."""
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        clipped = _clip(" ".join((raw or "").split()))
        parts = [part for part in clipped.split() if part.lower() != "sudo"]
        if len(parts) < 2:
            return
        nxt = parts[1]
        if not (nxt.startswith("-") or nxt.startswith("/") or nxt.lower() in _ACTION):
            return
        key = clipped.lower()
        if len(key) < 2 or key in seen or key in _STOP:
            return
        seen.add(key)
        found.append(clipped)

    for tick in _TICK.findall(text or ""):
        add(tick)
    for match in _SURFACE.finditer(text or ""):
        add(match.group("surface"))
    found.sort(key=len, reverse=True)
    return found


def command_already_in_window(reply: str, window: str) -> bool:
    """True when a command in the reply already appears in the window."""
    hay = " ".join((window or "").split())
    for surface in command_surfaces(reply):
        needle = " ".join(surface.split())
        bare = re.sub(r"(?i)^sudo\s+", "", needle)
        for item in (needle, bare):
            if not item:
                continue
            pattern = r"(?<![A-Za-z0-9_./])" + re.escape(item) + r"(?![A-Za-z0-9_])"
            if re.search(pattern, hay, re.I):
                return True
    return False


def _yes(value: object) -> bool:
    return str(value or "").strip().upper() in {"YES", "TRUE", "1"}


def contradicts(window: str, reply: str, client: GeminiClient) -> bool:
    """One model call. True means the reply must be silenced.

    A failed call also returns True. The room passes the Modal reply model.
    """
    prompt = _CONTRADICT.replace("{window}", window_block(window)).replace("{reply}", reply.strip())
    try:
        payload = parse_model_json(client.complete(prompt))
    except Exception:
        return True
    return _yes(payload.get("contradicts"))


def _page_names(surface: str) -> list[tuple[str, int]]:
    lower = surface.lower()
    pages: list[tuple[str, int]] = []
    for needle, page in _MAN5.items():
        if needle in lower:
            pages.append((page, 5))
    verb = ""
    for token in lower.split():
        if token == "sudo":
            continue
        verb = token.strip(".,")
        break
    if verb in _MAN8:
        pages.append((verb, 8))
    elif verb and verb not in {name for name, _section in pages}:
        pages.append((verb, 1))
        pages.append((verb, 8))
    return pages


def _urls(surface: str) -> list[str]:
    urls: list[str] = []
    for name, section in _page_names(surface):
        for release in ("noble", "jammy"):
            urls.append(
                f"https://manpages.ubuntu.com/manpages/{release}/en/man{section}/{name}.{section}.html"
            )
    return urls


def _html_to_text(body: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", body or "")
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|li|pre|tr)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    for src, dst in (
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&amp;", "&"),
        ("&quot;", '"'),
        ("&#39;", "'"),
        ("&nbsp;", " "),
    ):
        text = text.replace(src, dst)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _manual_text(body: str) -> str:
    """Man-page body only. The site nav also contains the word description."""
    raw = body or ""
    if "<" in raw:
        start = raw.lower().find("<h1")
        if start >= 0:
            raw = raw[start:]
        stop = raw.lower().find("<footer")
        if stop > 0:
            raw = raw[:stop]
        raw = _html_to_text(raw)
    return html.unescape(raw).strip()


def _http_get(url: str) -> str | None:
    try:
        response = httpx.get(
            url,
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": "soma-speak/0.1"},
        )
    except httpx.HTTPError:
        return None
    if response.status_code != 200 or not response.text:
        return None
    return response.text


def snippet_for_surface(
    surface: str,
    *,
    fetch: Callable[[str], str | None] | None = None,
) -> str | None:
    """Official Ubuntu man-page text for one command, or None."""
    getter = fetch or _http_get
    for url in _urls(surface):
        body = getter(url)
        if not body:
            continue
        text = _manual_text(body)[:2000].strip()
        if len(text) >= 40:
            return text
    return None


def ubuntu_snippet(
    reply: str,
    *,
    fetch: Callable[[str], str | None] | None = None,
) -> str | None:
    """Official Ubuntu man-page text for the reply's first command, or None."""
    surfaces = command_surfaces(reply)
    if not surfaces:
        return None
    return snippet_for_surface(surfaces[0], fetch=fetch)


def snippet_supports(reply: str, snippet: str, client: GeminiClient, *, command: str = "") -> bool:
    prompt = (
        _SUPPORT.replace("{command}", command or reply.strip())
        .replace("{snippet}", snippet[:2200])
        .replace("{reply}", reply.strip())
    )
    try:
        payload = parse_model_json(client.complete(prompt))
    except (GeminiError, ValueError, TypeError):
        return False
    return _yes(payload.get("supports"))


def docs_allow(
    reply: str,
    client: GeminiClient,
    *,
    fetch: Callable[[str], str | None] | None = None,
) -> bool:
    """True when every retrieved snippet supports its command.

    No command, or no retrieved snippet, skips this optional filter.
    """
    checked = False
    for surface in command_surfaces(reply):
        snippet = snippet_for_surface(surface, fetch=fetch)
        if snippet is None:
            continue
        checked = True
        if not snippet_supports(reply, snippet, client, command=surface):
            return False
    return True


def window_block(window: str) -> str:
    lines = [ln.strip() for ln in (window or "").splitlines() if ln.strip()]
    lines = lines[-12:]
    return "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1))


def draft_is_denied(reply: str) -> bool:
    return denied(reply)
