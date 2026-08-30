# Split card — SOMA v2.2 freeze

No LoRA. Friends are **not gold yet**. First experiment uses Nivas 200 as the only test.

## Counts

| file | n | SPEAK | SILENT | SPEAK % | overlap_test | overlap_friends |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| sft_train_1to1.jsonl | 10200 | 5100 | 5100 | 50.0% | 0 | 0 |
| sft_train_1to3.jsonl | 20400 | 5100 | 15300 | 25.0% | 0 | 0 |
| sft_test.jsonl | 200 | 90 | 110 | 45.0% | 0 | 0 |
| friend_400 | 400 | 0 | 0 | 0.0% | 0 | 0 |

- train 1:1 ∩ train 1:3 = 9897 (expected: same 5,100 SPEAK plus shared SILENT; not a leak)
- train 1:1 ∩ test = 0
- train 1:3 ∩ test = 0
- train 1:1 ∩ friend400 = 0
- train 1:3 ∩ friend400 = 0
- test ∩ friend400 = 0
- friend source: `unlabeled_queue` (Qwen labels not copied onto friend CSVs)
- friend strata: {'addressed_not_question': 133, 'other': 134, 'question': 133}
- Manu strata: {'addressed_not_question': 65, 'other': 75, 'question': 60}
- Punith strata: {'other': 59, 'question': 73, 'addressed_not_question': 68}

## Experiment plan

Primary run is **train 1:3** (5,100 SPEAK + 15,300 SILENT, closer to the room prior ~24% SPEAK) and the ablation is **train 1:1** (5,100 / 5,100, 50% SPEAK). Test is **Nivas 200 gold only** (90 SPEAK / 110 SILENT, 45.0% SPEAK). The 400 friend windows (Manu 200, Punith 200) stay unlabeled holdout until after that result; they are future test B, not a training mix and not gold today.

prompt_version=`pilot_v2.2`. Train source=`qwen32_v2.2`. Test source=`nivas_gold`. Seed=42.

sft_dev.jsonl is empty (`# friends 400 after they label — future test B`).

Label UI (do not start it from this freeze): `uv run python scripts/07_label_ui.py --annotator manu`
