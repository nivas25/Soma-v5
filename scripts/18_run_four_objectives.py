"""Run the four-objective closeout on the frozen 200. No training. No Modal.

Timing is the already scored LoRA column. This script does not flip SPEAK to
SILENT. It records thread-scoped clashes and writes a reply that can only
repeat a command already in the window.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soma_data.decide import decide  # noqa: E402
from soma_data.validate_reply import OPEN_REPLY, check_reply  # noqa: E402

PREDS = ROOT / "reports" / "lora_run" / "reports" / "test_200_predictions.csv"
TEST = ROOT / "data" / "processed" / "sft_test.jsonl"
OUT_CSV = ROOT / "reports" / "v5_four_objectives.csv"
OUT_MD = ROOT / "reports" / "v5_four_objectives.md"


def _chat(sft_input: str) -> str:
    start = sft_input.find("CHAT:\n")
    end = sft_input.find("\n\nDecide AFTER", start)
    if start < 0 or end < 0:
        raise ValueError("sft input has no CHAT block")
    return sft_input[start + len("CHAT:\n") : end]


def _field(sft_input: str, name: str) -> str:
    prefix = f"{name}="
    for line in sft_input.splitlines():
        for part in line.split():
            if part.startswith(prefix):
                return part[len(prefix) :].strip()
    return ""


def main() -> None:
    gold_rows = {}
    with TEST.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            gold_rows[row["window_id"]] = row

    written = []
    with PREDS.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            src = gold_rows[raw["window_id"]]
            chat = _chat(src["input"])
            asker = _field(src["input"], "last_speaker")
            also = _field(src["input"], "addressed_to")
            decision = decide(raw["pred"], chat, asker=asker, also=also)
            if decision.timing != raw["pred"]:
                raise SystemExit(
                    f"timing changed for {raw['window_id']}: {raw['pred']} -> {decision.timing}"
                )
            ok, reason = check_reply(
                chat, "SILENT" if decision.action == "SILENT" else "SPEAK", decision.reply
            )
            if not ok:
                raise SystemExit(f"reply failed validation {raw['window_id']}: {reason}")
            written.append(
                {
                    "window_id": raw["window_id"],
                    "gold": raw["gold"],
                    "pred": raw["pred"],
                    "question": raw["question"],
                    "helper_in_window": raw["helper_in_window"],
                    "action": decision.action,
                    "conflict": "yes" if decision.conflict else "no",
                    "conflict_kind": decision.conflict_kind,
                    "evidence_a": decision.evidence_a,
                    "evidence_b": decision.evidence_b,
                    "reply": decision.reply,
                    "drop_reason": decision.drop_reason,
                }
            )

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = list(written[0])
    with OUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(written)

    n = len(written)
    pred_speak = [r for r in written if r["pred"] == "SPEAK"]
    clashes = [r for r in written if r["conflict"] == "yes"]
    addressed = [r for r in pred_speak if r["action"] == "REPORT_CONFLICT"]
    quoted = [r for r in pred_speak if r["reply"].startswith("From this window:")]
    opened = [r for r in pred_speak if r["reply"] == OPEN_REPLY]
    silent_clash = [r for r in written if r["pred"] == "SILENT" and r["conflict"] == "yes"]
    kinds = Counter(r["conflict_kind"] for r in clashes)

    examples = []
    for row in clashes:
        examples.append(
            f"- `{row['window_id']}` gate={row['pred']} action={row['action']} ({row['conflict_kind']})\n"
            f"  - {row['evidence_a']}\n"
            f"  - {row['evidence_b']}"
        )
    example_block = "\n".join(examples) if examples else "- none"
    quotes = []
    for row in quoted:
        quotes.append(f"- `{row['window_id']}` {row['reply']}")
    quote_block = "\n".join(quotes) if quotes else "- none"

    text = f"""# SOMA v5 four-objective closeout

No retraining. Timing is the frozen step-1200 column in `reports/lora_run/reports/test_200_predictions.csv`. This run refused to flip any SPEAK to SILENT. `helper_in_window` is not a veto: on this file the 8 false speaks all have helper=no, so that veto cannot catch them, and it would silence true speaks that already have a helper.

A clash is two different speakers, the same addressee (or the same package/path when neither line names one), and a real disagreement. Commands in two tangled threads are not a clash.

| item | n |
| --- | ---: |
| windows | {n} |
| gate SPEAK (unchanged) | {len(pred_speak)} |
| gate SILENT (unchanged) | {n - len(pred_speak)} |
| clashes recorded | {len(clashes)} |
| SPEAK rows addressed as REPORT_CONFLICT | {len(addressed)} |
| SPEAK rows quoting one in-window command | {len(quoted)} |
| SPEAK rows with no safe command to repeat | {len(opened)} |
| SILENT rows that still record a clash | {len(silent_clash)} |
| replies that failed the filter | 0 |

Clash kinds: {", ".join(f"{k}={v}" for k, v in sorted(kinds.items())) or "none"}.

Every non-silent reply passed `check_reply`: no denylisted command, and every command span is a substring of that window. Gate macro-F1 is still **0.8776** from `reports/lora_run/reports/test_metrics.json`. This table does not replace that number.

{len(opened)} of the {len(pred_speak)} SPEAK rows have no command in the window aimed at the asker. Those replies refuse to invent one. The window `ubuntu:test:2005-07-06:0:0:274` contains both `chmod` and `dpkg` on different threads and is not flagged.

## Commands repeated from the window

{quote_block}

## Clashes recorded

{example_block}
"""
    OUT_MD.write_text(text, encoding="utf-8")
    print(f"wrote {OUT_CSV}")
    print(f"wrote {OUT_MD}")
    print(
        f"n={n} speak={len(pred_speak)} clash={len(clashes)} "
        f"addressed={len(addressed)} quoted={len(quoted)} open={len(opened)}"
    )


if __name__ == "__main__":
    main()
