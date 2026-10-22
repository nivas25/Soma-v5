"""Demo the speak path on four windows. No training. The key stays in the environment."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soma_data.gemini_client import GeminiError  # noqa: E402
from soma_data.speak import compose_reply, find_unanswered  # noqa: E402

OPEN = """
nina: hello
omar: how do I install nginx on ubuntu?
nina: brb
lee: the match is on
""".strip()

OWNED = """
omar: how do I install nginx on ubuntu?
lee: omar, sudo apt-get install nginx
omar: lee: thanks, that worked
""".strip()

OFFTOPIC = """
nina: hello
lee: nice weather today
omar: lunch?
nina: pizza
""".strip()

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


def main() -> None:
    try:
        open_line = find_unanswered(OPEN)
        owned = find_unanswered(OWNED)
        offtopic = find_unanswered(OFFTOPIC)
        disk = compose_reply(DISK)
        clean = compose_reply(CLEAN)
    except GeminiError as exc:
        print(str(exc))
        raise SystemExit(2) from None
    print(f"open: {open_line}")
    print(f"owned: {owned}")
    print(f"offtopic: {offtopic}")
    print(f"disk: {disk.reason or 'shown'} reply={disk.reply!r}")
    print(f"clean: {clean.reason or 'shown'} reply={clean.reply!r}")
    if not open_line.startswith("2:") or "nginx" not in open_line:
        raise SystemExit("open window did not return the nginx question")
    if owned != "NONE" or offtopic != "NONE":
        raise SystemExit("owned or offtopic window should be NONE")
    if disk.reply:
        raise SystemExit("disk conflict should stay silent")
    if not clean.reply:
        raise SystemExit(f"clean question was silenced: {clean.reason}")
    print("demo ok")


if __name__ == "__main__":
    main()
