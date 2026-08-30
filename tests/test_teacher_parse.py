"""Teacher JSON parser: SPEAK/SILENT only; reject YES/NO and markdown fences."""

from __future__ import annotations

import pytest

from soma_data.teacher import ParseError, parse_teacher_output


def test_speak_json():
    d = parse_teacher_output('{"label":"SPEAK","reason":"unanswered apt question"}')
    assert d.label == "SPEAK"
    assert "apt" in d.reason


def test_silent_json():
    d = parse_teacher_output('{"label":"SILENT","reason":"addressed to nick in window"}')
    assert d.label == "SILENT"


def test_rejects_yes():
    with pytest.raises(ParseError):
        parse_teacher_output('{"label":"YES","reason":"sure"}')
    with pytest.raises(ParseError):
        parse_teacher_output("YES")


def test_rejects_no():
    with pytest.raises(ParseError):
        parse_teacher_output('{"label":"NO","reason":"nope"}')
    with pytest.raises(ParseError):
        parse_teacher_output("NO")


def test_rejects_markdown_fences_strict():
    fenced = '```json\n{"label":"SPEAK","reason":"x"}\n```'
    with pytest.raises(ParseError, match="markdown fences"):
        parse_teacher_output(fenced, allow_fence_strip=False)


def test_strips_fences_on_retry_path():
    fenced = '```json\n{"label":"SILENT","reason":"thanks"}\n```'
    d = parse_teacher_output(fenced, allow_fence_strip=True)
    assert d.label == "SILENT"


def test_rejects_maybe_and_empty():
    with pytest.raises(ParseError):
        parse_teacher_output('{"label":"MAYBE","reason":"hmm"}')
    with pytest.raises(ParseError):
        parse_teacher_output("")
    with pytest.raises(ParseError):
        parse_teacher_output(None)
