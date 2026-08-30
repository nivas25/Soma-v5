"""Local labelling UI. Do not launch unless you are the annotator.

  uv run python scripts/07_label_ui.py --annotator manu
  uv run python scripts/07_label_ui.py --annotator punith
  uv run python scripts/07_label_ui.py --annotator nivas

No flag → start screen [Manu] [Punith] [Nivas].
Each click writes that person's csv (label_gold, reviewed_by, review_ok=Y).
Finish → data/friends/{name}_done.csv and {name}_done.jsonl.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rich.console import Console  # noqa: E402

from soma_data.config import LABEL_UI_HOST, LABEL_UI_PORT  # noqa: E402
from soma_data.label_store import ANNOTATORS, get_store  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="SOMA local label UI")
    parser.add_argument(
        "--annotator",
        choices=list(ANNOTATORS),
        default=None,
        help="manu | punith | nivas. Omit to pick on the start screen.",
    )
    args = parser.parse_args()
    console = Console()
    if args.annotator:
        os.environ["SOMA_ANNOTATOR"] = args.annotator
        store = get_store(args.annotator)
        console.print(f"annotator=[bold]{args.annotator}[/bold]  sheet={store.path}")
        if store.reset_happened:
            console.print("[yellow]backed up[/yellow] and reset gold flags (Nivas first launch)")
        c = store.counts()
        console.print(f"rows={c['n']} labelled={c['done']} remaining={c['empty']}")
    else:
        console.print("no --annotator: open the start screen and click Manu / Punith / Nivas")
    url = f"http://{LABEL_UI_HOST}:{LABEL_UI_PORT}"
    console.print(f"[bold green]SOMA label[/bold green]  {url}")
    console.print("S speak · L silent · C copy · arrows prev/next · U undo")
    console.print("Copy does not write gold. SPEAK/SILENT clicks still save.")
    import uvicorn

    from soma_data.label_app import app

    uvicorn.run(app, host=LABEL_UI_HOST, port=LABEL_UI_PORT, log_level="info")


if __name__ == "__main__":
    main()
