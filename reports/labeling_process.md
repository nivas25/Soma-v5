# How SPEAK / SILENT labels were produced

Panel report. Soma-v5 only. Hub IRC has **no** SPEAK/SILENT. Those two tokens are ours.

Verified on disk (2026-08-30): `data/silver/audit_200.csv`, `data/silver/pilot_v2_2_labels.jsonl`, `data/processed/sft_train_1to3.jsonl`, `data/processed/sft_test.jsonl`, `data/friends/*.csv`, `reports/pilot_v2*_gate1.md`, `reports/split_card.md`. Where `reports/dataset_eda.md` Table 1 still describes the earlier 1:1 export, **split_card + jsonl on disk** are the training freeze.

---

## 1. Goal of the label

The unit is a **W=12** window of consecutive non-system IRC lines. The decision is **after the last line**: should an **extra** helper-bot **SPEAK** or stay **SILENT**.

It is not writing the reply. It is not Kummerfeld `connections` (who replied to whom). Default is **SILENT**.

Teacher system prompt (`src/soma_data/teacher_prompt_v2_2.py`, `TEACHER_SYSTEM_PROMPT_V2_2`):

> You label SPEAK or SILENT for an EXTRA helper-bot AFTER the last line of a 12-line IRC window.  
> You are not writing a reply. […] Default: SILENT. Prefer SILENT when unsure.

Human stub (`reports/label_guidelines_stub.md`): same default; a frozen writer would draft a sentence **only if** the gate says SPEAK.

---

## 2. Guideline (ownership)

The live rule is **thread ownership**, encoded in prompt `pilot_v2.2` and `helper_in_window`.

**SPEAK** when nobody owns the last thread yet:

- `helper_in_window=no` **and** the last line is a real how-to / “anyone” / install-boot-wifi-driver-apt question with no owner
- or a follow-up how-to (“what should I use then?”) with no owner yet

Busy room is not a reason to stay silent if that last thread is unanswered.

**SILENT** when someone already owns it, or there is nothing to help:

- thanks / k / ok / works / fixed / good luck / nevermind
- joke, debate, offtopic, brb
- last speaker is already a helper giving steps
- last line is `Nick:` to someone who **already spoke** in the window (helper still present), even if the user says “nothing happens”
- `helper_in_window=yes` and the last line is **not** a brand-new group how-to (continuation / stuck report → SILENT)
- two humans already on that thread (pile-on)
- unsure → SILENT

That is the v2.2 fix vs v2/v2.1: empty `addressed_to` but a helper already on the last speaker’s thread must not look like an open group question (`reports/pilot_v2_2_gate1.md`).

`reports/label_guidelines_stub.md` lists the same ten ownership rules for the human UI. `guideline_hint` on the sheet is an automatic non-gold hint (`question + no clear addressee` / `addressed to human` / `thanks`). Ignore it when it conflicts with the rules.

---

## 3. Teacher pipeline + prompt version

**Model:** `Qwen/Qwen2.5-32B-Instruct`, revision `5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd`, bf16, Modal H100.  
**Engine:** `transformers.generate`, temperature 0, `max_new_tokens=80` (`reports/pilot_2k_results.md`, Gate-1 reports).

| stage | prompt | script | what |
| --- | --- | --- | --- |
| v1 2k pilot | `pilot_v1` | `scripts/06_silver_label_pilot.py` | 1,999 parse-ok + 1 fail on frozen 2k. **Not mixed into train.** |
| Gate 1 v2 | `pilot_v2` | `scripts/09_gate1_pilot_v2.py` | Relabel the same 200 gold. **FAIL** 147/200 = 73.5%. Does not write `label_gold`. |
| Gate 1 v2.1 | `pilot_v2.1` | `scripts/10_gate1_pilot_v2_1.py` | **FAIL** 155/200 = 77.5%. |
| Gate 1 v2.2 | `pilot_v2.2` | `scripts/11_gate1_pilot_v2_2.py` | **PASS** 171/200 = **85.5%**. Harvest bar ≥78% overall, addressed ≥75%, SPEAK 35–55%. Teacher SPEAK rate on the 200 = 40.5% vs Nivas 45.0%. |
| Harvest | `pilot_v2.2` | `scripts/12_…` then detached `14_spawn_harvest_detach.py` | Unlabeled queue **minus** `audit_200`. Resume-safe jsonl. |

Harvest dump on disk: `data/silver/pilot_v2_2_labels.jsonl`

- parse-ok **21,350**
- SPEAK **5,100** / SILENT **16,250** (**23.9%** SPEAK)
- + 1 parse fail (`ubuntu:train:2011-08-22:101:0:154432`)

That 23.9% is the **teacher prior** on the labeled pool, not the gold rate.

Teacher JSON: `{"label":"SPEAK"|"SILENT","reason":"<=15 words"}`. Stored as `label_silver`. **Never copied onto `label_gold`.**

---

## 4. Human audit process

1. Freeze 200 windows from the v1 2k (`scripts/07_audit_sample.py`) → `data/silver/audit_200.csv`, `audit_200_ids.txt`, `audit_200_manifest.json`. Stratified buckets (open questions, addressed, thanks, …). **Not a random IRC minute** — that is why gold SPEAK is 45%, not ~24%.
2. Local UI `scripts/07_label_ui.py` on that CSV. Reviewer **`nivas` only** (the `reviewed_by` column). Keyboard: S SPEAK / L SILENT. Hints (Qwen / Grok draft) exist for Nivas; they are stripped for friends.
3. Rubber-stamp pass was reset (`data/silver/audit_200.bak.csv`). Honest re-label: **200/200** `review_ok=Y`.
4. `scripts/08_apply_reviewed_gold.py` copies those 200 `label_gold` values onto `label_queue.csv` **for those ids only**. The other ~29,800 queue rows stay empty.

**Gold on disk** (`data/silver/audit_200.csv`):

| | n |
| --- | ---: |
| windows | 200 |
| `review_ok=Y` | 200 |
| `reviewed_by` | nivas |
| SPEAK | **90** |
| SILENT | **110** |
| SPEAK % | **45.0%** |

Friends (`data/friends/ASSIGNMENT.md`, `manu_200.csv`, `punith_200.csv`):

- Manu 200 + Punith 200 = 400 holdout ids
- **`label_gold` empty, `label_silver` empty** — not gold, not in train, not in test
- UI was built; **they have not labeled**

Do not invent other annotators. The only filled `reviewed_by` on gold is **nivas**.

---

## 5. Numbers table

| pool | n | SPEAK | SILENT | SPEAK % | who labeled | path |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Hub IRC | 250,738 messages → 222,954 windows | — | — | — | nobody (no SPEAK/SILENT) | `data/raw/`, `windows_full.parquet` |
| Label queue | 30,000 | — | — | — | unlabeled pool | `data/processed/label_queue.csv` |
| v1 silver 2k | 1,999 parse-ok | (v1) | (v1) | — | Qwen 32B `pilot_v1` | `data/silver/pilot_2k_labels.jsonl` — **not in train** |
| Harvest v2.2 | **21,350** parse-ok | **5,100** | **16,250** | **23.9%** | Qwen 32B `pilot_v2.2` | `data/silver/pilot_v2_2_labels.jsonl` |
| Gold | **200** | **90** | **110** | **45.0%** | nivas | `data/silver/audit_200.csv` |
| Train 1:1 (ablation file) | 10,200 | 5,100 | 5,100 | 50.0% | teacher silver | `sft_train_1to1.jsonl` |
| Train 1:3 (**used**) | **20,400** | **5,100** | **15,300** | **25.0%** | teacher silver `qwen32_v2.2` | `data/processed/sft_train_1to3.jsonl` |
| Test | **200** | **90** | **110** | **45.0%** | nivas_gold | `data/processed/sft_test.jsonl` |
| Friends | 400 | 0 | 0 | — | **unlabeled** | `data/friends/` |

Hygiene (`reports/split_card.md`, checked on jsonl):

- train 1:3 ∩ test = **0**
- train 1:1 ∩ test = **0**
- train ∩ friends = **0**
- test ∩ friends = **0**
- train source = `qwen32_v2.2`; test source = `nivas_gold`
- `prompt_version=pilot_v2.2`, seed=42

`reports/dataset_eda.md` Table 1 still lists train as 10,200 (the 1:1 export from `scripts/15_export_sft_and_eda.py`). Primary train on disk is **1:3** (`scripts/16_freeze_friends_and_splits.py`). Harvest 5,100 / 16,250 and gold 90 / 110 match both files.

Gate-1 on the **same 200 gold** (teacher vs nivas, gold never overwritten):

| prompt | agree | result | report |
| --- | ---: | --- | --- |
| v2 | 147/200 **73.5%** | FAIL | `reports/pilot_v2_gate1.md` |
| v2.1 | 155/200 **77.5%** | FAIL | `reports/pilot_v2_1_gate1.md` |
| v2.2 | 171/200 **85.5%** | PASS → harvest | `reports/pilot_v2_2_gate1.md` |

---

## 6. What we did not label

- **21,350 harvest rows are teacher silver, not student-hand gold.** Only **200** windows have a human `label_gold`.
- Hub `connections` are not SPEAK/SILENT.
- The leftover ~8k of the 30k queue (after gold, harvest, and 400 friends) is still empty.
- **Manu 200 and Punith 200 are not labeled.** Empty gold. Do not call them gold or a second test.
- v1 2k silver is **not** in `sft_train_1to3.jsonl` (`source=qwen32_v2.2` only; `dataset_eda.md` leak check `v1 rows in train = 0`).
- Nobody labeled the wording of a reply. The gate is SPEAK|SILENT only.

One sentence for a slide: **Hub has no gate labels; Qwen-32B v2.2 silver-labeled 21,350 windows (~24% SPEAK); Nivas gold-labeled 200 (90/110) as the only test; friends 400 are holdout with empty gold.**
