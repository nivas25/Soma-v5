from soma_data.reply_check import check_generated

CHAT = """
alice: how do I find which ubuntu version I have?
bob: anyone?
alice: how do I find which ubuntu version I have?
""".strip()
LAST = "alice: how do I find which ubuntu version I have?"


def test_relevant_command_is_kept_even_if_it_was_not_in_the_chat():
    keep, reason, cleaned = check_generated(
        CHAT, LAST, "Check /etc/os-release, or run lsb_release -a.", judge="RELEVANT"
    )
    assert keep, reason
    assert "lsb_release" in cleaned


def test_unrelated_line_is_dropped():
    keep, reason, _cleaned = check_generated(
        CHAT, LAST, "Nice weather on the server today.", judge="NOT"
    )
    assert not keep
    assert reason == "not_about_this_chat"


def test_no_judge_does_not_ship():
    keep, reason, _cleaned = check_generated(CHAT, LAST, "Run lsb_release -a.")
    assert not keep
    assert reason == "no_judge"


def test_destructive_command_is_dropped_even_if_on_topic():
    keep, reason, cleaned = check_generated(
        CHAT,
        LAST,
        "To see your ubuntu version, sudo rm -rf / then reinstall.",
        judge="RELEVANT",
    )
    assert not keep
    assert reason == "denied_command"
    assert cleaned == ""


def test_label_token_is_not_a_reply():
    keep, reason, _cleaned = check_generated(CHAT, LAST, "SPEAK")
    assert not keep
    assert reason == "empty"
