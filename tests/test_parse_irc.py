"""IRC regex fixtures — at least 8 shapes from Ubuntu logs / Kummerfeld files."""

from __future__ import annotations

from soma_data.parse_irc import extract_addressed_to, is_thanks, parse_raw_line


def test_normal_privmsg():
    p = parse_raw_line(
        "[03:57] <Xophe> (also, I'm guessing that this isn't a good place to report minor but annoying bugs... what is?)"
    )
    assert p["parse_ok"]
    assert p["time_hhmm"] == "03:57"
    assert p["speaker"] == "Xophe"
    assert p["text"].startswith("(also, I'm guessing")
    assert p["has_question"] is True
    assert p["is_system"] is False
    assert p["is_action"] is False
    assert p["addressed_to"] is None


def test_address_pattern():
    p = parse_raw_line("[09:14] <crimsun> kleedrac: I'm afraid not. Any version of mplayer except for -k7*")
    assert p["speaker"] == "crimsun"
    assert p["addressed_to"] == "kleedrac"
    assert p["has_question"] is False


def test_question_unaddressed():
    p = parse_raw_line("[09:14] <intinig> does a subversion gnome client exist?")
    assert p["speaker"] == "intinig"
    assert p["has_question"] is True
    assert p["addressed_to"] is None


def test_join_system():
    p = parse_raw_line("=== L0sT [~waa3@raptor.ukc.ac.uk]  has joined #ubuntu")
    assert p["parse_ok"]
    assert p["is_system"] is True
    assert p["is_action"] is False
    assert p["speaker"] == "L0sT"
    assert p["time_hhmm"] is None


def test_left_system():
    p = parse_raw_line('=== xgogol [~bernd@p5085D851.dip0.t-ipconnect.de]  has left #ubuntu ["Verlassend"]')
    assert p["is_system"] is True
    assert p["speaker"] == "xgogol"


def test_nick_change_system():
    p = parse_raw_line("=== sid77 is now known as sid77_")
    assert p["is_system"] is True
    assert p["speaker"] == "sid77"
    assert p["is_action"] is False


def test_weird_nick_pipe_and_address():
    p = parse_raw_line("[09:15] <|QuaD-> will: totem has caused me no troubles")
    assert p["speaker"] == "|QuaD-"
    assert p["addressed_to"] == "will"
    assert p["is_system"] is False


def test_action_equals_not_system():
    """Ubuntu logger writes /me as `=== nick rest` without a hostmask/event verb."""
    p = parse_raw_line("=== sid77 hi")
    assert p["is_system"] is False
    assert p["is_action"] is True
    assert p["speaker"] == "sid77"
    assert p["text"] == "hi"


def test_action_star_with_timestamp():
    p = parse_raw_line("[12:03] * tuppa tries again")
    assert p["is_action"] is True
    assert p["is_system"] is False
    assert p["speaker"] == "tuppa"
    assert p["text"] == "tries again"
    assert p["time_hhmm"] == "12:03"


def test_backtick_nick_join():
    p = parse_raw_line("=== `anthony [~anthony@213.151.107.243]  has joined #ubuntu")
    assert p["is_system"] is True
    assert p["speaker"] == "`anthony"


def test_http_is_not_address():
    p = parse_raw_line("[10:00] <foo> http://example.com is down")
    assert p["addressed_to"] is None
    assert extract_addressed_to("http://example.com is down") is None


def test_channel_two_entered_is_system():
    p = parse_raw_line("=== Nella entered the room.")
    assert p["is_system"] is True
    assert p["is_action"] is False
    assert p["speaker"] == "Nella"


def test_channel_two_left_room_is_system():
    p = parse_raw_line("=== Alice left the room (quit: Client Quit).")
    assert p["is_system"] is True
    assert p["speaker"] == "Alice"


def test_mode_line_is_system():
    p = parse_raw_line("=== mode/#ubuntu [+o Seveas]  by ChanServ")
    assert p["is_system"] is True
    assert p["is_action"] is False


def test_notice_is_system():
    p = parse_raw_line("[01:09] (soundray/#ubuntu) thomas: have you seen http://ubuntuforums.org/showthread.php?t=261065 ?")
    assert p["is_system"] is True
    assert p["speaker"] == "soundray"
    assert p["time_hhmm"] == "01:09"


def test_empty_line_excluded_as_system():
    p = parse_raw_line("")
    assert p["parse_ok"] is False
    assert p["is_system"] is True


def test_thanks_regex():
    assert is_thanks("thanks everyone")
    assert is_thanks("thx")
    assert is_thanks("works now")
    assert is_thanks("fixed")
    assert is_thanks("solved it")
    assert not is_thanks("how do I mount this")
