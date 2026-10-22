"""Send each gate-SPEAK window to the frozen 7B, then keep the line only if it is about that chat.

SILENT rows are not sent. No training.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soma_data.conflict import find_conflict  # noqa: E402
from soma_data.reply_check import check_generated  # noqa: E402

PREDS = ROOT / "reports" / "lora_run" / "reports" / "test_200_predictions.csv"
TEST = ROOT / "data" / "processed" / "sft_test.jsonl"
DRAFTS = ROOT / "reports" / "v5_llm_drafts.jsonl"
OUT_CSV = ROOT / "reports" / "v5_llm_replies.csv"
OUT_MD = ROOT / "reports" / "v5_llm_replies.md"


def _chat(sft_input: str) -> str:
    start = sft_input.find("CHAT:\n")
    end = sft_input.find("\n\nDecide AFTER", start)
    if start < 0 or end < 0:
        raise ValueError("sft input has no CHAT block")
    return sft_input[start + len("CHAT:\n") : end]


def _last(chat: str) -> str:
    lines = [ln.strip() for ln in chat.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def _load_rows() -> list[dict]:
    gold = {}
    with TEST.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            gold[row["window_id"]] = row
    items = []
    with PREDS.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            src = gold[raw["window_id"]]
            chat = _chat(src["input"])
            clash = find_conflict(chat) if raw["pred"] == "SPEAK" else None
            note = ""
            if clash is not None:
                note = f'Two lines disagree: "{clash.line_a}" / "{clash.line_b}". Do not pick a side.'
            items.append(
                {
                    "window_id": raw["window_id"],
                    "gold": raw["gold"],
                    "pred": raw["pred"],
                    "question": raw["question"],
                    "helper_in_window": raw["helper_in_window"],
                    "chat": chat,
                    "last_line": _last(chat),
                    "note": note,
                }
            )
    return items


def _write_outputs(rows: list[dict]) -> None:
    fields = [
        "window_id",
        "gold",
        "pred",
        "question",
        "helper_in_window",
        "draft",
        "judge",
        "reply",
        "keep",
        "drop_reason",
    ]
    with OUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})
    kept = [r for r in rows if r["pred"] == "SPEAK" and r["keep"] == "yes"]
    dropped = [r for r in rows if r["pred"] == "SPEAK" and r["keep"] != "yes"]
    lines = [
        "# LLM replies on gate SPEAK",
        "",
        "Frozen `Qwen/Qwen2.5-7B-Instruct`, no LoRA, temperature 0. "
        "Called only where step 1200 said SPEAK. The same model then answers RELEVANT or NOT. "
        "A destructive command is dropped even if the judge says RELEVANT.",
        "",
        f"SPEAK sent to the model: {sum(1 for r in rows if r['pred'] == 'SPEAK')}",
        f"Kept: {len(kept)}",
        f"Dropped: {len(dropped)}",
        "",
        "## Kept replies",
        "",
    ]
    if not kept:
        lines.append("- none")
    for row in kept:
        lines.append(f"- `{row['window_id']}`")
        lines.append(f"  - last: {row['last_line']}")
        lines.append(f"  - reply: {row['reply']}")
    lines += ["", "## Dropped drafts", ""]
    if not dropped:
        lines.append("- none")
    for row in dropped:
        lines.append(f"- `{row['window_id']}` ({row['drop_reason']})")
        lines.append(f"  - last: {row['last_line']}")
        lines.append(f"  - draft: {row['draft']}")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def finish_from_drafts(drafts: dict[str, dict]) -> None:
    rows = []
    for item in _load_rows():
        if item["pred"] != "SPEAK":
            rows.append(
                {**item, "draft": "", "judge": "", "reply": "", "keep": "no", "drop_reason": "gate_silent"}
            )
            continue
        got = drafts.get(item["window_id"], {})
        draft = got.get("draft") or ""
        judge = got.get("judge") or ""
        keep, reason, cleaned = check_generated(item["chat"], item["last_line"], draft, judge)
        rows.append(
            {
                **item,
                "draft": " ".join(draft.split()),
                "judge": judge,
                "reply": cleaned if keep else "",
                "keep": "yes" if keep else "no",
                "drop_reason": reason,
            }
        )
    _write_outputs(rows)
    kept = sum(1 for r in rows if r["keep"] == "yes")
    print(f"kept={kept} speak={sum(1 for r in rows if r['pred'] == 'SPEAK')} wrote {OUT_MD}")


def main() -> None:
    import modal

    from soma_data.modal_writer import app, write_replies

    items = _load_rows()
    pending = [
        {"window_id": r["window_id"], "chat": r["chat"], "last_line": r["last_line"], "note": r["note"]}
        for r in items
        if r["pred"] == "SPEAK"
    ]
    print(f"SEND {len(pending)} SPEAK windows")
    with modal.enable_output():
        with app.run():
            drafts = write_replies.remote(pending)
    DRAFTS.parent.mkdir(parents=True, exist_ok=True)
    with DRAFTS.open("w", encoding="utf-8") as handle:
        for row in drafts:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"drafts={len(drafts)} file={DRAFTS}")
    finish_from_drafts({row["window_id"]: row for row in drafts})


if __name__ == "__main__":
    main()
