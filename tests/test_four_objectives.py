"""Gate timing stays put. Replies may only repeat a command from the window."""

from soma_data.conflict import find_conflict, proposals
from soma_data.decide import decide
from soma_data.validate_reply import OPEN_REPLY, check_reply

TANGLED = """
jsimmons: can i use aptitude to install a pack I downloaded?
monchichi: LinuxNewbie, sudo addgroup networking; sudo chgrp networking /dev/eth0; sudo chmod 770 /dev/eth0
jeroen_: jsimmons, maybe, but just use dpkg -i
jeroen_: jsimmons, sudo dpkg -i packageblabla.deb
""".strip()

CLASH = """
alice: how do I install foo?
bob: alice, sudo apt-get install foo
carol: alice, sudo aptitude install foo
""".strip()

OPPOSITE = """
alice: how do I install foo?
bob: alice, sudo apt-get install foo
carol: alice, don't apt-get install foo
""".strip()

STEPS = """
alice: how do I install foo?
bob: alice, sudo apt-get update
bob: alice, sudo apt-get install foo
""".strip()

FAILED = """
bob: alice, sudo apt-get install foo
alice: bob, that didn't work
""".strip()


def test_mixed_threads_are_not_a_clash():
    assert find_conflict(TANGLED) is None


def test_same_person_two_tools_is_a_clash():
    found = find_conflict(CLASH)
    assert found is not None
    assert found.kind == "tool_clash"
    assert "apt-get" in found.line_a
    assert "aptitude" in found.line_b


def test_negation_is_a_clash():
    found = find_conflict(OPPOSITE)
    assert found is not None
    assert found.kind == "opposite"


def test_two_steps_from_one_helper_are_not_a_clash():
    assert find_conflict(STEPS) is None


def test_failed_advice_is_a_clash():
    found = find_conflict(FAILED)
    assert found is not None
    assert found.kind == "failed_advice"


def test_prose_mention_is_not_a_command():
    chat = "bob: alice, dpkg created for MySQL to upgrade from 5.5 to 5.7 during build\n"
    assert proposals(chat) == []


def test_strace_line_is_a_command():
    chat = "bob: alice, strace xmms\n"
    found = proposals(chat)
    assert [item.surface for item in found] == ["strace xmms"]


def test_question_does_not_count_as_a_proposed_command():
    assert find_conflict("jsimmons: can i use aptitude to install foo?\n") is None


def test_denied_command_cannot_ship():
    chat = "bob: alice, sudo rm -rf /\n"
    ok, reason = check_reply(chat, "SPEAK", "From this window: sudo rm -rf /")
    assert not ok
    assert reason == "denied_command"


def test_invented_command_cannot_ship():
    ok, reason = check_reply(STEPS, "SPEAK", "From this window: sudo apt-get install bar")
    assert not ok
    assert reason == "ungrounded_command"


def test_verbatim_command_can_ship():
    ok, reason = check_reply(STEPS, "SPEAK", "From this window: sudo apt-get install foo")
    assert ok
    assert reason == ""


def test_silent_cannot_carry_a_reply():
    ok, reason = check_reply(STEPS, "SILENT", "From this window: sudo apt-get install foo")
    assert not ok
    assert reason == "silent_must_be_empty"


def test_speak_quotes_the_asker_command_and_keeps_timing():
    decision = decide("SPEAK", STEPS, asker="alice")
    assert decision.action == "SPEAK"
    assert decision.timing == "SPEAK"
    assert decision.reply == "From this window: sudo apt-get install foo"
    assert decision.drop_reason == ""
    assert "sudo apt-get install foo" in STEPS


def test_clash_is_addressed_without_picking_a_side():
    decision = decide("SPEAK", CLASH, asker="alice")
    assert decision.action == "REPORT_CONFLICT"
    assert decision.timing == "SPEAK"
    assert "Not choosing a command." in decision.reply
    assert "apt-get" in decision.reply
    assert "aptitude" in decision.reply
    ok, reason = check_reply(CLASH, "SPEAK", decision.reply)
    assert ok, reason


def test_silent_stays_silent_but_records_the_clash():
    decision = decide("SILENT", CLASH, asker="alice")
    assert decision.action == "SILENT"
    assert decision.timing == "SILENT"
    assert decision.reply == ""
    assert decision.conflict is True


def test_helper_present_does_not_veto_a_speak():
    decision = decide("SPEAK", STEPS, asker="alice")
    assert decision.timing == "SPEAK"


def test_dangerous_quote_is_redacted():
    chat = "bob: alice, sudo rm -rf /\ncarol: alice, do not rm -rf /\n"
    decision = decide("SPEAK", chat, asker="alice")
    assert decision.action == "REPORT_CONFLICT"
    assert "rm -rf" not in decision.reply
    assert "[blocked]" in decision.reply
    ok, reason = check_reply(chat, "SPEAK", decision.reply)
    assert ok, reason


def test_open_question_with_no_aimed_command_does_not_invent_one():
    chat = "alice: how do I see my ubuntu version?\n"
    decision = decide("SPEAK", chat, asker="alice")
    assert decision.reply == OPEN_REPLY
    assert decision.timing == "SPEAK"
