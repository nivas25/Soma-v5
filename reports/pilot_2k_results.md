# SOMA gate — silver-label PILOT (2,000 windows)

Generated (UTC): 2026-08-28T16:42:20.245743+00:00

## Model / backend

- backend: **modal**
- engine: `transformers.AutoModelForCausalLM.generate`
- model_id: `Qwen/Qwen2.5-32B-Instruct`
- revision: `5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd`
- gpu: `NVIDIA H100 80GB HBM3, 81559 MiB`
- quantization: `bf16`
- prompt_version: `pilot_v1`
- inference: temperature=0.0, top_p=1.0, max_new_tokens=80, do_sample=False
- one window per prompt / per `.remote()`: **yes**
- stack: **transformers** (no vLLM, no FlashInfer, no nvcc, no 72B-AWQ)
- writes: **resume-safe local jsonl** (skip ids already in labels/failures)

## 2000 = success + fail

- frozen ids: 2000
- success (parsed SPEAK/SILENT): **1999**
- fail (timeout/parse after 2 retries): **1**
- success + fail: **2000**
- integrity: `success=1999 fail=1 missing=0 extra=0`

## Overall rates (successes only)

- SPEAK: **233** / 1999 (11.7%)
- SILENT: **1766** / 1999 (88.3%)

## Speak rate by stratum

- question (last_is_question): SPEAK 162/700 (23.1%)
- addressed, not question: SPEAK 16/699 (2.3%)
- other: SPEAK 55/600 (9.2%)

## Speak rate vs guideline_hint (hint is NOT gold)

| hint | n | SPEAK % |
|---|---:|---:|
| addressed to human | 889 | 2.2 |
| question + no clear addressee | 491 | 32.2 |
| other | 365 | 4.1 |
| open question in last 3 | 213 | 18.8 |
| thanks | 41 | 0.0 |

## 8 example SPEAK windows

- `ubuntu:test:2005-07-06:0:0:924` **SPEAK** — last: `sktrdie: enrico: nothing happens`
  - reason: sktrdie needs help with mplayer-powerpc command
- `ubuntu:test:2007-12-01:2:0:4491` **SPEAK** — last: `NemesisD: anyone know of the boot option for ubuntu to have it not check floppy drives? i'm setting up a persistent install of ubuntu on a USB drive and it works fine on this computer but i get a bunch of fd0 i/o errors on a computer without a floppy drive`
  - reason: Unanswered question about boot option to skip floppy checks
- `ubuntu:test:2008-07-14:3:0:4730` **SPEAK** — last: `danutzu: how do I make it work??`
  - reason: Unanswered question about Pidgin Yahoo login issue
- `ubuntu:test:2008-07-14:3:0:4875` **SPEAK** — last: `kaolaBuntuPH: but you can restore softwares using it right?`
  - reason: Clarification needed on software restoration with aptoncd
- `ubuntu:test:2008-07-14:3:0:5023` **SPEAK** — last: `sHOCkwAV1: Hello, I need help configuring my wireless card. It's not working with ubuntu.`
  - reason: Unanswered request for wireless card configuration help
- `ubuntu:test:2008-07-14:3:0:5766` **SPEAK** — last: `kafitz: ive tried removing everything`
  - reason: kafitz needs help uninstalling software installed from source
- `ubuntu:test:2010-08-17:4:0:6582` **SPEAK** — last: `yanick_: this is GOOD?`
  - reason: Clarify if yanick_ needs help with system performance
- `ubuntu:test:2013-09-01:5:0:7574` **SPEAK** — last: `bazzer: on precise i just booted with a max_loop=64 to give me more loop devices and loopback mounted 16 iso images, now a pid belonging to gvfs-gdu-volume is taxing the spu at 100%....any ideas?`
  - reason: Last line is a group-facing question without an answer

## 8 example SILENT windows

- `channel_two:all_:undated:0:0:1005` **SILENT** — last: `Margene: lose 95 was 32mb`
  - reason: Last line is part of off-topic discussion about old OS.
- `channel_two:all_:undated:0:0:1006` **SILENT** — last: `Arlie: 4k was the norm for awhile`
  - reason: last line is a statement, not a question or need for help
- `channel_two:all_:undated:0:0:1069` **SILENT** — last: `Jeanice: that's GNU/communism`
  - reason: last line is chit-chat, not a stuck question
- `channel_two:all_:undated:0:0:1164` **SILENT** — last: `Paulita: i figured this was the perfect song to accompany the Mexodus to Amerika :D http://youtube.com/watch?v=8_B1BcDFdQY`
  - reason: last line is chit-chat
- `channel_two:all_:undated:0:0:1225` **SILENT** — last: `Leota: Jeanice: no the stock kernel is fine`
  - reason: question addressed and answered
- `channel_two:all_:undated:0:0:1378` **SILENT** — last: `Elli: Felicia, heh =P`
  - reason: last line is chit-chat
- `channel_two:all_:undated:0:0:1445` **SILENT** — last: `Granville: hello`
  - reason: last line is a greeting, not a request for help
- `channel_two:all_:undated:0:0:153` **SILENT** — last: `Rachel: because its not downtime!`
  - reason: last line is off-topic joke

## 8 disagreements with guideline_hint

- `channel_two:all_:undated:0:0:1164` **SILENT** — last: `Paulita: i figured this was the perfect song to accompany the Mexodus to Amerika :D http://youtube.com/watch?v=8_B1BcDFdQY`
  - reason: last line is chit-chat
- `ubuntu:test:2005-07-06:0:0:1201` **SILENT** — last: `markuman: someone here has a radeon all in wonder ???`
  - reason: last line introduces new topic, not unanswered request
- `ubuntu:test:2005-07-06:0:0:924` **SPEAK** — last: `sktrdie: enrico: nothing happens`
  - reason: sktrdie needs help with mplayer-powerpc command
- `ubuntu:test:2007-01-11:1:0:1967` **SILENT** — last: `Jowi: patrick_, so the alsa one is correct. how strange... btw in the capture tab is both the mic and speaker icons there unmuted?`
  - reason: last line is a follow-up question being handled implicitly
- `ubuntu:test:2007-01-11:1:0:2847` **SILENT** — last: `Jowi: Enverex, you think depmod -a is needed?`
  - reason: multiple unrelated threads; last line handled by Jowi
- `ubuntu:test:2007-12-01:2:0:3058` **SILENT** — last: `jimjam: Is there any way to see *all* files on a computer that have changed in the last x number of days?`
  - reason: Unrelated questions; last line not owned
- `ubuntu:test:2007-12-01:2:0:3067` **SILENT** — last: `n215: how do i setup default gw in startup for nas0 interface that wasnt created yet??`
  - reason: unrelated questions flying; last line owned by a human
- `ubuntu:test:2007-12-01:2:0:4386` **SILENT** — last: `Donne_Fashion: ciao a tutti, io ho una scheda video Intel GMA X3100 è ho installato xgl invece di aiglx. Come installo aiglx?`
  - reason: last line is in italian, offtopic for english channel

## Failures

- n=1: `not a JSON object: Extra data: line 3 column 1 (char 84)`

## Dry-run raw JSON (first 3)

1. `{"label":"SILENT","reason":"Last line is part of off-topic discussion about old OS."}`

2. `{"label":"SILENT","reason":"last line is a statement, not a question or need for help"}`

3. `{"label":"SILENT","reason":"last line is chit-chat, not a stuck question"}`

## Resume

Id file is frozen and will not be reshuffled. Re-run skips written ids.

```bash
uv run python scripts/06_silver_label_pilot.py --poll
```

## Warning

These are **SILVER** labels from a teacher LLM, **not gold**.
Do not copy them into `label_gold` on `label_queue.csv` (that column is human-only).
Humans must audit 100–200 of these windows next before any 30k/223k job.
Do not claim zero hallucination. Do not train LoRA on this pilot alone.

System prompt prefix: `You are a careful human rater in #ubuntu IRC support. You are NOT the assistant …`

