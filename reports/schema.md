# Schema contract — SOMA IRC gate data

Source: `jkkummerfeld/irc_disentangle`  
Paper: Kummerfeld et al., ACL 2019 (P19-1374 / arXiv:1810.11118)  
License: CC-BY-4.0  
Not used: Lowe / McGill Ubuntu Dialogue Corpus (dyadic extracted threads).

Generated (UTC): 2026-08-28T13:13:30.213343+00:00

## Hub configs and splits (actual downloads)

| config | split | n_rows | n_nonempty_connections | card_annotated | has_real_date | id unique per date |
|---|---|---:|---:|---:|---|---|
| channel_two | all_ | 2602 | 2601 | 2600 | False | True |
| channel_two | dev | 1001 | 1000 | — | False | True |
| channel_two | pilot | 501 | 500 | — | False | True |
| channel_two | pilot_dev | 1501 | 1500 | — | False | True |
| channel_two | test | 1001 | 1000 | — | False | True |
| ubuntu | test | 15010 | 5042 | 5000 | True | True |
| ubuntu | train | 220616 | 68074 | 67463 | True | True |
| ubuntu | validation | 12510 | 2533 | 2500 | True | True |

### Notes vs the dataset card

- Card **annotated** Ubuntu counts: train 67,463 / dev 2,500 / test 5,000.
- Hub loader returns **context + annotated**. Context is typically the first
  ~1,000 messages of each slice (`connections` empty; labels start at id ≥ 1000).
- Hub split name is `validation` (not `dev`).
- `channel_two` has **no `date` field**. We fill `date="undated"` so the frozen
  sort key `(config, date, id)` stays defined. It is one #linux session (Elsner & Charniak 2008 / Kummerfeld re-annotation).
- `channel_two` Hub splits: `dev`, `pilot`, `test`, `pilot_dev`, `all_`.
  `all_` is the union (2,602 rows). Overlapping subset splits are stored in
  `data/raw/` but **windows use `all_` only** (domain-shift partition).
- `connections` is `list[int]` (reply-graph edges, possibly a self-loop for thread start).
  Used as a **feature**, never as a sort key.
- Nonempty-`connections` slightly exceeds the card’s annotated counts (e.g. ubuntu
  train 68,074 vs 67,463). The extras are context-region messages that still carry
  a reply edge / self-loop. We do **not** drop them: they are real IRC turns.

## Raw Hub fields (do not invent)

| field | dtype | meaning |
|---|---|---|
| id | int | message id inside the source file; values referenced by `connections` |
| raw | str | original IRC log line (primary text) |
| ascii | str | ascii-fied `raw` |
| tokenized | str | tokenised / UNK version |
| connections | sequence[int32] | reply-graph neighbours (same thread) |
| date | str | Ubuntu only. Calendar day of the log file. |

## Parsed message (`data/interim/messages.parquet`)

Derived from `raw` with tested regex. Plus Hub identity fields.

| field | meaning |
|---|---|
| config, split, date, original_id, row_idx | identity / order |
| raw, ascii, tokenized, connections | passthrough |
| time_hhmm | `[HH:MM]` when present |
| speaker | nick inside `<…>` or system/action nick |
| text | remainder after nick |
| is_system | JOIN/PART/QUIT/NICK/KICK/MODE/TOPIC |
| is_action | `/me` (`=== nick rest` without a system verb, or `* nick`) |
| addressed_to | `^Nick:` on `text`, else null (URLs excluded) |
| has_question | `'?' in text` |
| parse_ok | regex matched a known shape |
| slice_id, run_id | ordering (see eda.md) |

## Frozen window schema (`data/processed/windows_full.parquet`)

Decision point = after message `t`. Window = last **W=12** non-system messages in the same run, ending at `t`.
`REQUIRE_EXACT_W=True` — short leading windows are **not** emitted.
`MIN_HISTORY=8` is recorded but unused (exact-W is stricter).
Time-capped view (`time_capped_n`): count of the 12 lines whose clock is within 3 minutes of `t` (feature only; `chat_block` stays 12 lines).

| field | meaning |
|---|---|
| window_id | `{config}:{split}:{date}:{slice_id}:{run_id}:{t_id}` |
| config, split, date, slice_id, run_id, t_id, source | keys |
| chat_block | `Nick: text` one message per line, exactly W lines |
| last_speaker, addressed_to, n_speakers_in_window, n_messages | room flags |
| question_open | last line **or last 3** contain `?` |
| assistant_named | always false in this corpus (schema stability) |
| thread_ids_last | `connections` of t |
| thread_overlap_count | window msgs sharing a reply edge with t |
| last_is_question, last_is_thanks | last-line flags |
| time_capped_n, time_hhmm_last, window_message_ids | features / QA |
| label_gold | **empty** — humans fill later |
| guideline_hint | auto hint only, not a label |

Gold SPEAK/SILENT is **not** produced in this task.

