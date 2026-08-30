# Raw Hub conversation (not a Soma window)

Source: `data/raw/ubuntu__test.parquet`  
Dataset: `jkkummerfeld/irc_disentangle`, config `ubuntu`, split `test`  
Hub stored example = one JSON object per IRC line with fields `id`, `raw`, `ascii`, `tokenized`, `date`, `connections`.  
Full dump of this snippet: `reports/raw_hub_rows.json`.  
Not taken from `label_queue`, `chat_block`, or any W=12 Soma window.

## Metadata

| | |
| --- | --- |
| split | `test` |
| date | `2014-06-18` |
| first_id–last_id | `9550`–`9567` |
| n lines | 18 consecutive non-system PRIVMSG |
| id gaps | all +1 (one run; nothing > 5) |
| nicks | arog, mxvxrts, dunbuggy, Ben64 |

Why this stretch: a user pastes `df -h`, asks why 909G shows only 848G free, two other nicks answer, a fourth nick walks in. Readable on a slide. No JOIN/PART, no empty `ascii`, no binary.

`connections` are `[]` on every line here. That is the Hub file, not a bug in this dump: on this date the annotated reply-graph starts at id 10002. These 18 lines are in the unannotated context prefix of the slice.

## RAW as on Hub

| id | raw | connections |
| ---: | --- | --- |
| 9550 | `[06:53] <arog> hi` | `[]` |
| 9551 | `[06:53] <arog> i just ran df -h and I noticed:: /dev/sda1       909G   15G  848G   2% /` | `[]` |
| 9552 | `[06:53] <arog> why is my size so large (909gb) but my available is only 848gb` | `[]` |
| 9553 | `[06:53] <arog> I find it difficult to believe ubuntu takes up almost 60gb` | `[]` |
| 9554 | `[06:54] <arog> this is without a GUI as well` | `[]` |
| 9555 | `[06:54] <arog> anyone around?` | `[]` |
| 9556 | `[06:54] <mxvxrts> arog, partition sizes are counted in two ways that is about right.` | `[]` |
| 9557 | `[06:55] <dunbuggy> hey` | `[]` |
| 9558 | `[06:55] <arog> mxvxrts: so from 900gb almost 50gb gets used up?!` | `[]` |
| 9559 | `[06:55] <arog> that's crazy!` | `[]` |
| 9560 | `[06:55] <mxvxrts> arog, THat is to full anyway` | `[]` |
| 9561 | `[06:55] <Ben64> arog: it probably is reserved space` | `[]` |
| 9562 | `[06:55] <arog> what do you mean` | `[]` |
| 9563 | `[06:55] <mxvxrts> arog, It is not crazy it is the way it is look it up.` | `[]` |
| 9564 | `[06:56] <arog> got a link?` | `[]` |
| 9565 | `[06:56] <arog> im not sure what to search for` | `[]` |
| 9566 | `[06:57] <mxvxrts> arog, The difference is 1000MB for a gig and 1024 for a gig if I have the numbers correct.` | `[]` |
| 9567 | `[06:57] <Ben64> arog: by default 5% of a filesystem is reserved for root, 5% of 909G is 45.45G, 45.45+15+848=908.45` | `[]` |

`ascii` is nonempty on every row (same printable text as `raw`).

## Hub stored records (`load_dataset` row shape)

Each Hugging Face row is **one message**, not a conversation. Fields:

```
id: int            # line id inside the date file; connections point here
raw: str           # original irclog line  [HH:MM] <nick> text
ascii: str         # ascii-fied raw
tokenized: str     # tokenised / UNK version used in the ACL 2019 paper
date: str          # ubuntu only, calendar day of the log
connections: list[int]  # disentangle reply-graph neighbours (empty in unannotated context)
```

Three rows from this snippet, as stored:

```json
{
  "id": 9550,
  "raw": "[06:53] <arog> hi",
  "ascii": "[06:53] <arog> hi",
  "tokenized": "<s> hi </s>",
  "date": "2014-06-18",
  "connections": []
}
```

```json
{
  "id": 9552,
  "raw": "[06:53] <arog> why is my size so large (909gb) but my available is only 848gb",
  "ascii": "[06:53] <arog> why is my size so large (909gb) but my available is only 848gb",
  "tokenized": "<s> why is my size so large ( <unk#a> ) but my available is only <unk#a> </s>",
  "date": "2014-06-18",
  "connections": []
}
```

```json
{
  "id": 9567,
  "raw": "[06:57] <Ben64> arog: by default 5% of a filesystem is reserved for root, 5% of 909G is 45.45G, 45.45+15+848=908.45",
  "ascii": "[06:57] <Ben64> arog: by default 5% of a filesystem is reserved for root, 5% of 909G is 45.45G, 45.45+15+848=908.45",
  "tokenized": "<s> <user> : by default 5% of a filesystem is reserved for root , 5% of <unk#a> is <unk#a.> , <unk#+.=> </s>",
  "date": "2014-06-18",
  "connections": []
}
```

Same date, **annotated** region (id ≥ 10002) so you can see a nonempty `connections` list — still Hub format, not our gate:

```json
{
  "id": 10389,
  "raw": "[15:32] <daftykins> user123321: upgraded recently? tried an older kernel?",
  "ascii": "[15:32] <daftykins> user123321: upgraded recently? tried an older kernel?",
  "tokenized": "<s> <user> : upgraded recently ? tried an older kernel ? </s>",
  "date": "2014-06-18",
  "connections": [10386, 10390]
}
```

Paste block — Hub `raw` only, one string per line, as stored before any Soma parse:

```
[06:53] <arog> hi
[06:53] <arog> i just ran df -h and I noticed:: /dev/sda1       909G   15G  848G   2% /
[06:53] <arog> why is my size so large (909gb) but my available is only 848gb
[06:53] <arog> I find it difficult to believe ubuntu takes up almost 60gb
[06:54] <arog> this is without a GUI as well
[06:54] <arog> anyone around?
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

## Readable transcript (`nick: text`)

```
arog: hi
arog: i just ran df -h and I noticed:: /dev/sda1       909G   15G  848G   2% /
arog: why is my size so large (909gb) but my available is only 848gb
arog: I find it difficult to believe ubuntu takes up almost 60gb
arog: this is without a GUI as well
arog: anyone around?
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

## Note (not a labelled SPEAK example)

1. This is **Hub raw IRC**, not a Soma W=12 window and not a SPEAK/SILENT label.
2. `connections` are Kummerfeld **disentangle reply-graph** ids (who replied to whom), **not** our helper-bot gate.
3. On this slice they are empty because ids 9550–9567 sit in the unannotated context prefix; annotated edges in this file start at id 10002.
4. Consecutive `id` step is 1; same `date`; no JOIN/PART/QUIT in the stretch.
5. Four nicks in one room: arog asks, mxvxrts and Ben64 help, dunbuggy walks in — that is the multi-party mess the gate later has to watch, not a dyadic Ubuntu Dialogue Corpus thread.
