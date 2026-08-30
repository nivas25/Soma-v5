"""Teacher prompt_version=pilot_v2. Grok-style payload. No guideline_hint. No v1 technical-hint law."""

from __future__ import annotations

from typing import Any

PROMPT_VERSION = "pilot_v2"

TEACHER_SYSTEM_PROMPT_V2 = """You label SPEAK or SILENT for an EXTRA helper-bot AFTER the last line of a 12-line IRC window.
You are not writing a reply. You do not need to know the Linux command.

Default: SILENT.

SPEAK when:
- The last line is a real how-to / “anyone” / install-boot-wifi-driver-apt question and nobody in the window owns that thread.
- OR the last line is still-broken (“nothing happens”, “still fails”, same error after a step), even if it says Nick:.
Busy room is not a reason to stay silent if that last thread is unanswered.

SILENT when:
- thanks / k / ok / works / fixed / good luck / nevermind
- joke, debate, offtopic, brb
- a human is mid-step on that exact thread and the last line is NOT a failure report
- last line is Nick: to someone already helping AND the last step has not failed
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


def build_user_payload_v2(row: dict) -> str:
    """Teacher + student input template. No guideline_hint. No few-shots."""
    addr = _addr(row.get("addressed_to"))
    chat = row.get("chat_block") or ""
    return (
        f"WINDOW_ID: {row['window_id']}\n"
        f"last_speaker={row.get('last_speaker') or ''} "
        f"question={_yn(row.get('last_is_question'))} "
        f"thanks={_yn(row.get('last_is_thanks'))} "
        f"addressed_to={addr}\n"
        f"LAST: {_last_line(row)}\n"
        f"\n"
        f"CHAT:\n"
        f"{chat}\n"
        f"\n"
        f"Decide AFTER the last line. JSON only."
    )


# Short pattern sketches. WINDOW_IDs are shot:* — never audit_200 ids.
FEW_SHOTS: list[tuple[str, str]] = [
    (
        "WINDOW_ID: shot:owned_midstep\n"
        "last_speaker=jeroen_ question=no thanks=no addressed_to=curut\n"
        "LAST: jeroen_: curut, no, what Synaptic suggests\n"
        "\n"
        "CHAT:\n"
        "jeroen_: curut, no, what Synaptic suggests\n"
        "\n"
        "Decide AFTER the last line. JSON only.",
        '{"label":"SILENT","reason":"jeroen_ answering curut mid-thread"}',
    ),
    (
        "WINDOW_ID: shot:thanks\n"
        "last_speaker=Lynda question=no thanks=yes addressed_to=Arlie\n"
        "LAST: Lynda: Arlie: thanks... darn i got to fix a stupid problem\n"
        "\n"
        "CHAT:\n"
        "Lynda: Arlie: thanks... darn i got to fix a stupid problem\n"
        "\n"
        "Decide AFTER the last line. JSON only.",
        '{"label":"SILENT","reason":"thanks to Arlie, not a new ask"}',
    ),
    (
        "WINDOW_ID: shot:offtopic\n"
        "last_speaker=Margene question=no thanks=no addressed_to=\n"
        "LAST: Margene: lose 95 was 32mb\n"
        "\n"
        "CHAT:\n"
        "Margene: lose 95 was 32mb\n"
        "\n"
        "Decide AFTER the last line. JSON only.",
        '{"label":"SILENT","reason":"OS nostalgia not a help request"}',
    ),
    (
        "WINDOW_ID: shot:hanging_howto\n"
        "last_speaker=jsimmons question=yes thanks=no addressed_to=\n"
        "LAST: jsimmons: can i use aptitude to install a pack I downloaded?\n"
        "\n"
        "CHAT:\n"
        "jsimmons: can i use aptitude to install a pack I downloaded?\n"
        "\n"
        "Decide AFTER the last line. JSON only.",
        '{"label":"SPEAK","reason":"group how-to, no owner yet"}',
    ),
    (
        "WINDOW_ID: shot:still_broken\n"
        "last_speaker=sktrdie question=no thanks=no addressed_to=enrico\n"
        "LAST: sktrdie: enrico: nothing happens\n"
        "\n"
        "CHAT:\n"
        "sktrdie: enrico: nothing happens\n"
        "\n"
        "Decide AFTER the last line. JSON only.",
        '{"label":"SPEAK","reason":"named helper but last step failed"}',
    ),
    (
        "WINDOW_ID: shot:helper_instruct\n"
        "last_speaker=jeroen_ question=no thanks=no addressed_to=jsimmons\n"
        "LAST: jeroen_: jsimmons, for example: sudo dpkg -i package.deb\n"
        "\n"
        "CHAT:\n"
        "jeroen_: jsimmons, for example: sudo dpkg -i package.deb\n"
        "\n"
        "Decide AFTER the last line. JSON only.",
        '{"label":"SILENT","reason":"helper mid-instruction"}',
    ),
    (
        "WINDOW_ID: shot:unanswered_followup\n"
        "last_speaker=user question=yes thanks=no addressed_to=\n"
        "LAST: what should I use then?\n"
        "\n"
        "CHAT:\n"
        "user: how do I install the driver?\n"
        "user: what should I use then?\n"
        "\n"
        "Decide AFTER the last line. JSON only.",
        '{"label":"SPEAK","reason":"follow-up still unanswered"}',
    ),
    (
        "WINDOW_ID: shot:pile_on\n"
        "last_speaker=IceDC571 question=no thanks=no addressed_to=ukato\n"
        "LAST: IceDC571: ukato: it depends what your ripping speed is\n"
        "\n"
        "CHAT:\n"
        "IceDC571: ukato: it depends what your ripping speed is\n"
        "\n"
        "Decide AFTER the last line. JSON only.",
        '{"label":"SILENT","reason":"IceDC571 already helping ukato"}',
    ),
]


def few_shot_window_ids() -> set[str]:
    return {p.split("\n", 1)[0].removeprefix("WINDOW_ID: ").strip() for p, _ in FEW_SHOTS}


def build_chat_messages(user_payload: str) -> list[dict[str, str]]:
    """Qwen chat: system + 8 user/assistant shots + live user."""
    msgs: list[dict[str, str]] = [{"role": "system", "content": TEACHER_SYSTEM_PROMPT_V2}]
    for user, assistant in FEW_SHOTS:
        msgs.append({"role": "user", "content": user})
        msgs.append({"role": "assistant", "content": assistant})
    msgs.append({"role": "user", "content": user_payload})
    return msgs


SFT_INSTRUCTION_V2 = (
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
        "instruction": SFT_INSTRUCTION_V2,
        "input": build_user_payload_v2(row),
        "output": lab,
    }
