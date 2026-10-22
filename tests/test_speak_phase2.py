"""Phase 2: a draft is shown only when overlap, contradiction, and docs agree."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from soma_data.gemini_client import GeminiClient
from soma_data.speak import compose_reply
from soma_data.speak_validate import _manual_text, command_already_in_window, command_surfaces

DISK = """
arog: i just ran df -h and I noticed:: /dev/sda1       909G   15G  848G   2% /
arog: why is my size so large (909gb) but my available is only 848gb
arog: I find it difficult to believe ubuntu takes up almost 60gb
mxvxrts: arog, partition sizes are counted in two ways that is about right.
arog: mxvxrts: so from 900gb almost 50gb gets used up?!
mxvxrts: arog, THat is to full anyway
Ben64: arog: it probably is reserved space
arog: what do you mean
mxvxrts: arog, It is not crazy it is the way it is look it up.
arog: got a link?
mxvxrts: arog, The difference is 1000MB for a gig and 1024 for a gig if I have the numbers correct.
Ben64: arog: by default 5% of a filesystem is reserved for root, 5% of 909G is 45.45G, 45.45+15+848=908.45
""".strip()

CLEAN = """
nina: hi
lee: hello
omar: anyone here good with ubuntu?
nina: yep
omar: how do I check which version of ubuntu I am running?
lee: brb
nina: ok
lee: back
nina: still here
omar: still stuck on the version question
lee: hmm
nina: no idea
""".strip()

_QUESTION = "5: omar: how do I check which version of ubuntu I am running?"
_SNIPPET = (
    "DESCRIPTION lsb_release prints distribution-specific information. "
    "-a --all Show all of the above information, including the release."
)


class _Script:
    def __init__(self, steps: dict[str, dict]) -> None:
        self.steps = steps
        self.kinds: list[str] = []

    def __call__(self, prompt: str) -> str:
        if prompt.startswith("You select one unanswered"):
            kind = "find"
        elif prompt.startswith("Draft ONE short"):
            kind = "draft"
        elif prompt.startswith("Does this reply contradict"):
            kind = "contradict"
        elif prompt.startswith("Does this official"):
            kind = "doc"
        else:
            raise AssertionError(prompt[:80])
        self.kinds.append(kind)
        return json.dumps(self.steps[kind])


def _client(steps: dict[str, dict]) -> tuple[GeminiClient, _Script]:
    script = _Script(steps)
    return GeminiClient(transport=script), script


def _fetch_ok(_url: str) -> str:
    return _SNIPPET


def _fetch_miss(_url: str) -> None:
    return None


def test_man_page_text_starts_at_the_heading():
    page = (
        "<nav>DESCRIPTION SYNOPSIS df -h</nav>"
        "<h1>lsb_release</h1><p>-a, --all Show all of the above information.</p>"
        "<p>-r, --release Show release number of this distribution.</p>"
        "<footer>end</footer>"
    )
    text = _manual_text(page)
    assert text.startswith("lsb_release")
    assert "-a, --all" in text
    assert "df -h" not in text


def test_plain_word_free_is_not_a_command():
    draft = "You can check free disk space by running `df -h` in the terminal."
    assert command_surfaces(draft) == ["df -h"]
    assert not command_already_in_window(draft, "Arun: how do I check free disk space on ubuntu?")


def test_command_overlap_sees_df_already_in_the_disk_window():
    assert command_surfaces("Run `df -h` again.") == ["df -h"]
    assert command_already_in_window("Run `df -h` again.", DISK)
    assert not command_already_in_window("Run `lsb_release -a`.", CLEAN)


def test_disk_repeat_is_blocked_before_the_model_checks():
    client, script = _client(
        {
            "find": {
                "result": "LINE",
                "line": 2,
                "text": "arog: why is my size so large (909gb) but my available is only 848gb",
            },
            "draft": {"reply": "Run `df -h` again to see the same numbers."},
        }
    )
    outcome = compose_reply(DISK, client=client, fetch=_fetch_ok)
    assert outcome.reply == ""
    assert outcome.shown is False
    assert outcome.reason == "command_in_window"
    assert "contradict" not in script.kinds
    assert "doc" not in script.kinds


def test_contradiction_yes_blocks_and_skips_the_doc_filter():
    client, script = _client(
        {
            "find": {
                "result": "LINE",
                "line": 2,
                "text": "arog: why is my size so large (909gb) but my available is only 848gb",
            },
            "draft": {"reply": "Ubuntu is using about 60GB and the disk is full."},
            "contradict": {"contradicts": "YES"},
        }
    )
    outcome = compose_reply(DISK, client=client, fetch=_fetch_ok)
    assert outcome.reply == ""
    assert outcome.reason == "contradicts"
    assert script.kinds == ["find", "draft", "contradict"]


def test_doc_snippet_that_does_not_support_the_reply_blocks():
    client, script = _client(
        {
            "find": {"result": "LINE", "line": 5, "text": _QUESTION.split(": ", 1)[1]},
            "draft": {"reply": "Run `lsb_release -a`."},
            "contradict": {"contradicts": "NO"},
            "doc": {"supports": "NO"},
        }
    )
    outcome = compose_reply(CLEAN, client=client, fetch=_fetch_ok)
    assert outcome.reply == ""
    assert outcome.reason == "doc_unsupported"
    assert script.kinds == ["find", "draft", "contradict", "doc"]


def test_clean_draft_passes_when_every_check_passes():
    client, script = _client(
        {
            "find": {"result": "LINE", "line": 5, "text": _QUESTION.split(": ", 1)[1]},
            "draft": {"reply": "Run `lsb_release -a`."},
            "contradict": {"contradicts": "NO"},
            "doc": {"supports": "YES"},
        }
    )
    outcome = compose_reply(CLEAN, client=client, fetch=_fetch_ok)
    assert outcome.shown is True
    assert outcome.reply == "Run `lsb_release -a`."
    assert outcome.reason == ""
    assert script.kinds == ["find", "draft", "contradict", "doc"]


def test_missing_snippet_skips_the_optional_filter():
    client, _script = _client(
        {
            "find": {"result": "LINE", "line": 5, "text": _QUESTION.split(": ", 1)[1]},
            "draft": {"reply": "Run `lsb_release -a`."},
            "contradict": {"contradicts": "NO"},
        }
    )
    outcome = compose_reply(CLEAN, client=client, fetch=_fetch_miss)
    assert outcome.reply == "Run `lsb_release -a`."
    assert outcome.reason == ""


def test_destructive_draft_is_silenced():
    client, script = _client(
        {
            "find": {"result": "LINE", "line": 5, "text": _QUESTION.split(": ", 1)[1]},
            "draft": {"reply": "sudo rm -rf /"},
        }
    )
    outcome = compose_reply(CLEAN, client=client, fetch=_fetch_ok)
    assert outcome.reply == ""
    assert outcome.reason == "denied_command"
    assert "contradict" not in script.kinds


def test_silent_gate_makes_no_model_call():
    client, script = _client({"find": {"result": "LINE", "line": 5, "text": "x"}})
    outcome = compose_reply(CLEAN, gate="SILENT", client=client)
    assert outcome.gate == "SILENT"
    assert outcome.reply == ""
    assert outcome.reason == "gate_silent"
    assert script.kinds == []


def test_gemini_key_is_not_in_the_tree():
    root = Path(__file__).resolve().parents[1]
    pattern = re.compile(r"AQ\.[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{10,}")
    skip = {".git", ".venv", "venv", "__pycache__", "node_modules", "data", "models", "huggingface"}
    hits: list[str] = []
    for path in root.rglob("*"):
        if any(part in skip for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".py", ".md", ".toml", ".txt", ".json", ".example", ".tsx", ".ts", ".css"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            hits.append(str(path.relative_to(root)))
    assert hits == []


@pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="GEMINI_API_KEY is not set")
def test_live_disk_blocks_and_clean_question_passes():
    disk = compose_reply(DISK)
    clean = compose_reply(CLEAN)
    assert disk.reply == "", (disk.reason, disk.question, disk.draft)
    assert disk.shown is False
    assert clean.reply, (clean.reason, clean.question, clean.draft)
    assert clean.shown is True
    assert clean.reason == ""
    assert not command_already_in_window(clean.reply, CLEAN)
