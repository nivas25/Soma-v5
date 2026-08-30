"""Teacher prompt_version=pilot_v2.1. Quieter Nick: law. No v2 still-broken→SPEAK."""

from __future__ import annotations

import re
from typing import Any

PROMPT_VERSION = "pilot_v2.1"

TEACHER_SYSTEM_PROMPT_V2_1 = """You label SPEAK or SILENT for an EXTRA helper-bot AFTER the last line of a 12-line IRC window.
You are not writing a reply. You do not need to know the Linux command.

Default: SILENT. Prefer SILENT when unsure.

SPEAK when:
- The last line is a real how-to / "anyone" / install-boot-wifi-driver-apt question AND nobody in the window owns that thread.
- OR a follow-up how-to ("what should I use then?") with no owner yet.
Busy room is not a reason to stay silent if that last thread is unanswered.

SILENT when:
- thanks / k / ok / works / fixed / good luck / nevermind
- joke, debate, offtopic, brb, language-chat
- last speaker is a helper giving steps or a diagnostic
- last line is Nick: to someone who already spoke in the window (helper still present), even if the user says "nothing happens" / "still fails" / "didn't accept"
- SPEAK on Nick: ONLY if that helper clearly left / is going to sleep AND the user is still stuck
- two humans already on that thread (pile-on)
- unsure

Return ONE JSON object, no markdown:
{"label":"SPEAK"|"SILENT","reason":"<=15 words"}"""


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


def nicks_in_chat(chat: str) -> set[str]:
    nicks: set[str] = set()
    for ln in str(chat or "").splitlines():
        ln = ln.strip()
        if ln.startswith("* "):
            parts = ln[2:].split()
            if parts:
                nicks.add(parts[0])
            continue
        if ": " in ln:
            nicks.add(ln.split(": ", 1)[0].strip())
    return {n for n in nicks if n}


def helper_still_in_window(row: dict) -> bool:
    """True if addressed nick (or last-line Nick:) already spoke in the window."""
    chat = str(row.get("chat_block") or "")
    nicks = {n.lower() for n in nicks_in_chat(chat)}
    addr = _addr(row.get("addressed_to")).lower()
    if addr and addr in nicks:
        return True
    last = _last_line(row)
    m = re.match(r"^\S+:\s+(\S+):", last)
    if m and m.group(1).lower() in nicks:
        return True
    return False


def build_user_payload_v2_1(row: dict) -> str:
    """Grok-style payload. No guideline_hint. Optional helper_in_window flag."""
    addr = _addr(row.get("addressed_to"))
    chat = row.get("chat_block") or ""
    helper = "yes" if helper_still_in_window(row) else "no"
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


def _shot(wid: str, last_speaker: str, question: str, thanks: str, addressed: str, helper: str, last: str, chat: str) -> str:
    return (
        f"WINDOW_ID: {wid}\n"
        f"last_speaker={last_speaker} question={question} thanks={thanks} addressed_to={addressed}\n"
        f"helper_in_window={helper}\n"
        f"LAST: {last}\n"
        f"\n"
        f"CHAT:\n"
        f"{chat}\n"
        f"\n"
        f"Decide AFTER the last line. JSON only."
    )


# Short sketches. WINDOW_IDs are shot:* — never audit_200 ids.
FEW_SHOTS: list[tuple[str, str]] = [
    (
        _shot(
            "shot:owned_midstep",
            "jeroen_",
            "no",
            "no",
            "curut",
            "yes",
            "jeroen_: curut, no, what Synaptic suggests",
            "jeroen_: curut, no, what Synaptic suggests",
        ),
        '{"label":"SILENT","reason":"jeroen_ answering curut mid-thread"}',
    ),
    (
        _shot(
            "shot:thanks",
            "Lynda",
            "no",
            "yes",
            "Arlie",
            "yes",
            "Lynda: Arlie: thanks... darn i got to fix a stupid problem",
            "Lynda: Arlie: thanks... darn i got to fix a stupid problem",
        ),
        '{"label":"SILENT","reason":"thanks to Arlie, not a new ask"}',
    ),
    (
        _shot(
            "shot:offtopic",
            "Margene",
            "no",
            "no",
            "",
            "no",
            "Margene: lose 95 was 32mb",
            "Margene: lose 95 was 32mb",
        ),
        '{"label":"SILENT","reason":"OS nostalgia not a help request"}',
    ),
    (
        _shot(
            "shot:hanging_howto",
            "jsimmons",
            "yes",
            "no",
            "",
            "no",
            "jsimmons: can i use aptitude to install a pack I downloaded?",
            "jsimmons: can i use aptitude to install a pack I downloaded?",
        ),
        '{"label":"SPEAK","reason":"group how-to, no owner yet"}',
    ),
    (
        _shot(
            "shot:stuck_helper_present",
            "sktrdie",
            "no",
            "no",
            "enrico",
            "yes",
            "sktrdie: enrico: nothing happens",
            "enrico: try launching it from a terminal\nsktrdie: enrico: nothing happens",
        ),
        '{"label":"SILENT","reason":"enrico still in window, do not pile on"}',
    ),
    (
        _shot(
            "shot:helper_instruct",
            "jeroen_",
            "no",
            "no",
            "jsimmons",
            "yes",
            "jeroen_: jsimmons, for example: sudo dpkg -i package.deb",
            "jeroen_: jsimmons, for example: sudo dpkg -i package.deb",
        ),
        '{"label":"SILENT","reason":"helper mid-instruction"}',
    ),
    (
        _shot(
            "shot:unanswered_followup",
            "user",
            "yes",
            "no",
            "",
            "no",
            "what should I use then?",
            "user: how do I install the driver?\nuser: what should I use then?",
        ),
        '{"label":"SPEAK","reason":"follow-up still unanswered"}',
    ),
    (
        _shot(
            "shot:pile_on",
            "IceDC571",
            "no",
            "no",
            "ukato",
            "yes",
            "IceDC571: ukato: it depends what your ripping speed is",
            "IceDC571: ukato: it depends what your ripping speed is",
        ),
        '{"label":"SILENT","reason":"IceDC571 already helping ukato"}',
    ),
    (
        _shot(
            "shot:stuck_password_helper_present",
            "sean_",
            "no",
            "no",
            "bluefox",
            "yes",
            "sean_: I did, and it didn't accept",
            "bluefox: type su and enter the password\nsean_: I did, and it didn't accept",
        ),
        '{"label":"SILENT","reason":"helper still present after failed step"}',
    ),
    (
        _shot(
            "shot:ask_helper_advice",
            "xpat",
            "yes",
            "no",
            "farous",
            "yes",
            "xpat: farous: sorry, don't know how to access that....advice ?",
            "farous: it is in multiverse\nxpat: farous: sorry, don't know how to access that....advice ?",
        ),
        '{"label":"SILENT","reason":"follow-up to farous who is in the window"}',
    ),
]


def few_shot_window_ids() -> set[str]:
    return {p.split("\n", 1)[0].removeprefix("WINDOW_ID: ").strip() for p, _ in FEW_SHOTS}


def build_chat_messages(user_payload: str) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = [{"role": "system", "content": TEACHER_SYSTEM_PROMPT_V2_1}]
    for user, assistant in FEW_SHOTS:
        msgs.append({"role": "user", "content": user})
        msgs.append({"role": "assistant", "content": assistant})
    msgs.append({"role": "user", "content": user_payload})
    return msgs


SFT_INSTRUCTION_V2_1 = (
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
        "instruction": SFT_INSTRUCTION_V2_1,
        "input": build_user_payload_v2_1(row),
        "output": lab,
    }
