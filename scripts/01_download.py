"""Step 1 — login, print 20 sample rows, snapshot every useful config/split to parquet."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.pretty import Pretty

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soma_data.config import HF_DATASET, ensure_dirs, hf_token, masked_token  # noqa: E402
from soma_data.hf_download import download_all, login_hub, sample_rows  # noqa: E402
from soma_data.quality import assert_no_hf_token_in_tree  # noqa: E402


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    ensure_dirs()
    token = hf_token()
    logger.info("HF_TOKEN present ({}) — never printed in full", masked_token(token))

    login_hub(token)
    console = Console()
    console.rule("20 sample rows — ubuntu/train")
    rows = sample_rows("ubuntu", "train", 20, token)
    for row in rows:
        # Compact print: id, date, connections, raw
        console.print(
            Pretty(
                {
                    "id": row.get("id"),
                    "date": row.get("date"),
                    "connections": row.get("connections"),
                    "raw": row.get("raw"),
                },
                max_string=200,
            )
        )
    console.rule("full download")
    manifest = download_all(token, force="--force" in sys.argv)
    console.print(json.dumps({k: manifest[k] for k in ("configs_on_hub", "configs_kept", "configs_skipped")}, indent=2))
    for s in manifest["splits"]:
        console.print(
            f"  {s['config']}/{s['split']}: {s['n_rows']} rows "
            f"(nonempty connections={s['n_annotated_nonempty_connections']}, "
            f"card_annotated={s['card_annotated']})"
        )
    assert_no_hf_token_in_tree()
    logger.info("01_download complete. Dataset={} configs={}", HF_DATASET, manifest["configs_kept"])


if __name__ == "__main__":
    main()
