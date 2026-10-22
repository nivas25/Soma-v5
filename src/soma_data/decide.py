"""Turn a frozen gate label into a reply without changing the timing call.

pred SPEAK stays a speak action. A thread-scoped clash changes only the
wording (REPORT_CONFLICT), not the decision to speak. pred SILENT stays
empty even when a clash is recorded. helper_in_window is not a veto:
the 8 false speaks on the 200 all have helper=no, and a helper veto would
only flip true speaks.
"""

from __future__ import annotations

from dataclasses import dataclass

from soma_data.conflict import Conflict, find_conflict, proposals
from soma_data.validate_reply import OPEN_REPLY, check_reply, denied, redact

_POINT = "From this window: "


@dataclass(frozen=True)
class Decision:
    action: str
    timing: str
    conflict: bool
    conflict_kind: str
    evidence_a: str
    evidence_b: str
    reply: str
    drop_reason: str


def _point_at(chat: str, asker: str, also: str = "") -> str:
    """One verbatim command aimed at the asker. Never a command from another thread."""
    wanted = {n.lower() for n in (asker, also) if n}
    candidates = []
    for item in proposals(chat):
        if denied(item.surface) or item.negative:
            continue
        if item.surface not in chat:
            continue
        aimed = item.group in wanted or item.speaker.lower() in wanted
        if not aimed:
            continue
        candidates.append(item)
    if not candidates:
        return OPEN_REPLY
    chosen = candidates[-1]
    return _POINT + chosen.surface


def _conflict_reply(clash: Conflict) -> str:
    left = redact(clash.line_a)
    right = redact(clash.line_b)
    return f'These two lines disagree: "{left}" / "{right}". Not choosing a command.'


def decide(pred: str, chat: str, *, asker: str = "", also: str = "") -> Decision:
    label = (pred or "").strip().upper()
    if label not in {"SPEAK", "SILENT"}:
        label = "SILENT"
    clash = find_conflict(chat)
    kind = clash.kind if clash else ""
    evidence_a = clash.line_a if clash else ""
    evidence_b = clash.line_b if clash else ""
    if label == "SILENT":
        action = "SILENT"
        reply = ""
    elif clash is not None:
        action = "REPORT_CONFLICT"
        reply = _conflict_reply(clash)
    else:
        action = "SPEAK"
        reply = _point_at(chat, asker, also)
    ok, reason = check_reply(chat, "SILENT" if action == "SILENT" else "SPEAK", reply)
    drop = ""
    if not ok:
        drop = reason
        if action == "SILENT":
            reply = ""
        else:
            reply = OPEN_REPLY
            ok2, reason2 = check_reply(chat, "SPEAK", reply)
            if not ok2:
                reply = ""
                action = "SILENT"
                drop = reason2 or reason
    timing = "SILENT" if action == "SILENT" else "SPEAK"
    return Decision(
        action=action,
        timing=timing,
        conflict=clash is not None,
        conflict_kind=kind,
        evidence_a=evidence_a,
        evidence_b=evidence_b,
        reply=reply,
        drop_reason=drop,
    )
