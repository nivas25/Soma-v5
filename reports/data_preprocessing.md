# Data preprocessing — Hub raw → 12-line label-ready window

This is what **this repo actually runs**. Scripts `01_download.py` → `04_export.py`, plus `src/soma_data/parse_irc.py`, `windows.py`, `export.py`, `teacher_prompt_v2_2.py`. No NLTK, no spaCy, no Porter stemmer, no WordNet lemmatizer.

**NLP checklist (gate corpus):**

| step | used? |
| --- | --- |
| stemming | **NOT USED** |
| lemmatizing | **NOT USED** |
| lowercasing the chat | **NOT USED** (nicks and text keep Hub casing) |
| stopword removal | **NOT USED** |
| Hub `tokenized` field as gate input | **NOT USED** (passthrough only) |
| Gate “tokenization” | Qwen chat template + the **model’s own BPE** at train/infer (`tokenizer.apply_chat_template` in `modal_lora.py` / `modal_teacher.py`). That is not a corpus cleaner. |

---

## 1. Raw schema (Hub)

`scripts/01_download.py` logs in and calls `download_all` (`hf_download.py`). Each row is **one IRC line**:

| Hub field | meaning |
| --- | --- |
| `id` | line id inside the source file; values `connections` point at |
| `raw` | original irclog: `[HH:MM] <nick> text` or `=== …` |
| `ascii` | ascii-fied `raw` |
| `tokenized` | paper’s UNK tokenisation — **we do not feed this to the gate** |
| `connections` | reply-graph neighbour ids (Kummerfeld disentangle) |
| `date` | Ubuntu calendar day; `channel_two` has none |

We add Hub identity: `config`, `split`, `row_idx` (`parse_hub_row`, `parse_irc.py:323–344`).

On disk: `data/raw/ubuntu__{train,validation,test}.parquet`, `channel_two__*.parquet`, `data/raw/download_manifest.json`.

Windowing partition (`messages_for_windows`, `stats.py:57–60`): **all ubuntu splits** + **`channel_two/all_` only** (overlapping channel_two subset splits dropped).

---

## 2. Filters — what is dropped from windows

Parse: `parse_raw_line` (`parse_irc.py:196–320`). Never raises; junk gets `parse_ok=False`.

**Dropped from windows** (`emit_windows`, `windows.py:271–272`):

```python
if exclude_system and (m.is_system or not m.parse_ok):
    continue
```

`EXCLUDE_SYSTEM_FROM_WINDOWS = True` (`config.py:111`).

`is_system` (`parse_irc.py:13`, `_system_match` `173–193`):

- JOIN / PART / QUIT (`has joined|left|quit`)
- nick change (`is now known as`)
- KICK, MODE, TOPIC
- `entered the room` / `left the room` (channel_two)
- IRC NOTICE `(nick/#channel)` / `-nick:#channel-`
- blank log lines (`parse_irc.py:214` — kept for run ids, then dropped)

**Kept in the stream (not system):**

- PRIVMSG `[HH:MM] <nick> text`
- `/me` actions: `[HH:MM] * nick …` or `=== nick rest` without a system verb (`is_action=True`)

Parse-fail lines (`parse_ok=False`) are **dropped from windows**, same as system. They still sit in `messages.parquet`.

**Not dropped:** we do **not** drop by length, language, or “noise” nicks. FloodBot is still a chat line; `helper_in_window` later ignores it as a helper (`teacher_prompt_v2_2.py:105–106`).

---

## 3. Run / gap rule and W=12

**Sort key is never `connections`.** Docstring: `windows.py:3`. Official order:

`(config, split, date, slice_id, original_id)` after `assign_slices_and_runs` (`windows.py:79–123`).

- **New slice** when `date` changes **or** `original_id` decreases (same-day Hub file concat) (`windows.py:107–112`).
- **New run** inside a slice when `original_id[i] - original_id[i-1] > GAP_THRESHOLD` (`windows.py:113–114`).
- `GAP_THRESHOLD = 5` (`config.py:104`). Jumps of 1–5 stay in-run. Jump of 6+ starts a new run. Windows **never** cross a run, date, slice, split, or config (`build_window_record`, `windows.py:214–219`).

**Window definition** (`windows.py:8–11`, `emit_windows` `258–284`):

- Decision point = after message `t` (the last line).
- Window = last **W=12** non-system, parse-ok messages in the **same run**, ending at `t`.
- `WINDOW_SIZE = 12` (`config.py:108`).
- `REQUIRE_EXACT_W = True` (`config.py:110`). Short leading windows are **not** emitted (`windows.py:266–267`).
- `MIN_HISTORY = 8` (`config.py:109`) is **recorded only**. Exact-W is stricter; MIN_HISTORY is unused for emission.

Sliding: for a run of length N ≥ 12, emit windows `run[i-11 : i+1]` for `i = 11 … N-1` (`windows.py:281–283`).

`time_capped_n` (`windows.py:159–174`): count of the 12 lines whose clock is within `TIME_CAP_MINUTES = 3` of `t`. **Feature only.** It does **not** shrink `chat_block`.

---

## 4. Flags — exact rules

Computed on the **last line** of the window unless noted.

### `addressed_to`

`extract_addressed_to` (`parse_irc.py:147–162`) on the last line’s **text** (after `<nick>`):

- Regex `ADDRESS_RE`: start of text is `Nick:` with RFC-ish nick class (`parse_irc.py:91`).
- Reject `http:`, `ftp:`, `file:`, `irc:`.
- Reject one-letter `C:\` / `C:/` drive paths.
- `arog, hello` (comma) is **not** addressed. `arog: hello` is.
- Stored on the last message; copied onto the window as `addressed_to=last.addressed_to` (`windows.py:243`).

### `last_is_question`

`has_question` (`parse_irc.py:165–166`): **`"?" in text`**. No question-word list. Copied as `last_is_question=bool(last.has_question)` (`windows.py:247`).

### `last_is_thanks`

`is_thanks` (`parse_irc.py:169–170`) via `THANKS_RE` (`parse_irc.py:93`):

```
thanks|thx|works now|fixed|solved
```

case-insensitive substring on **last text**. Copied `windows.py:248`.

### `question_open`

Any of the **last 3** lines has `has_question` (`windows.py:221–222`). Queue/SFT side feature, not the v2.2 `question=` flag (that one is `last_is_question`).

### `helper_in_window`

**Not** a Hub field and **not** a column on `windows_full` / `label_queue` from `04_export.py`. Recomputed at teacher / SFT export from `chat_block` + last line (`helper_in_window`, `teacher_prompt_v2_2.py:155–206`).

True if **any** of:

1. `helper_still_in_window`: `addressed_to` nick (or last-line `Nick:`) already spoke in the window (`141–152`).
2. Earlier lines (not the last) from someone else **toward last_speaker** (`Nick:` or `| nick`) that are not greetings (`just ask|hello|hi|hey|…`): helper-language regex **or** 1+ such answer (`173–196`). FloodBot is skipped.
3. Last line is `ubotu tell` / addressee is ubotu/ubottu, **or** last line addresses someone who already spoke **and** is diagnostic / helper-language / ends with `?` (`198–205`).

`yes`/`no` string in the v2.2 user payload (`build_user_payload_v2_2`, `209–227`).

---

## 5. Hub fields kept vs fields we added

**Kept (passthrough):** `raw`, `ascii`, `tokenized`, `connections`, `id` (as `original_id`), `date`.

**Added at parse:** `speaker`, `text`, `time_hhmm`, `is_system`, `is_action`, `addressed_to`, `has_question`, `parse_ok`, `slice_id`, `run_id`, plus identity `config`, `split`, `row_idx`.

**Added at window:** `window_id`, `chat_block` (`nick: text` or `* nick action` via `display_line`, `parse_irc.py:138–144`), `last_speaker`, `last_is_question`, `last_is_thanks`, `question_open`, `n_speakers_in_window`, `thread_ids_last`, `thread_overlap_count`, `time_capped_n`, `window_message_ids`, `guideline_hint` (labeller hint only — **not gold**).

**Added later, not in 04:** `helper_in_window` (v2.2), `label_gold` / `labeler` (human audit), `label_silver` (teacher).

---

## 6. `connections` and the gate

- **Sort / window membership: ignored.** Never a sort key (`windows.py:3`).
- **Stored** on the window as `thread_ids_last = last.connections` and `thread_overlap_count` (`windows.py:177–190`, `245–246`) — how many window ids share a reply-graph edge with the last line.
- **Gate input (v2.2): ignored.** `build_user_payload_v2_2` sends `chat_block` + `question` / `thanks` / `addressed_to` / `helper_in_window`. No `connections` list. The SPEAK|SILENT model does not see the disentangle graph.

---

## 7. What we did **NOT** do

- **NOT USED:** stemming, lemmatizing, stopword lists, lowercasing the chat, TF–IDF, sentence splitting, coref, MiniLM, emotion, PPO.
- **NOT USED** as gate text: Hub `tokenized` (`<s> … </s>`, `<unk#a>`, `<user>`).
- We do **not** rewrite spelling (`THat`, `im not sure` stay).
- We do **not** collapse nicks or strip timestamps from `raw` until `display_line` builds `chat_block` (`Nick: text`).
- `04_export.py` `format_sft_input` (`export.py:52–69`) is an **older** `[ROOM]/[CHAT]` template for `sft_template.jsonl`. The **live gate** uses `pilot_v2.2` `sft_record` / `build_user_payload_v2_2` from scripts 15–16.

The only “tokenizer” the gate sees is **Qwen’s** `apply_chat_template` + BPE on the already-built string (`modal_lora.py:158`, `modal_teacher.py:254`). That does not change `chat_block` on disk.

---

## 8. Worked example — arog `df -h` (Hub raw → one W=12)

Hub: `ubuntu` / `test` / `2014-06-18` / ids 9550–9567 (18 consecutive PRIVMSG, one run). Parsed in `messages.parquet`: `slice_id=6`, `run_id=0`, none system, all `parse_ok`.

`emit_windows` slides W=12 over that run. **One** label-ready example is the window **ending at id 9567** (decision after Ben64’s reserved-space line). That is ids **9556–9567**.

`window_id` = `ubuntu:test:2014-06-18:6:0:9567`  
(`{config}:{split}:{date}:{slice_id}:{run_id}:{t_id}`, `windows.py:229`)

### Last 12 Hub `raw` lines (what we keep)

```
[06:54] <mxvxrts> arog, partition sizes are counted in two ways that is about right.
[06:55] <dunbuggy> hey
[06:55] <arog> mxvxrts: so from 900gb almost 50gb gets used up?!
[06:55] <arog> that's crazy!
[06:55] <mxvxrts> arog, THat is to full anyway
[06:55] <Ben64> arog: it probably is reserved space
[06:55] <arog> what do you mean
[06:55] <mxvxrts> arog, It is not crazy it is the way it is look it up.
[06:56] <arog> got a link?
[06:56] <arog> im not sure what to search for
[06:57] <mxvxrts> arog, The difference is 1000MB for a gig and 1024 for a gig if I have the numbers correct.
[06:57] <Ben64> arog: by default 5% of a filesystem is reserved for root, 5% of 909G is 45.45G, 45.45+15+848=908.45
```

(The six earlier lines 9550–9555, including `anyone around?`, sit in **previous** W=12 windows of the same run, not this one.)

### Same 12 as `chat_block` (`display_line`)

```
mxvxrts: arog, partition sizes are counted in two ways that is about right.
dunbuggy: hey
arog: mxvxrts: so from 900gb almost 50gb gets used up?!
arog: that's crazy!
mxvxrts: arog, THat is to full anyway
Ben64: arog: it probably is reserved space
arog: what do you mean
mxvxrts: arog, It is not crazy it is the way it is look it up.
arog: got a link?
arog: im not sure what to search for
mxvxrts: arog, The difference is 1000MB for a gig and 1024 for a gig if I have the numbers correct.
Ben64: arog: by default 5% of a filesystem is reserved for root, 5% of 909G is 45.45G, 45.45+15+848=908.45
```

### Flags on this window

| flag | value | why |
| --- | --- | --- |
| `last_speaker` | `Ben64` | last PRIVMSG nick |
| `last_is_question` | **no** | last text has no `?` |
| `last_is_thanks` | **no** | no `thanks\|thx\|works now\|fixed\|solved` |
| `addressed_to` | `arog` | last text starts `arog:` (`extract_addressed_to`) |
| `question_open` | **no** | last 3 lines (9565–9567) have no `?` (`got a link?` is 4th from end) |
| `helper_in_window` | **yes** | `addressed_to=arog` and arog already spoke (`helper_still_in_window`) |
| `n_speakers_in_window` | 4 | mxvxrts, dunbuggy, arog, Ben64 |
| `connections` on these ids | `[]` | unannotated context prefix of the slice; **not** used by the gate anyway |

This is still **not** a SPEAK/SILENT gold row. It is only the structural window the gate would see.

v2.2 user payload shape (`build_user_payload_v2_2`):

```
WINDOW_ID: ubuntu:test:2014-06-18:6:0:9567
last_speaker=Ben64 question=no thanks=no addressed_to=arog
helper_in_window=yes
LAST: Ben64: arog: by default 5% of a filesystem is reserved for root, 5% of 909G is 45.45G, 45.45+15+848=908.45

CHAT:
…12 lines above…

Decide AFTER the last line. JSON only.
```

---

## 9. Outputs on disk (after 01–04)

| file | what |
| --- | --- |
| `data/raw/*.parquet` | Hub snapshots (`01_download.py`) |
| `data/interim/messages.parquet` | parsed lines + slice/run (`02_analyze.py`) |
| `reports/schema.md`, `reports/eda.md` | schema + EDA (`02`) |
| `data/processed/windows_full.parquet` | every exact W=12 (`03_build_windows.py`) — 222,954 rows |
| `data/processed/label_queue.csv` + `.parquet` | 30,000 sampled windows, **gold empty** (`04_export.py`) |
| `data/processed/sft_template.jsonl` | same 30k, `output=""` (`04`) |
| `reports/stats.json` | row-count reconciliation (`04`) |

Later (not 01–04): teacher silver, Nivas gold, `sft_train_1to3.jsonl`. Those do not restem or retokenize `chat_block`.
