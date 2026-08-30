# SOMA gate — human audit sheet (200 windows)

Rubber-stamp review was **reset**. Honest re-label in the local UI:

```bash
uv run python scripts/07_label_ui.py
```

Open http://127.0.0.1:7860

Backup: `data/silver/audit_200.bak.csv`
Does not write `label_queue.csv` until you click **Export gold to label_queue**.
