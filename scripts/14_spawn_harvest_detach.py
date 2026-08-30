"""Spawn harvest_until as a detached Modal job. Volume must already have snapshot+pending."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import modal  # noqa: E402
from soma_data.modal_teacher import Teacher, app  # noqa: E402


def main() -> None:
    with modal.enable_output():
        with app.run(detach=True) as running:
            T = Teacher.with_options(timeout=10 * 60 * 60, max_containers=1)
            call = T().harvest_until.spawn()
            cid = getattr(call, "object_id", None) or str(call)
            aid = getattr(running, "app_id", None) or getattr(app, "app_id", None)
            print(f"DETACHED_APP_ID={aid}", flush=True)
            print(f"DETACHED_CALL_ID={cid}", flush=True)
            print(
                "YES you can close the lid. Loop is inside one Modal GPU function; resume-only.",
                flush=True,
            )


if __name__ == "__main__":
    main()
