# Friend holdout — Manu 200 / Punith 200

These 400 windows are **not gold yet**. They are a frozen holdout.
They are **not** in Nivas test (audit_200) and **not** in train 1:1 or train 1:3.

## Files

- **Manu:** `data/friends/manu_200.csv` (n=200; addressed_not_question=65, other=75, question=60)
- **Punith:** `data/friends/punith_200.csv` (n=200; addressed_not_question=68, other=59, question=73)
- Combined ids: `data/friends/friend_400_ids.txt` (Manu first, then Punith)

## Rules

- Do **not** look at Qwen / teacher labels. The CSVs have `label_silver` empty on purpose.
- Do **not** share sheets. Manu does not open Punith's file and vice versa.
- `label_gold`, `labeler`, `reviewed_by`, `review_ok` start empty. The UI fills them.
- Nivas 200 is test-only. Friends never go into train.

## How to label (do not run until you are the annotator)

```
uv run python scripts/07_label_ui.py --annotator manu
uv run python scripts/07_label_ui.py --annotator punith
```

Or start without a flag and click **Manu** / **Punith** / **Nivas** on the start screen.
Finish writes `data/friends/{name}_done.csv` and `{name}_done.jsonl`.

Seed=42. Stratified question / addressed_not_question / other from unlabeled queue rows.
