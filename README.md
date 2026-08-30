---
language:
- en
license: mit
tags:
- text-classification
- lora
- ubuntu-irc
datasets:
- jkkummerfeld/irc_disentangle
---
# SOMA gate

A **SPEAK | SILENT** helper-bot gate for multi-party Ubuntu IRC. A 7B LoRA student decides whether an extra helper should talk **after the last line** of a 12-line window. It is **not** a Theory-of-Mind stack, not PPO, not emotion, and not a reply writer.

Default is SILENT. A frozen writer (out of scope here) would run only if the gate says SPEAK.

## Data

Upstream logs: [`jkkummerfeld/irc_disentangle`](https://huggingface.co/datasets/jkkummerfeld/irc_disentangle) — Kummerfeld et al., ACL 2019 ([P19-1374](https://aclanthology.org/P19-1374/) / [arXiv:1810.11118](https://arxiv.org/abs/1810.11118)). **CC-BY-4.0.** One Hub row is one IRC line (`id`, `raw`, `ascii`, `tokenized`, `date`, `connections`).

We **add** SPEAK/SILENT labels. Hub has none. Not Lowe/McGill Ubuntu Dialogue Corpus.

You must accept the Hugging Face dataset license to download raw dumps. This clone does **not** ship those parquets.

## What is in this clone vs not

| In the clone | Not in the clone (rebuild or request) |
| --- | --- |
| Code (`src/`, `scripts/01–17`, `tests/`) | `data/raw/*.parquet` (IRC dumps) |
| 200 **gold** windows (`data/silver/audit_200.csv`, `sft_test.jsonl`) | ~21k teacher silver jsonl |
| Friend holdout CSVs (gold **empty**) | LoRA adapter / `.safetensors` |
| Reports + figures | `sft_train_1to3.jsonl` (~28 MB silver; rebuild after harvest) |

Train file is gitignored even though it is under 50 MB: it is teacher-labeled IRC text, not gold. Rebuild with harvest + `scripts/15_export_sft_and_eda.py` + `scripts/16_freeze_friends_and_splits.py`, or request from the authors.

## Pipeline

| script | role |
| --- | --- |
| `01_download.py` | Hub snapshots → `data/raw/` |
| `02_analyze.py` | parse + EDA → `messages.parquet` |
| `03_build_windows.py` | exact **W=12** windows |
| `04_export.py` | 30k `label_queue` (gold empty) |
| `05_select_pilot_2k.py` | freeze 2k ids |
| `06_silver_label_pilot.py` | Qwen-32B v1 silver on 2k (**not** mixed into train) |
| `07_audit_sample.py` | freeze 200 for human audit |
| `07_label_ui.py` | local gold UI |
| `08_apply_reviewed_gold.py` | copy 200 gold onto the queue |
| `09` / `10` / `11` Gate 1 | teacher vs gold: v2 73.5% → v2.1 77.5% → **v2.2 85.5% PASS** |
| `12`–`14` harvest | v2.2 silver 5,100 SPEAK / 16,250 SILENT |
| `15_export_sft_and_eda.py` | 1:1 SFT + paper EDA |
| `16_freeze_friends_and_splits.py` | **1:3 train**, 400 friend holdout |
| `17_launch_lora_train.py` | 7B LoRA on Modal H100 |

No stemming, lemmatizing, stopwords, or lowercasing. See `reports/data_preprocessing.md`.

## Setup

Python 3.12 (3.11+). [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
cp .env.example .env   # HF_TOKEN if you download Hub data
uv run pytest
```

Download + windows (needs Hub token, writes large parquets locally):

```bash
uv run python scripts/01_download.py
uv run python scripts/02_analyze.py
uv run python scripts/03_build_windows.py
uv run python scripts/04_export.py
```

Teacher harvest and LoRA need Modal credentials. Do not commit `.env`.

## Results (200 gold test)

Best LoRA checkpoint **step 1200**. Mapping Silent=0, Speak=1.

| method | Macro-F1 | Speak-F1 | Silent-F1 |
| --- | ---: | ---: | ---: |
| **LoRA 7B** | **0.878** | **0.861** | **0.895** |
| B3 question ∧ ¬helper | 0.775 | 0.716 | 0.833 |
| B2 question | 0.682 | 0.652 | 0.712 |
| B1 always SILENT | 0.355 | 0.000 | 0.710 |

Confusion: TN 102, FP 8, FN 16, TP 74. Details: `reports/training_eval.md`.

## License

- **Code:** MIT (`LICENSE`)
- **Upstream IRC data:** CC-BY-4.0 (Kummerfeld et al. 2019). Users must accept the Hub license before `01_download.py`.

## Authors

PES University capstone — **SOMA** (Synthetic Orchestrator for Meaningful Assistance). Gate only: SPEAK/SILENT on Ubuntu IRC, not ToM/PPO.
