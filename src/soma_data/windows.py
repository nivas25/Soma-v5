"""Order messages and emit fixed-W=12 windows.

Sort key: (config, split, date, slice_id, original_id). Never connections.
A slice starts when `original_id` decreases inside the same (config, split, date)
— that is how concatenated same-day annotation files show up on the Hub.
A run starts when the id gap exceeds GAP_THRESHOLD inside a slice.

Windows:
  decision point = after message t
  window        = last W non-system messages in the SAME run, ending at t
  emit iff exactly W lines (uniform labelling UI)
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import pandas as pd
from pydantic import BaseModel, Field

from soma_data.config import (
    EXCLUDE_SYSTEM_FROM_WINDOWS,
    GAP_THRESHOLD,
    REQUIRE_EXACT_W,
    TIME_CAP_MINUTES,
    WINDOW_SIZE,
)
from soma_data.parse_irc import ParsedIrcMessage, is_thanks, parse_hub_row


class WindowRecord(BaseModel):
    """One labelling / SFT row. label_gold is always empty here."""

    window_id: str
    config: str
    split: str
    date: str
    slice_id: int
    run_id: int
    t_id: int
    source: str
    n_messages: int
    n_speakers_in_window: int
    last_speaker: str | None
    question_open: bool
    addressed_to: str | None
    assistant_named: bool = False
    thread_ids_last: list[int] = Field(default_factory=list)
    thread_overlap_count: int = 0
    last_is_question: bool = False
    last_is_thanks: bool = False
    time_capped_n: int | None = None
    time_hhmm_last: str | None = None
    window_message_ids: list[int] = Field(default_factory=list)
    chat_block: str
    label_gold: str = ""
    guideline_hint: str = ""


def parse_dataframe(df: pd.DataFrame) -> list[ParsedIrcMessage]:
    """Parse Hub/raw rows. `df` must have config, split, date, id, raw."""
    out: list[ParsedIrcMessage] = []
    for i, rec in enumerate(df.to_dict(orient="records")):
        date = rec.get("date")
        if date is None or (isinstance(date, float) and pd.isna(date)):
            date = "undated"
        out.append(
            parse_hub_row(
                rec,
                config=str(rec["config"]),
                split=str(rec["split"]),
                date=str(date),
                row_idx=int(rec.get("row_idx", i)),
            )
        )
    return out


def assign_slices_and_runs(
    messages: list[ParsedIrcMessage],
    *,
    gap_threshold: int = GAP_THRESHOLD,
) -> list[ParsedIrcMessage]:
    """Mutate slice_id / run_id in original Hub order, then stable-sort.

    Walk each (config, split) in `row_idx` order (Hub concatenation order).
    A new slice starts when original_id decreases on the same date — two
    annotation files of the same calendar day concatenated.
    Inside a slice, a new run starts when id[i] - id[i-1] > gap_threshold.
    """
    groups: dict[tuple[str, str], list[ParsedIrcMessage]] = {}
    for m in messages:
        groups.setdefault((m.config, m.split), []).append(m)

    assigned: list[ParsedIrcMessage] = []
    for key in sorted(groups):
        bucket = sorted(groups[key], key=lambda x: x.row_idx)
        slice_id = 0
        run_id = 0
        prev: ParsedIrcMessage | None = None
        for m in bucket:
            if prev is None:
                m.slice_id = 0
                m.run_id = 0
            else:
                # Date change OR id reset (same-day file concat) starts a new slice.
                # Never reset the slice counter: two visits to the same calendar
                # date must not share slice_id 0 or they would interleave on sort.
                new_slice = (m.date != prev.date) or (m.original_id < prev.original_id)
                if new_slice:
                    slice_id += 1
                    run_id = 0
                elif (m.original_id - prev.original_id) > gap_threshold:
                    run_id += 1
                m.slice_id = slice_id
                m.run_id = run_id
            prev = m
            assigned.append(m)

    assigned.sort(
        key=lambda m: (m.config, m.split, m.date, m.slice_id, m.run_id, m.original_id)
    )
    return assigned


def hhmm_to_minutes(hhmm: str | None) -> int | None:
    if not hhmm or len(hhmm) < 5 or hhmm[2] != ":":
        return None
    try:
        h = int(hhmm[:2])
        m = int(hhmm[3:5])
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h * 60 + m


def minutes_forward(earlier: str | None, later: str | None) -> int | None:
    """Minutes from earlier → later along conversation order, wrapping midnight."""
    e = hhmm_to_minutes(earlier)
    l = hhmm_to_minutes(later)
    if e is None or l is None:
        return None
    delta = l - e
    if delta < 0:
        # Early Ubuntu irclogs are 12-hour clocks (12:59 → 01:00 = 1 min).
        # Later years are 24-hour (23:59 → 00:00). Prefer the wrap that
        # yields a small positive delta.
        d12 = l + 12 * 60 - e
        d24 = l + 24 * 60 - e
        if 0 <= d12 <= 6 * 60:
            delta = d12
        else:
            delta = d24
    return delta


def time_capped_count(
    window: Sequence[ParsedIrcMessage],
    *,
    cap_minutes: int = TIME_CAP_MINUTES,
) -> int | None:
    last = window[-1]
    if last.time_hhmm is None:
        return None
    n = 0
    for m in window:
        d = minutes_forward(m.time_hhmm, last.time_hhmm)
        if d is None:
            continue
        if d <= cap_minutes:
            n += 1
    return n


def thread_overlap_count(window: Sequence[ParsedIrcMessage]) -> int:
    """How many window messages share a reply-graph edge with the last line.

    Counts m where m.id ∈ last.connections OR last.id ∈ m.connections
    (including a self-loop on the last message, which marks a new thread).
    """
    last = window[-1]
    last_con = set(last.connections)
    last_id = last.original_id
    n = 0
    for m in window:
        if m.original_id in last_con or last_id in set(m.connections):
            n += 1
    return n


def guideline_hint(last: ParsedIrcMessage, question_open: bool) -> str:
    """Short auto hint for the labeller. NOT label_gold."""
    if is_thanks(last.text):
        return "thanks"
    if last.addressed_to:
        return "addressed to human"
    if last.has_question:
        return "question + no clear addressee"
    if question_open:
        return "open question in last 3"
    return "other"


def build_window_record(
    window: Sequence[ParsedIrcMessage],
    *,
    w: int = WINDOW_SIZE,
) -> WindowRecord:
    if len(window) != w:
        raise ValueError(f"window length {len(window)} != W={w}")
    last = window[-1]
    dates = {m.date for m in window}
    runs = {(m.config, m.split, m.date, m.slice_id, m.run_id) for m in window}
    if len(dates) != 1:
        raise AssertionError(f"window crosses dates: {dates}")
    if len(runs) != 1:
        raise AssertionError(f"window crosses run keys: {runs}")

    last3 = window[-3:]
    q_open = any(m.has_question for m in last3)
    speakers = {m.speaker for m in window if m.speaker}
    chat_block = "\n".join(m.display_line() for m in window)
    if chat_block.count("\n") + 1 != w:
        raise AssertionError("chat_block line count != W")

    cfg, split, date, slice_id, run_id = next(iter(runs))
    window_id = f"{cfg}:{split}:{date}:{slice_id}:{run_id}:{last.original_id}"
    return WindowRecord(
        window_id=window_id,
        config=cfg,
        split=split,
        date=date,
        slice_id=slice_id,
        run_id=run_id,
        t_id=last.original_id,
        source=f"irc_disentangle/{cfg}",
        n_messages=len(window),
        n_speakers_in_window=len(speakers),
        last_speaker=last.speaker,
        question_open=q_open,
        addressed_to=last.addressed_to,
        assistant_named=False,
        thread_ids_last=list(last.connections),
        thread_overlap_count=thread_overlap_count(window),
        last_is_question=bool(last.has_question),
        last_is_thanks=is_thanks(last.text),
        time_capped_n=time_capped_count(window),
        time_hhmm_last=last.time_hhmm,
        window_message_ids=[m.original_id for m in window],
        chat_block=chat_block,
        label_gold="",
        guideline_hint=guideline_hint(last, q_open),
    )


def emit_windows(
    messages: Iterable[ParsedIrcMessage],
    *,
    w: int = WINDOW_SIZE,
    exclude_system: bool = EXCLUDE_SYSTEM_FROM_WINDOWS,
    require_exact_w: bool = REQUIRE_EXACT_W,
) -> list[WindowRecord]:
    """Slide a W-gram over each (config, split, date, slice, run)."""
    if not require_exact_w:
        raise NotImplementedError("Short windows are disabled; labelling UI is uniform W=12.")

    buckets: dict[tuple, list[ParsedIrcMessage]] = {}
    for m in messages:
        if exclude_system and (m.is_system or not m.parse_ok):
            continue
        key = (m.config, m.split, m.date, m.slice_id, m.run_id)
        buckets.setdefault(key, []).append(m)

    records: list[WindowRecord] = []
    for key in sorted(buckets):
        run_msgs = sorted(buckets[key], key=lambda x: x.original_id)
        if len(run_msgs) < w:
            continue
        for i in range(w - 1, len(run_msgs)):
            window = run_msgs[i - w + 1 : i + 1]
            records.append(build_window_record(window, w=w))
    return records


def windows_to_frame(records: Sequence[WindowRecord]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=list(WindowRecord.model_fields))
    return pd.DataFrame([r.model_dump() for r in records])
