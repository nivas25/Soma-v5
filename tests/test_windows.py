"""Windowing invariants: no cross-date/run, exact W, gap splits runs."""

from __future__ import annotations

from soma_data.config import GAP_THRESHOLD, WINDOW_SIZE
from soma_data.parse_irc import ParsedIrcMessage
from soma_data.windows import assign_slices_and_runs, emit_windows, minutes_forward, thread_overlap_count


def _msg(
    original_id: int,
    *,
    date: str = "2004-12-25",
    config: str = "ubuntu",
    split: str = "train",
    raw: str | None = None,
    speaker: str = "ann",
    text: str = "hello",
    is_system: bool = False,
    connections: list[int] | None = None,
    row_idx: int | None = None,
    time_hhmm: str = "03:00",
    has_question: bool = False,
    addressed_to: str | None = None,
) -> ParsedIrcMessage:
    if raw is None:
        raw = f"[{time_hhmm}] <{speaker}> {text}"
    return ParsedIrcMessage(
        config=config,
        split=split,
        date=date,
        original_id=original_id,
        raw=raw,
        connections=connections or [],
        time_hhmm=time_hhmm,
        speaker=speaker,
        text=text,
        is_system=is_system,
        is_action=False,
        addressed_to=addressed_to,
        has_question=has_question,
        parse_ok=True,
        row_idx=original_id if row_idx is None else row_idx,
    )


def test_gap_starts_new_run():
    # diffs of 1 stay together; a jump of 6 (> GAP_THRESHOLD=5) splits.
    ids = list(range(10)) + list(range(16, 30))
    msgs = [_msg(i, row_idx=k) for k, i in enumerate(ids)]
    out = assign_slices_and_runs(msgs, gap_threshold=GAP_THRESHOLD)
    runs = {m.run_id for m in out}
    assert runs == {0, 1}
    assert max(m.original_id for m in out if m.run_id == 0) == 9
    assert min(m.original_id for m in out if m.run_id == 1) == 16


def test_id_reset_same_date_new_slice():
    a = [_msg(i, row_idx=i) for i in range(5)]
    b = [_msg(i, row_idx=100 + i) for i in range(5)]  # id goes back to 0
    out = assign_slices_and_runs(a + b)
    assert {m.slice_id for m in out} == {0, 1}


def test_windows_do_not_cross_date():
    d1 = [_msg(i, date="2004-12-25", speaker="a", text=f"d1-{i}", row_idx=i) for i in range(20)]
    d2 = [_msg(i, date="2004-12-26", speaker="b", text=f"d2-{i}", row_idx=100 + i) for i in range(20)]
    out = assign_slices_and_runs(d1 + d2)
    windows = emit_windows(out, w=WINDOW_SIZE)
    assert windows
    for w in windows:
        dates = set()
        # chat_block speakers differ by date in this fixture
        assert w.n_messages == WINDOW_SIZE
        assert w.chat_block.count("\n") + 1 == WINDOW_SIZE
        assert w.date in {"2004-12-25", "2004-12-26"}
        ids = w.window_message_ids
        assert ids == sorted(ids)
        assert len(set(ids)) == WINDOW_SIZE


def test_windows_do_not_cross_run():
    left = [_msg(i, row_idx=i) for i in range(20)]
    right = [_msg(i, row_idx=100 + (i - 100)) for i in range(100, 120)]  # big gap
    # simpler: ids 0-19 then 80-99
    right = [_msg(80 + i, row_idx=50 + i) for i in range(20)]
    out = assign_slices_and_runs(left + right, gap_threshold=5)
    windows = emit_windows(out, w=12)
    for w in windows:
        ids = w.window_message_ids
        assert max(ids) - min(ids) == 11  # contiguous ids inside a run of chat msgs


def test_system_excluded_from_windows():
    msgs = []
    for i in range(20):
        msgs.append(
            _msg(
                i,
                speaker="sys" if i % 5 == 0 else "ann",
                text="has joined" if i % 5 == 0 else f"chat {i}",
                is_system=(i % 5 == 0),
                row_idx=i,
            )
        )
    out = assign_slices_and_runs(msgs)
    windows = emit_windows(out, w=12)
    for w in windows:
        assert "has joined" not in w.chat_block
        assert w.n_messages == 12


def test_exact_w_skips_short_runs():
    short = [_msg(i, row_idx=i) for i in range(8)]
    out = assign_slices_and_runs(short)
    windows = emit_windows(out, w=12)
    assert windows == []


def test_thread_overlap_counts_reply_edges():
    msgs = [
        _msg(10, connections=[10], speaker="a"),
        _msg(11, connections=[10], speaker="b"),
        _msg(12, connections=[11, 13], speaker="c"),
    ]
    n = thread_overlap_count(msgs)
    # last=12, connections {11,13}; window ids 10,11,12
    # 11 in last.connections; 12 not in {11,13}; 10 not.
    # last.id in m.connections: 12 in {10}? no; 12 in {10}? wait m1 connections [10]
    # m2 [10] — 12 not in
    # m3 [11,13] — 12 not in (unless we count last's self)
    # 11 is in last.connections → +1
    assert n == 1


def test_twelve_hour_clock_wrap():
    assert minutes_forward("12:59", "01:00") == 1
    assert minutes_forward("23:59", "00:00") == 1
    assert minutes_forward("03:00", "03:02") == 2


def test_chat_block_format():
    msgs = [_msg(i, speaker="Ann" if i % 2 == 0 else "Ken", text=f"line {i}", row_idx=i) for i in range(12)]
    out = assign_slices_and_runs(msgs)
    windows = emit_windows(out, w=12)
    assert len(windows) == 1
    lines = windows[0].chat_block.split("\n")
    assert lines[0].startswith("Ann: ")
    assert windows[0].assistant_named is False
    assert windows[0].label_gold == ""
