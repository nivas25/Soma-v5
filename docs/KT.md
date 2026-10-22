# SOMA knowledge transfer

This note is for a teammate taking over the repo. It follows the code, the reports under `reports/`, and the chat that was added on top of the trained gate. Numbers below are copied from those reports. They were not remeasured for this file.

## What SOMA is

The trained system is a gate. It reads one 12-line Ubuntu IRC window and answers with one token, SPEAK or SILENT, for the moment after the last line. It does not write the help text.

`reports/labeling_process.md` states the unit: a window of 12 consecutive non-system lines, and the decision is whether an extra helper-bot should speak after the last line. The teacher prompt in `src/soma_data/teacher_prompt_v2_2.py` says the same thing: label SPEAK or SILENT, do not write a reply, default SILENT, prefer SILENT when unsure. The student instruction used at train and serve time is `SFT_INSTRUCTION_V2_2` in that file:

> You are an extra silent helper-bot in multi-party Ubuntu IRC. Decide SPEAK or SILENT AFTER the last line. Default SILENT. Reply with one token: SPEAK or SILENT.

A writer and a set of checks were added later, in the room server. They run only after the gate has already returned SPEAK. They are not part of the trained label. `reports/training_eval.md` section 6 lists “a writer (reply generation)” under what was not trained. `reports/labeling_process.md` says nobody labeled the wording of a reply.

The nick `soma` in the live room is reserved for those later replies. The gate itself has no nick.

## Dataset

Source: `jkkummerfeld/irc_disentangle` (`src/soma_data/config.py`, `HF_DATASET`). Paper: Kummerfeld et al., ACL 2019, P19-1374 / arXiv:1810.11118. License: CC-BY-4.0. This is not the Lowe/McGill Ubuntu Dialogue Corpus. `reports/schema.md` says that corpus was not used.

Official Hub splits, from `reports/schema.md` (counts are Hub rows, not windows):

| config | split | rows |
| --- | --- | ---: |
| ubuntu | train | 220,616 |
| ubuntu | validation | 12,510 |
| ubuntu | test | 15,010 |
| channel_two | all_ | 2,602 |

The card’s annotated Ubuntu counts are train 67,463 / dev 2,500 / test 5,000. The loader returns context plus annotated lines. Context is about the first 1,000 messages of a slice, with empty `connections`. The Hub split is named `validation`, not `dev`. `channel_two` has no date field; the code fills `date="undated"`. Its smaller splits overlap, so windows use `all_` only (`CHANNEL_TWO_WINDOW_SPLIT` in `config.py`).

A Hub row is one IRC line. `reports/schema.md` lists the raw fields: `id`, `raw`, `ascii`, `tokenized`, `date`, `connections`. `connections` is a reply-graph edge list. It is stored and never used as a sort key (`windows.py` docstring). The v2.2 gate payload does not include it (`reports/data_preprocessing.md` section 6).

`reports/labeling_process.md` gives the scale after our parse: 250,738 messages become 222,954 windows. System lines are dropped before a window is built. `emit_windows` in `src/soma_data/windows.py` skips a line when `is_system` or `parse_ok` is false. `EXCLUDE_SYSTEM_FROM_WINDOWS` is true in `config.py`. `reports/data_preprocessing.md` lists what counts as system: JOIN, PART, QUIT, nick change, KICK, MODE, TOPIC, “entered the room” / “left the room”, IRC NOTICE, and blank log lines. Parse failures are dropped from windows and kept in `messages.parquet`. PRIVMSG and `/me` actions stay. Lines are not dropped for length, language, or bot-looking nicks. FloodBot can remain in the chat block; `helper_in_window` later skips it as a helper.

Windows are exact length 12. `WINDOW_SIZE = 12` and `REQUIRE_EXACT_W = True` in `config.py`. `emit_windows` refuses short windows. The comment in `config.py` says the labelling UI is uniform, so every example has exactly W messages. `MIN_HISTORY = 8` is recorded and not used to emit a short leading window. For a run of length N at least 12, the slide is 1: windows are `run[i-11 : i+1]` for `i` from 11 through N-1 (`reports/data_preprocessing.md` section 3). A run shorter than 12 emits nothing.

A window never crosses a run. `assign_slices_and_runs` starts a new slice when the date changes or `original_id` goes backwards (two Hub files of the same calendar day). Inside a slice, a new run starts when `original_id[i] - original_id[i-1] > GAP_THRESHOLD`. `GAP_THRESHOLD = 5`, so a gap of 6 or more splits the run. Gaps of 1 to 5 stay in the same run. `reports/eda.md` gives the reason: Kummerfeld samples time slices of #ubuntu; ids are log-line numbers; a same-day file concat resets the id; small holes are not a new conversation, and a jump of 6 or more must not glue two distant samples into one room. `build_window_record` asserts one date and one run key.

Flags on a window:

| Flag | Where it is computed |
| --- | --- |
| question | `last_is_question`. True when the last line’s text contains `?`. `has_question` in `parse_irc.py`. There is no question-word list. The v2.2 payload prints this as `question=yes` or `question=no`. |
| thanks | `last_is_thanks`. `THANKS_RE` matches `thanks`, `thx`, `works now`, `fixed`, `solved` on the last line, case-insensitive. |
| addressed_to | `extract_addressed_to` on the last line. A leading `Nick:` counts. `http:`, `ftp:`, `file:`, `irc:`, and a one-letter drive path do not. A comma address (`arog, hello`) does not. |
| helper_in_window | Not a Hub column. Recomputed in `teacher_prompt_v2_2.py` from the chat block and the last line. True if the addressed nick already spoke, or an earlier line toward the last speaker looks like help, or the last line is an `ubotu` tell / addresses someone who already spoke and looks diagnostic. FloodBot is skipped. The payload gets `helper_in_window=yes` or `no`. |

`question_open` (any `?` in the last 3 lines) exists on the window record. The v2.2 `question=` flag is the last line only.

Why 12: `config.py` says the labelling UI is uniform and therefore emits exact-W windows. `reports/data_preprocessing.md` repeats that short windows are disabled for that reason. Nothing in the reports shows a sweep that picked 12 as optimal. `MIN_HISTORY = 8` was written down and not used.

## Labels

The teacher is `Qwen/Qwen2.5-32B-Instruct`, revision `5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd`, bf16, temperature 0, `max_new_tokens=80` (`reports/labeling_process.md`). The prompt that was allowed to harvest is `pilot_v2.2` (`PROMPT_VERSION` in `teacher_prompt_v2_2.py`).

Gate 1 compared the teacher with Nivas on the same 200 gold windows, without writing over `label_gold`:

| Prompt | Agree | Result | Report |
| --- | --- | --- | --- |
| pilot_v2 | 147/200 = 73.5% | fail | `reports/pilot_v2_gate1.md` |
| pilot_v2.1 | 155/200 = 77.5% | fail | `reports/pilot_v2_1_gate1.md` |
| pilot_v2.2 | 171/200 = 85.5% | pass | `reports/pilot_v2_2_gate1.md` |

The harvest bar in that report is at least 78% overall, at least 75% on addressed cases, and a teacher SPEAK rate between 35% and 55%. v2.2 was 85.5% overall. Teacher SPEAK on those 200 was 40.5%. Nivas SPEAK was 45.0%. Harvest ran after that pass, not before.

Harvest (`scripts/12_harvest_pilot_v2_2.py`, detached by `scripts/14_spawn_harvest_detach.py`) labeled the queue minus the 200 audit ids. On disk, via `reports/labeling_process.md`: 21,350 parse-ok rows, 5,100 SPEAK, 16,250 SILENT, 23.9% SPEAK, plus one parse failure (`ubuntu:train:2011-08-22:101:0:154432`). Stored as `label_silver`. Never copied onto `label_gold`. The v1 2,000-window silver pass is not in the train file.

Train is the 1:3 file, not the 1:1 ablation. `scripts/16_freeze_friends_and_splits.py` writes `data/processed/sft_train_1to3.jsonl`: 20,400 rows, 5,100 SPEAK and 15,300 SILENT, 25.0% SPEAK, source `qwen32_v2.2`. `reports/dataset_eda.md` Table 1 still says 10,200 because that is the older 1:1 export from `scripts/15_export_sft_and_eda.py`. The training report uses 1:3.

Gold is 200 windows, one annotator. `scripts/07_audit_sample.py` froze them from the v1 2k into `data/silver/audit_200.csv`. Buckets were stratified (open questions, addressed, thanks, and other buckets). `reports/labeling_process.md` says this is not a random IRC minute, which is why gold SPEAK is 45% rather than the teacher’s ~24%. The UI is `scripts/07_label_ui.py`. `reviewed_by` is `nivas` only. Keyboard S / L. Qwen and Grok hints were shown to Nivas and stripped for friends. A rubber-stamp pass was reset (`audit_200.bak.csv`). The kept sheet is 200/200 `review_ok=Y`, 90 SPEAK, 110 SILENT. `scripts/08_apply_reviewed_gold.py` copies those 200 onto the queue. The other queue rows stay empty. Do not add annotators. The report says the only filled `reviewed_by` on gold is nivas.

Friends are 400 unlabeled holdout ids: Manu 200 and Punith 200 (`data/friends/ASSIGNMENT.md`, `manu_200.csv`, `punith_200.csv`). `label_gold` and `label_silver` are empty. They are not in train and not in test. `sft_dev` is empty on purpose (“friends later”, `reports/dataset_eda_stats.json`).

Hygiene from `reports/labeling_process.md` and `reports/split_card.md`, checked on the jsonl:

- train 1:3 ∩ test ids = 0
- train 1:1 ∩ test ids = 0
- train ∩ friends = 0
- test ∩ friends = 0
- train source `qwen32_v2.2`, test source `nivas_gold`, `prompt_version=pilot_v2.2`, seed 42

Known limits, all stated in those reports or in the training setup:

- One annotator. No second human label on the 200.
- The checkpoint was picked on the test set. Training eval runs every 100 steps on the same 200 gold rows, and the saved adapter is the max macro-F1 on that set (`reports/training_eval.md`). There is no separate dev split for selection.
- Neighbor overlap is possible because the slide is 1. Window `t` and window `t+1` in the same run share 11 lines. The reports do not give a measured leakage count for that overlap. They do record train ∩ audit ids = 0, which is a different check.
- Hints were on screen while Nivas labeled. The report does not measure how much they moved the gold.

## Gate model

Base: `Qwen/Qwen2.5-7B-Instruct`, revision `a09a35458c702b33eeacc393d103063234e8bc28`. LoRA r=16, alpha=32, dropout 0.05, on `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj` (`LoraConfig` in `src/soma_data/modal_lora.py`). The serve path checks the adapter config for r=16 and alpha=32 (`src/soma_data/modal_gate.py`).

Loss is only on the token. Rows are prompt/completion pairs. The completion is `SPEAK` or `SILENT`. `SFTTrainer` is built with `completion_only_loss=True` (`modal_lora.py`). `reports/training_eval.md` says the 12-line window is in the prompt and the loss is not on the chat. Train loss is already about 0.037 at step 100 because the target is one class token.

Other training facts from that report: lr 2e-4, cosine, warmup 0.03, 2 epochs, seed 42, per-device batch 8, grad accumulation 4, effective batch 32, `max_length=1024`, packing off, Modal H100, bf16, about 58 minutes. Stack named there: transformers 5.16.1, TRL 1.12.0, PEFT 0.20.0. Train file 20,400. Test file 200 gold (90/110).

Selection is max macro-F1 on the 200, not min train loss. Step 1200 is the first step at 0.8776. Step 1276 ties that F1 and the same confusion. The kept adapter is 1200.

Final numbers on the 200, from `reports/training_eval.md` and `reports/lora_run/reports/test_metrics.json`. Silent=0, Speak=1.

| Method | Macro-F1 | Speak-F1 | Silent-F1 | TN | FP | FN | TP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LoRA step 1200 | 0.8776 | 0.8605 | 0.8947 | 102 | 8 | 16 | 74 |
| B1 always SILENT | 0.3548 | 0.0000 | 0.7097 | 110 | 0 | 90 | 0 |
| B2 `question=yes` | 0.6821 | 0.6519 | 0.7123 | 78 | 32 | 31 | 59 |
| B3 question and no helper | 0.7748 | 0.7162 | 0.8333 | 105 | 5 | 37 | 53 |

Accuracy of the LoRA on this set is 176/200. SPEAK precision 0.902, recall 0.822. Predicted SPEAK rate 41%, gold 45%. The report’s comparison line is macro-F1 0.8776 versus B3 0.7748.

Baselines are untrained rules in `modal_lora.py` `_baselines`. They read flags already printed in `input`. B1 is always SILENT. B2 is SPEAK when `question=yes`. B3 is SPEAK when `question=yes` and `helper_in_window=no`.

Errors, from `test_200_predictions.csv` as counted in `reports/training_eval.md` section 5: of 16 false negatives (gold SPEAK, pred SILENT), 13 have `helper_in_window=yes`. Gold SPEAK rows with a helper present: 15 of 90. All 8 false positives have helper=no. The same section gives the shift: v2.2 train SPEAK rows have helper rate 1.8%, gold SPEAK rows 16.7%. The student copied the quiet teacher.

Deploy: Modal app `soma-gate`, class `Gate`, module `src/soma_data/modal_gate.py`. `generate` is greedy, `max_new_tokens=8`, `do_sample=False`. The room calls `gate_raw`, which is `Cls.from_name("soma-gate", "Gate").generate.remote`. `chat_app._token` then runs `modal_lora._parse_pred`. `_parse_pred` takes the first whitespace token, strips `.,:;"'`, and returns SPEAK, SILENT, or INVALID. INVALID becomes SILENT, matching `_generate_labels`. `gate_label` in `modal_gate.py` does the same parse for a direct call. The room does not use `gate_label`.

Input pair at serve time, built in `chat_app.claim`: system string `SFT_INSTRUCTION_V2_2`, user string `build_user_payload_v2_2`. The payload is window id, `last_speaker`, `question`, `thanks`, `addressed_to`, `helper_in_window`, `LAST:`, `CHAT:`, then “Decide AFTER the last line. JSON only.” The live room builds that row from the last 12 lines, ending at the latest human line (`WINDOW_SIZE`).

Adapter files are read from `models/soma-gate-lora-best/best_adapter` and uploaded into the image at deploy. They are gitignored. `modal_gate.py` raises at deploy time if `adapter_model.safetensors` is missing. GPU settings on the class: H100, 64 GB memory, 8 CPU, startup timeout 30 minutes, method timeout 10 minutes, `scaledown_window` 2 minutes, no `min_containers`. The container needs the Modal secret named `huggingface`.

## Current chat system (phases 1–6)

The room is `src/soma_data/chat_app.py`. The page is `web/`. The phases below are what that code does now. The gate module was not retrained for any of them.

Phase 1. Serve the trained gate. `modal_gate.py` loads the 7B plus the step-1200 adapter. The room does not fall back to Gemini, to `room_gate.py`, or to the 3B writer.

Phase 2. In-memory rooms. `POST /api/join` creates a room and adds a nick. `POST /api/rooms/{name}/lines` appends a human line immediately. `POST /api/rooms/{name}/typing` records typing. Typing expires after `_TYPING_S = 1.5` seconds. Idle is true only when nobody is typing, a human line exists, and `last_activity` is at least `SOMA_IDLE_S` seconds old. The default is 4. A nick equal to `soma` is rejected by `_nick`. Before idle, `claim` returns nothing, so the gate is not called.

Phase 3. On idle, one gate call per `(line id, generation)`. `claim` holds the lock, skips a key that is in `inflight` or `settled`, builds the v2.2 payload, then returns. The Modal call runs outside the lock. `store` keeps the result only if generation and the latest human line still match. A new human line or a typing post calls `bump()`, which increments generation. A second poll of a settled key does not call again. A failed call stores the exception type name, token null, and posts nothing. It does not invent SPEAK.

Phase 4. A reply is requested only when the stored token is SPEAK. The reply app is `soma-reply`, class `Reply`, `src/soma_data/modal_reply.py`. Same 7B base and revision, no LoRA, greedy (`do_sample=False`), `max_new_tokens=96`. System text is only: “Output one JSON object and nothing else. No markdown. No code fence.” The user prompt is `_REPLY` in `src/soma_data/speak.py`, filled with `str.replace` (not `str.format`, because the prompt contains braces). `checked_draft` parses JSON with `parse_model_json` in `gemini_client.py`. That function does not call the network. Empty text or the word NONE becomes reason `none` and posts nothing, unless the question is destructive (below).

Checks inside `checked_draft`, in order:

1. Clean. `_clean_draft` collapses whitespace, strips a leading `helper:` / `bot:` / `soma:`, drops NONE, and cuts at 400 characters. Empty after that is reason `clean`.
2. Denied. `denied` in `src/soma_data/validate_reply.py` matches `rm -rf` / `rm -fr`, `mkfs`, `dd if=`, `chmod 777`, a fork bomb, shutdown, `curl` or `wget` piped to a shell, `init 0` / `init 6`, and `kill -9 1`.
3. Overlap. `command_already_in_window` in `speak_validate.py`. The full clipped command surface must match, with word boundaries. A reply `df -h` matches a window that already contains `df -h /`. A reply `df -h /` does not match a window that only contains `df -h`.
4. Contradicts. A second call to the same Modal `complete` asks whether the draft contradicts the window. Only YES, TRUE, or 1 count as yes. Any exception fails closed (the draft is dropped). A new command by itself is not a contradiction.

Overlap and contradicts still drop the line. They were not loosened when the caution path was added.

Risky-command change, after phase 6. If `denied(cleaned)` is true, or `_asks_destructive(question)` matches (erase/wipe/format of a disk, drive, filesystem, partition, or root; overwrite root; “root filesystem”; “whole disk”), the draft is not dropped for that reason. `_cautioned` posts `This will erase data. Be careful.` If the draft itself is denied and has a command surface, that surface is appended in backticks. The denied command is not the whole reply. A normal `df -h` question does not get the prefix. `tests/test_caution.py` locks that. `tests/test_gate_stages.py` still expects `denied: pass` and the unchanged `df` text on the safe question.

Phase 5. If the draft text is non-empty, the server appends one `ChatLine` with nick `soma`, that text, and `reply_to` set to the human line id. If generation or the latest human line changed while the reply was in flight, the draft is discarded and nothing is appended. The soma line does not go through `_nick` and does not bump generation. The page (`web/src/LineRow.tsx`) shows the name SOMA, the text, and one quoted line. It does not show SPEAK, SILENT, or a reason.

Phase 6. The Gate button is off by default. `web/src/App.tsx` does not mount the column until the click. `web/src/GateColumn.tsx` lists, for each human line that has a stored result or any stages: line id, nick, token, raw model text, the payload, and the stages appended by `_add_stage`. Stages are written only when that step ran. Examples from `chat_app.py`: idle reached, payload built, gate returned SPEAK or SILENT, draft requested, clean/denied/overlap/contradicts, final posted or dropped. A failed gate call says nothing was posted.

What is not wired into the live room:

- Man page / doc filter. `docs_allow` in `speak_validate.py` can fetch a snippet and ask whether it supports the command. `checked_draft` does not call it. The docstring on `checked_draft` says “No docs.” Only `compose_reply` calls `docs_allow`.
- Gemini as the gate or as the room’s writer. `compose_reply` and `scripts/20_speak_demo.py` use `GeminiClient` (`GEMINI_API_KEY`, model name `gemini-3.8-flash` in `.env.example`). `chat_app.py` does not import them. `parse_model_json` is local parsing only.
- Regex as the decision. `room_gate` in `src/soma_data/room_gate.py` is a keyword check. `chat_app.py` does not call it. `draft_one` and `compose_reply` use `open_question_line` from that module. The live path uses `checked_draft`, which does not.

`src/soma_data/modal_writer.py` and `scripts/19_llm_replies.py` are an offline frozen 7B writer. The room calls `soma-reply`, not that writer. `conflict.py` and `decide.py` feed `scripts/18_run_four_objectives.py`. They are not the gate.

## Flaws

Single annotator. Gold `reviewed_by` is nivas on all 200. Friends have not labeled. There is no agreement number between two humans.

Test-set checkpoint. Every 100 steps the run scores the 200 gold windows, and step 1200 wins because that score is highest. The published test number is the selection number. `sft_dev` is empty. Do not describe 0.8776 as an untouched test.

Fixed 12 and last-line bias. W is frozen for a uniform labelling sheet, not because a search showed 12 was best. The decision, `question`, `thanks`, and `addressed_to` are defined on the last line. A how-to that is not the last line is invisible to those flags. `helper_in_window` looks earlier, but the token is still “after the last line.”

Neighbor overlap. Slide 1 means adjacent windows share 11 lines. Ids do not overlap between train and the 200 test windows. The text still can. No report quantifies that.

Flag leakage risk. `build_user_payload_v2_2` prints `question=` and `helper_in_window=` in the same string the model is trained to complete. B3 is the rule “question yes and helper no” read off those flags. The 13 of 16 misses are gold SPEAK with helper present, and the train SPEAK helper rate is 1.8% against 16.7% on gold. The model can follow the printed flag. The reports do not contain an ablation that hides the flags.

No zero-shot 7B baseline. `test_metrics.json` has the LoRA and B1, B2, B3. It does not have the base 7B with no adapter. `reports/training_eval.md` section 6 also says there was no 1:1 LoRA run, no 32B student, and no training on gold.

Idle and generation can fire more than once on the same human line. The guard is the pair `(line id, generation)`, not the line id alone (`claim` in `chat_app.py`). A typing post calls `bump()` even when the text did not change. After that post goes idle, the new generation is a new key, so the gate runs again on that line. Two polls of one key do not both call: `inflight` and `settled` block the second. A call that loses the race because generation changed is not settled, so the new generation can call.

The Gate panel prints the raw decode and the full payload as well as the stage list (`GateColumn.tsx`). That text is long. The thread does not show it, and the column is unmounted until the button is on. There is no separate measurement of an older panel.

v5 by itself is not a tier-2 paper. `reports/v5_four_objectives.md` and `reports/v5_llm_replies.md` are offline checks on top of this gate. They do not add a second annotator, a dev split, a zero-shot 7B, or a labeled conflict set. The gate result is a distillation of one 32B teacher onto one token, scored on 200 labels from one person, with the checkpoint chosen on those 200.

## What is solid

The gate is a real LoRA on real Ubuntu IRC from the Kummerfeld corpus, not a keyword list. System lines are removed, windows do not cross a run, and train ids do not meet the 200 test ids.

The teacher was checked on the 200 before harvest. v2 and v2.1 failed their bars. v2.2 passed at 171/200, and only then were 21,350 windows labeled. Silver was not written into `label_gold`.

The reply can refuse. NONE, empty text, overlap, and a contradiction post nothing. A Modal exception posts nothing and stores the exception type.

The checks can block. Overlap drops a command that is already in the window, including after the caution rewrite. A repeated `mkfs` on an erase question is dropped (`tests/test_caution.py`). Contradicts fails closed.

A posted reply is tied to a message. `reply_to` is the human line id the gate ran on. If that line is no longer the latest human line, the draft is not appended.

The demo can show the stages that ran. The column is fed by `_add_stage` at the moment of the step. It is not a second, made-up explanation.

## Research note

“When should a bot speak in a multi-party chat” is already a line of work (When2Speak and similar systems). This repo does not include a literature review or a citation list, so do not invent one in a paper draft from this file.

The sharper claim that this data almost supports, and does not yet measure, is abstain when helpers already disagree. The gold label is ownership: SPEAK if the last thread has no helper yet, SILENT if someone owns it or there is nothing to add (`reports/labeling_process.md` section 2). It is not a label for “two helpers gave conflicting commands.” `src/soma_data/conflict.py` is an offline detector used by `scripts/18_run_four_objectives.py`. It is not a benchmark split, and those rows were not the training target.

The current target is a capstone, and after that a small venue. The 200 gold windows, the missing dev split, the test-set checkpoint, and the missing conflict labels are the reasons v5 alone does not carry a stronger claim.

## How to run

Modal auth. Install the CLI login, or set `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` from `.env.example`. The gate and reply containers also expect a Modal secret named `huggingface` so they can download `Qwen/Qwen2.5-7B-Instruct`. `HF_TOKEN` in `.env` is for `scripts/01_download.py` and the other data scripts. Do not commit `.env`.

Adapter. The gate deploy reads `models/soma-gate-lora-best/best_adapter/adapter_model.safetensors`. That directory is gitignored. A clone without it cannot deploy `soma-gate`. `soma-reply` has no adapter.

From the repo root, with Python 3.11+ and uv:

```powershell
uv sync --extra dev
uv run python -m modal deploy src/soma_data/modal_gate.py
uv run python -m modal deploy src/soma_data/modal_reply.py
uv run python -m soma_data.chat_app
```

The backend listens on http://127.0.0.1:8787. In a second shell, the Vite dev server proxies `/api` to that port (`web/vite.config.ts`, port 5173). CORS in `chat_app.py` allows `http://127.0.0.1:5173` and `http://localhost:5173`.

```powershell
Set-Location web
npm install
npm run dev
```

Open http://127.0.0.1:5173 . Join a room. The usual demo room is `ubuntu`. Use any nick except `soma`.

`npm run build` writes `web/dist`. If that directory exists, the same backend mounts it at `/` and http://127.0.0.1:8787 serves the built page. The dev server does not need that build.

`uv run modal` and `uv run pytest` fail in this environment (“Failed to canonicalize script path”). Use `uv run python -m modal` and `uv run python -m pytest`.

Env vars the room actually reads:

| Name | Role |
| --- | --- |
| `SOMA_IDLE_S` | Quiet time before the gate. Default 4. Parsed in `chat_app._idle_seconds`. |
| `HF_TOKEN` | Hub download and the Modal secret. Not read by the room loop. |
| `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` | Modal API auth if the CLI is not logged in. |
| `GEMINI_API_KEY` | `GeminiClient` only. The room does not read it. |

Stop the apps with `uv run python -m modal app stop soma-gate -y` and the same command for `soma-reply`. Then stop the Python process.

A restart of `chat_app` clears the room. `rooms` is a dict in the process. Nothing is written to disk. Stopping Modal does not clear a server that is still running. Deploy again after a change to `modal_gate.py` or `modal_reply.py`. A warm container keeps the old code until it scales down or you stop it. Gate scale-down is 2 minutes. Reply scale-down is 5 minutes. The first call after a cold start loads the 7B and is slow.

## File map

Scripts `01`–`17` are the data and training path. Later scripts are offline or a Gemini demo.

| Script | Role |
| --- | --- |
| `scripts/01_download.py` | Hub snapshots into `data/raw/`. |
| `scripts/02_analyze.py` | Parse and EDA. Writes `messages.parquet`. |
| `scripts/03_build_windows.py` | Exact 12-line windows. |
| `scripts/04_export.py` | 30,000-row `label_queue`. Gold empty. |
| `scripts/05_select_pilot_2k.py` | Freeze 2,000 pilot ids. |
| `scripts/06_silver_label_pilot.py` | v1 32B silver on those 2,000. Not in the 1:3 train file. |
| `scripts/07_audit_sample.py` | Freeze the stratified 200. |
| `scripts/07_label_ui.py` | Local gold UI. |
| `scripts/08_apply_reviewed_gold.py` | Copy the 200 gold labels onto the queue. |
| `scripts/09_gate1_pilot_v2.py` | Teacher v2 vs gold. 73.5%. Fail. |
| `scripts/10_gate1_pilot_v2_1.py` | Teacher v2.1 vs gold. 77.5%. Fail. |
| `scripts/11_gate1_pilot_v2_2.py` | Teacher v2.2 vs gold. 85.5%. Pass. |
| `scripts/12_harvest_pilot_v2_2.py` | Harvest v2.2 silver. |
| `scripts/13_detach_harvest_v2_2.py` | Detach helper for that harvest. |
| `scripts/14_spawn_harvest_detach.py` | Spawn the detached harvest. |
| `scripts/15_export_sft_and_eda.py` | 1:1 SFT file and the dataset EDA. |
| `scripts/16_freeze_friends_and_splits.py` | 1:3 train file and the 400 friend ids. |
| `scripts/17_launch_lora_train.py` | Launch the 7B LoRA run on Modal. |
| `scripts/18_run_four_objectives.py` | Offline conflict / decide table. Not the room. |
| `scripts/19_llm_replies.py` | Offline replies through `modal_writer.py`. Not the room. |
| `scripts/20_speak_demo.py` | Gemini demo through `compose_reply`. Not the room. |

`src/soma_data` files that matter:

| File | Role |
| --- | --- |
| `config.py` | Paths, `WINDOW_SIZE=12`, `GAP_THRESHOLD=5`, dataset name. |
| `parse_irc.py` | One Hub row to a message. System lines, `?`, thanks, `Nick:`. |
| `windows.py` | Slices, runs, exact-12 slide. |
| `export.py` | Queue and the older SFT template. The live gate does not use `format_sft_input`. |
| `teacher_prompt_v2_2.py` | Teacher prompt, `helper_in_window`, `SFT_INSTRUCTION_V2_2`, `build_user_payload_v2_2`. |
| `teacher_prompt_v2.py`, `teacher_prompt_v2_1.py` | Failed Gate 1 prompts. Not the harvest prompt. |
| `modal_teacher.py` | 32B teacher on Modal. |
| `modal_lora.py` | 7B LoRA training, `_parse_pred`, B1–B3. |
| `modal_gate.py` | Deployed `soma-gate`. |
| `modal_reply.py` | Deployed `soma-reply`. |
| `modal_writer.py` | Offline writer. Not `soma-reply`. |
| `chat_app.py` | Room, idle, one gate call, reply append, stages. Port 8787. |
| `speak.py` | `_REPLY`, `checked_draft`, caution path. `compose_reply` is the Gemini path. |
| `speak_validate.py` | Command surfaces, overlap, contradicts, `docs_allow` (not used by the room). |
| `validate_reply.py` | `denied` patterns. |
| `gemini_client.py` | HTTP client plus `parse_model_json`. The room uses only the parser. |
| `room_gate.py` | Keyword gate. Not the live decision. |
| `conflict.py`, `decide.py` | Offline only. |

`web/`:

| Path | Role |
| --- | --- |
| `web/src/App.tsx` | Join, thread, composer, Gate button. Polls every 2 seconds. |
| `web/src/LineRow.tsx` | Human line and SOMA quote. |
| `web/src/GateColumn.tsx` | Token, raw text, payload, stages. |
| `web/vite.config.ts` | Dev server port 5173, proxy `/api` to 8787. |
| `web/dist/` | Production build. Gitignored. Served by `chat_app` when present. |

Reports to read first:

| Report | What it settles |
| --- | --- |
| `reports/schema.md` | Hub configs, splits, row counts, raw fields. |
| `reports/data_preprocessing.md` | System drop, gap rule, W=12, flag definitions. |
| `reports/eda.md` | Why gap threshold is 5. |
| `reports/labeling_process.md` | Teacher, 85.5%, harvest 21,350, gold 200, friends 400, id intersections. |
| `reports/split_card.md` | Train / test / friend id checks. |
| `reports/pilot_v2_2_gate1.md` | The pass that allowed harvest. |
| `reports/training_eval.md` | Step 1200, 0.8776, baselines, 13 of 16 helper-present misses. |
| `reports/lora_run/reports/test_metrics.json` | The same test numbers in JSON. |
| `reports/train_plan.md` | Training setup named by `training_eval.md`. |
| `reports/v5_four_objectives.md` | Offline objectives. Says the gate macro-F1 0.8776 is unchanged by that table. |
| `reports/v5_llm_replies.md` | Offline reply rows. Not the live room. |

Tests that lock the room, if you change it: `tests/test_chat_room.py`, `tests/test_gate_idle.py`, `tests/test_reply_thread.py`, `tests/test_gate_column.py`, `tests/test_gate_stages.py`, `tests/test_caution.py`. `tests/test_reply_live.py` calls the deployed reply model. The older destructive-command assertion in that live file still expects a denied draft to be empty. The room no longer does that. `tests/test_caution.py` is the current check. Do not “fix” the room to satisfy the old assertion.
