"""Teacher prompt_version=pilot_v2.2. Thread-scoped helper_in_window."""

from __future__ import annotations

import re
from typing import Any

PROMPT_VERSION = "pilot_v2.2"

TEACHER_SYSTEM_PROMPT_V2_2 = """You label SPEAK or SILENT for an EXTRA helper-bot AFTER the last line of a 12-line IRC window.
You are not writing a reply. You do not need to know the Linux command.

Default: SILENT. Prefer SILENT when unsure.

SPEAK when:
- helper_in_window=no AND the last line is a real how-to / "anyone" / install-boot-wifi-driver-apt question with no owner.
- OR a follow-up how-to ("what should I use then?") with no owner yet.
Busy room is not a reason to stay silent if that last thread is unanswered and helper_in_window=no.

SILENT when:
- thanks / k / ok / works / fixed / good luck / nevermind
- joke, debate, offtopic, brb, language-chat, interjection ("oh man")
- last speaker is a helper giving steps or a diagnostic
- last line is Nick: to someone who already spoke in the window (helper still present), even if the user says "nothing happens" / "still fails" / "didn't accept"
- SPEAK on Nick: ONLY if that helper clearly left / is going to sleep AND the user is still stuck
- helper_in_window=yes AND the last line is not a brand-new group how-to to the room (continuation / stuck report / helper diagnostic → SILENT)
- two humans already on that thread (pile-on)
- unsure

Return ONE JSON object, no markdown:
{"label":"SPEAK"|"SILENT","reason":"<=15 words"}"""

BOT_NICKS = frozenset({"ubottu", "ubotu"})
_SPEAKER = re.compile(r"^(\S+):")
_ADDR_BODY = re.compile(r"^(\S+)[:,]\s+")
_PIPE_NICK = re.compile(r"\|\s*(\S+)\s*$")
_HELPER_LANG = re.compile(
    r"(?i)("
    r"\btry\b|\bsudo\b|\bapt(?:-get)?\b|\bdpkg\b|\btype\b|\brun\b|\bpaste(?:bin)?\b|"
    r"\bcheck\b|open a terminal|from a terminal|\bdid you\b|\bhave you\b|\bcan you\b|"
    r"you (?:can|should|need|have to)|what (?:does|happens|kind)|"
    r"\bare you\b|\bdoes it\b|!\w+|\brtfm\b|\belaborate\b|"
    r"tell \S+ about"
    r")"
)
_DIAGNOSTIC = re.compile(
    r"(?i)\b("
    r"did you|have you|does it|do you|are you|can you|"
    r"what (?:does|happens|kind|is the tool)|how far|"
    r"fully boot|on a terminal|run the command"
    r")\b"
)
_GREETING = re.compile(
    r"(?i)^(just ask|hello|hi|hey|yo|wb|welcome|ask(?: away)?)\.?$"
)
_UBOTU_TELL = re.compile(r"(?i)\b(ubotu|ubottu)[,:]?\s+tell\b")


def _yn(value: object) -> str:
    if value is True or str(value).strip().lower() in {"true", "1", "yes", "y"}:
        return "yes"
    return "no"


def _addr(value: object) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if s == "" or s.lower() in {"nan", "none", "null", "group"}:
        return ""
    return s


def _last_line(row: dict) -> str:
    last = str(row.get("last_line") or "").strip()
    if last:
        return last
    chat = str(row.get("chat_block") or "")
    lines = [ln for ln in chat.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def parse_chat_lines(chat: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for ln in str(chat or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("* "):
            parts = ln[2:].split(None, 1)
            out.append((parts[0], parts[1] if len(parts) > 1 else ""))
            continue
        m = _SPEAKER.match(ln)
        if m:
            out.append((m.group(1), ln[len(m.group(1)) + 1 :].lstrip()))
        else:
            out.append(("", ln))
    return out


def nicks_in_chat(chat: str) -> set[str]:
    return {s for s, _ in parse_chat_lines(chat) if s}


def _is_floodbot(nick: str) -> bool:
    return nick.lower().startswith("floodbot")


def _is_bot(nick: str) -> bool:
    s = nick.lower()
    return s in BOT_NICKS or s.startswith("ubot") or _is_floodbot(nick)


def _addressee(body: str) -> str:
    m = _ADDR_BODY.match(body.strip())
    if m:
        return m.group(1).lower().rstrip(":")
    return ""


def _pipe_nick(body: str) -> str:
    m = _PIPE_NICK.search(body.strip())
    if m:
        return m.group(1).lower()
    return ""


def _body_after_addr(body: str) -> str:
    m = _ADDR_BODY.match(body.strip())
    if not m:
        return body.strip()
    return body.strip()[m.end() :].strip()


def last_addressee(last: str) -> str:
    m = _SPEAKER.match(last.strip())
    body = last.strip()[len(m.group(1)) + 1 :].lstrip() if m else last
    return _addressee(body)


def helper_still_in_window(row: dict) -> bool:
    """Back-compat alias: addressed nick (or last-line Nick:) already spoke."""
    chat = str(row.get("chat_block") or "")
    nicks = {n.lower() for n in nicks_in_chat(chat)}
    addr = _addr(row.get("addressed_to")).lower()
    if addr and addr in nicks:
        return True
    last = _last_line(row)
    a = last_addressee(last)
    if a and a in nicks:
        return True
    return False


def helper_in_window(row: dict) -> bool:
    """True if a helper is already on the last speaker's thread.

    helper language toward last_speaker
    OR 2+ answer-like lines toward last_speaker
    OR last speaker asking a diagnostic / commanding ubotu
    OR addressed nick already spoke (v2.1).
    FloodBot is not a helper. Greetings ("just ask") are not answers.
    """
    chat = str(row.get("chat_block") or "")
    last = _last_line(row)
    ls = str(row.get("last_speaker") or "").strip().lower()
    nickset = {n.lower() for n in nicks_in_chat(chat)}
    lines = parse_chat_lines(chat)

    if helper_still_in_window(row):
        return True

    ans_to_last = 0
    helper_lang = False
    for spk, body in lines[:-1]:
        sl = (spk or "").lower()
        if not sl or sl == ls or _is_floodbot(sl):
            continue
        to = _addressee(body)
        pipe = _pipe_nick(body)
        toward = to == ls or pipe == ls
        if not toward:
            continue
        rest = _body_after_addr(body)
        if _GREETING.match(rest):
            continue
        ans_to_last += 1
        if _HELPER_LANG.search(body) or sl in BOT_NICKS or sl.startswith("ubot"):
            helper_lang = True
    if helper_lang:
        return True
    if ans_to_last >= 2:
        return True
    # One human already talking to last_speaker counts as helper language on that thread.
    if ans_to_last >= 1:
        return True

    la = last_addressee(last)
    m = _SPEAKER.match(last.strip())
    body = last.strip()[len(m.group(1)) + 1 :].lstrip() if m else last
    if _UBOTU_TELL.search(last) or la in BOT_NICKS:
        return True
    if la and la in nickset and la != ls and not _is_floodbot(la):
        if _DIAGNOSTIC.search(body) or _HELPER_LANG.search(body) or last.strip().endswith("?"):
            return True
    return False


def build_user_payload_v2_2(row: dict) -> str:
    """Grok-style payload. No guideline_hint. helper_in_window=yes/no only."""
    addr = _addr(row.get("addressed_to"))
    chat = row.get("chat_block") or ""
    helper = "yes" if helper_in_window(row) else "no"
    return (
        f"WINDOW_ID: {row['window_id']}\n"
        f"last_speaker={row.get('last_speaker') or ''} "
        f"question={_yn(row.get('last_is_question'))} "
        f"thanks={_yn(row.get('last_is_thanks'))} "
        f"addressed_to={addr}\n"
        f"helper_in_window={helper}\n"
        f"LAST: {_last_line(row)}\n"
        f"\n"
        f"CHAT:\n"
        f"{chat}\n"
        f"\n"
        f"Decide AFTER the last line. JSON only."
    )


def _shot_row(
    wid: str,
    last_speaker: str,
    question: str,
    thanks: str,
    addressed: str,
    last: str,
    chat: str,
) -> dict[str, str]:
    return {
        "window_id": wid,
        "last_speaker": last_speaker,
        "last_is_question": question,
        "last_is_thanks": thanks,
        "addressed_to": addressed,
        "last_line": last,
        "chat_block": chat,
    }


def _payload_from_row(row: dict[str, str]) -> str:
    return build_user_payload_v2_2(row)


# Short sketches. WINDOW_IDs are shot:* — never audit_200 ids.
_SHOT_ROWS: list[tuple[dict[str, str], str]] = [
    (
        _shot_row(
            "shot:owned_midstep",
            "jeroen_",
            "no",
            "no",
            "curut",
            "jeroen_: curut, no, what Synaptic suggests",
            "curut: how do I use synaptic\njeroen_: curut, no, what Synaptic suggests",
        ),
        '{"label":"SILENT","reason":"jeroen_ answering curut mid-thread"}',
    ),
    (
        _shot_row(
            "shot:thanks",
            "Lynda",
            "no",
            "yes",
            "Arlie",
            "Lynda: Arlie: thanks... darn i got to fix a stupid problem",
            "Arlie: try this\nLynda: Arlie: thanks... darn i got to fix a stupid problem",
        ),
        '{"label":"SILENT","reason":"thanks to Arlie, not a new ask"}',
    ),
    (
        _shot_row(
            "shot:offtopic",
            "Margene",
            "no",
            "no",
            "",
            "Margene: lose 95 was 32mb",
            "Margene: lose 95 was 32mb",
        ),
        '{"label":"SILENT","reason":"OS nostalgia not a help request"}',
    ),
    (
        _shot_row(
            "shot:hanging_howto",
            "jsimmons",
            "yes",
            "no",
            "",
            "jsimmons: can i use aptitude to install a pack I downloaded?",
            "jsimmons: can i use aptitude to install a pack I downloaded?",
        ),
        '{"label":"SPEAK","reason":"group how-to, no owner yet"}',
    ),
    (
        _shot_row(
            "shot:stuck_helper_present",
            "sktrdie",
            "no",
            "no",
            "enrico",
            "sktrdie: enrico: nothing happens",
            "enrico: try launching it from a terminal\nsktrdie: enrico: nothing happens",
        ),
        '{"label":"SILENT","reason":"enrico still in window, do not pile on"}',
    ),
    (
        _shot_row(
            "shot:helper_instruct",
            "jeroen_",
            "no",
            "no",
            "jsimmons",
            "jeroen_: jsimmons, for example: sudo dpkg -i package.deb",
            "jsimmons: how do I install the deb?\njeroen_: jsimmons, for example: sudo dpkg -i package.deb",
        ),
        '{"label":"SILENT","reason":"helper mid-instruction"}',
    ),
    (
        _shot_row(
            "shot:unanswered_followup",
            "user",
            "yes",
            "no",
            "",
            "what should I use then?",
            "user: how do I install the driver?\nuser: what should I use then?",
        ),
        '{"label":"SPEAK","reason":"follow-up still unanswered"}',
    ),
    (
        _shot_row(
            "shot:pile_on",
            "IceDC571",
            "no",
            "no",
            "ukato",
            "IceDC571: ukato: it depends what your ripping speed is",
            "ukato: what ripping speed should I use?\nIceDC571: ukato: it depends what your ripping speed is",
        ),
        '{"label":"SILENT","reason":"IceDC571 already helping ukato"}',
    ),
    (
        _shot_row(
            "shot:stuck_no_nick",
            "sean_",
            "no",
            "no",
            "",
            "sean_: I did, and it didn't accept",
            "bluefox: sean_, open a terminal, type su and the password\nsean_: I did, and it didn't accept",
        ),
        '{"label":"SILENT","reason":"helper still present after failed step"}',
    ),
    (
        _shot_row(
            "shot:ask_helper_advice",
            "xpat",
            "yes",
            "no",
            "farous",
            "xpat: farous: sorry, don't know how to access that....advice ?",
            "farous: it is in multiverse\nxpat: farous: sorry, don't know how to access that....advice ?",
        ),
        '{"label":"SILENT","reason":"follow-up to farous who is in the window"}',
    ),
    (
        _shot_row(
            "shot:helper_diagnostic",
            "pat",
            "yes",
            "no",
            "",
            "pat: mina, does it fully boot then reboot?",
            "mina: my machine reboots by itself\npat: mina, does it fully boot then reboot?",
        ),
        '{"label":"SILENT","reason":"last speaker is the helper diagnosing"}',
    ),
    (
        _shot_row(
            "shot:no_dice",
            "mira",
            "no",
            "no",
            "",
            "mira: no dice",
            "mira: flash will not play in firefox\nlex: mira: reinstall the plugin from synaptic\nmira: no dice",
        ),
        '{"label":"SILENT","reason":"lex already on mira thread"}',
    ),
    (
        _shot_row(
            "shot:interjection",
            "rio",
            "no",
            "no",
            "",
            "rio: oh man",
            "rio: any hardware issues with this laptop?\nrio: oh man",
        ),
        '{"label":"SILENT","reason":"interjection, not a new how-to"}',
    ),
    (
        _shot_row(
            "shot:busy_hanging_howto",
            "ada",
            "yes",
            "no",
            "",
            "ada: can I install this package with apt?",
            "gil: othernick, try sudo apt-get update\nothernick: gil: thanks\nada: can I install this package with apt?",
        ),
        '{"label":"SPEAK","reason":"new group how-to, ada thread has no helper"}',
    ),
]


def _few_shots() -> list[tuple[str, str]]:
    return [(_payload_from_row(row), ans) for row, ans in _SHOT_ROWS]


FEW_SHOTS: list[tuple[str, str]] = _few_shots()


def few_shot_window_ids() -> set[str]:
    return {row["window_id"] for row, _ in _SHOT_ROWS}


def build_chat_messages(user_payload: str) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = [{"role": "system", "content": TEACHER_SYSTEM_PROMPT_V2_2}]
    for user, assistant in FEW_SHOTS:
        msgs.append({"role": "user", "content": user})
        msgs.append({"role": "assistant", "content": assistant})
    msgs.append({"role": "user", "content": user_payload})
    return msgs


SFT_INSTRUCTION_V2_2 = (
    "You are an extra silent helper-bot in multi-party Ubuntu IRC. "
    "Decide SPEAK or SILENT AFTER the last line. Default SILENT. "
    "Reply with one token: SPEAK or SILENT."
)


def sft_record(row: dict, label: str, *, source: str, split: str) -> dict[str, Any]:
    lab = str(label).strip().upper()
    if lab not in {"SPEAK", "SILENT"}:
        raise ValueError(lab)
    return {
        "window_id": row["window_id"],
        "prompt_version": PROMPT_VERSION,
        "source": source,
        "split": split,
        "instruction": SFT_INSTRUCTION_V2_2,
        "input": build_user_payload_v2_2(row),
        "output": lab,
    }
