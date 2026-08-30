# Gate 1 — pilot_v2.1 vs Nivas gold (audit_200)

**FAIL**

v2 failed at 73.5% / addressed 62.5% / SPEAK 61.5%. Root: SHOT5 taught
`enrico: nothing happens → SPEAK` while Nivas gold is SILENT when that helper is still present.
v2.1 flips that shot, adds two more SILENT Nick:+stuck+helper-present sketches,
and SPEAKs on Nick: only if the helper left/sleeps.

- prompt_version: `pilot_v2.1`
- model: Qwen/Qwen2.5-32B-Instruct (transformers generate, temp 0, max_new_tokens=80)
- revision: `5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd`
- gpu: NVIDIA H100 80GB HBM3
- n: 200 (parse-ok 200, fail 0)
- overall agree: **155/200 (77.5%)**  (need ≥ 80%)
- addressed_to nonempty: **85.0%** of 40  (need ≥ 75%)
- last_is_question: 80.2% of 91
- SPEAK rate Nivas: 90/200 (45.0%)
- SPEAK rate v2.1: 105/200 (52.5%)  (need 35–55%)
- gold SILENT / v2.1 SPEAK: 30
- gold SPEAK / v2.1 SILENT: 15

PASS needs all three: overall ≥80% **and** addressed ≥75% **and** SPEAK 35–55%.
Addressed and SPEAK-rate pass. Overall misses by 5 rows (2.5pp). Harvest blocked.

## Delta vs v2

| metric | v2 | v2.1 | need |
| --- | --- | --- | --- |
| overall | 147/200 (73.5%) | 155/200 (77.5%) | ≥80% |
| addressed_to nonempty | 62.5% of 40 | **85.0% of 40** | ≥75% |
| last_is_question | 75.8% of 91 | 80.2% of 91 | — |
| SPEAK rate | 123/200 (61.5%) | **105/200 (52.5%)** | 35–55% |
| gold SILENT / teacher SPEAK | (loud Nick:) | 30 | — |
| gold SPEAK / teacher SILENT | — | 15 | — |

v2.1 vs v2 on the same 200 ids: **fixed 17, regressed 9, still wrong 36**.

SHOT5 flip worked. Canonical fail `ubuntu:test:2005-07-06:0:0:924`
(`sktrdie: enrico: nothing happens`) is now **SILENT**, matching Nivas.

Also quieted the other owned Nick: v2 false-SPEAKs (xpat/farous, Lokadin/cafuego,
Kingsqueak/cmweb, mrdk/ASULutzy, FriGiN/urlin2u, bullgard4/ActionParsnip, ikonia/Skunkwaffle).

## System prompt (pilot_v2.1)

```
You label SPEAK or SILENT for an EXTRA helper-bot AFTER the last line of a 12-line IRC window.
You are not writing a reply. You do not need to know the Linux command.

Default: SILENT. Prefer SILENT when unsure.

SPEAK when:
- The last line is a real how-to / "anyone" / install-boot-wifi-driver-apt question AND nobody in the window owns that thread.
- OR a follow-up how-to ("what should I use then?") with no owner yet.
Busy room is not a reason to stay silent if that last thread is unanswered.

SILENT when:
- thanks / k / ok / works / fixed / good luck / nevermind
- joke, debate, offtopic, brb, language-chat
- last speaker is a helper giving steps or a diagnostic
- last line is Nick: to someone who already spoke in the window (helper still present), even if the user says "nothing happens" / "still fails" / "didn't accept"
- SPEAK on Nick: ONLY if that helper clearly left / is going to sleep AND the user is still stuck
- two humans already on that thread (pile-on)
- unsure

Return ONE JSON object, no markdown:
{"label":"SPEAK"|"SILENT","reason":"<=15 words"}
```

Payload is Grok-style plus `helper_in_window=yes/no` (addressed nick already spoke).
No `guideline_hint`. Few-shots are `shot:*` ids only — none of the audit_200 window_ids.

## 15 disagreements

- `ubuntu:test:2008-07-14:3:0:5766` gold=**SILENT** v2.1=**SPEAK** — `kafitz: ive tried removing everything`
- `ubuntu:test:2014-06-18:6:0:9598` gold=**SILENT** v2.1=**SPEAK** — `tomengland: what does that do`
- `ubuntu:test:2015-03-18:7:0:10537` gold=**SILENT** v2.1=**SPEAK** — `brx_: i want like a glow effect when i click the mouse`
- `ubuntu:test:2016-02-22:8:0:12938` gold=**SILENT** v2.1=**SPEAK** — `PHroGman: i wanted access to add to backgrounds folder and edit trustywallpapers xml`
- `ubuntu:train:2005-09-26:12:0:17826` gold=**SILENT** v2.1=**SPEAK** — `pythonscript: so adjacent where is things to read ? I'm absolutely newbie don't know much`
- `ubuntu:train:2005-12-04:16:0:24107` gold=**SILENT** v2.1=**SPEAK** — `sean_: I did, and it didn't accept`
- `ubuntu:train:2005-12-16:17:0:24869` gold=**SILENT** v2.1=**SPEAK** — `_jason: ubotu, tell j1b about easysource`
- `ubuntu:train:2005-12-23:18:0:27669` gold=**SPEAK** v2.1=**SILENT** — `lordjohnny: Somebody Spanish?`
- `ubuntu:train:2007-01-21:48:0:73240` gold=**SPEAK** v2.1=**SILENT** — `riotkittie: Dreamglider: no`
- `ubuntu:train:2007-02-06:50:0:76309` gold=**SPEAK** v2.1=**SILENT** — `haxality_: nexousNET: let me know if anything I say goes over your head`
- `ubuntu:train:2007-02-07:51:0:77249` gold=**SILENT** v2.1=**SPEAK** — `eternalswd: fula_, does it fully boot and then reboot at random times or does it reboot while booting?`
- `ubuntu:train:2007-02-15:52:0:79386` gold=**SPEAK** v2.1=**SILENT** — `nusa42: soundray: yeah - doesn't add this ood resolution`
- `ubuntu:train:2007-07-03:56:0:86501` gold=**SILENT** v2.1=**SPEAK** — `sam_: for bash?`
- `ubuntu:train:2007-08-22:58:0:89986` gold=**SPEAK** v2.1=**SILENT** — `mudkipdesu: yeah its a flat screen`
- `ubuntu:train:2007-09-07:60:0:92140` gold=**SPEAK** v2.1=**SILENT** — `Mexel: winbound, yes.`

45 disagreements total (30 false SPEAK + 15 false SILENT). First 15 shown, same format as v2.

## Remaining clusters (not Nick: anymore)

Addressed-to-human is no longer the miss. Only **6/45** disagreements have nonempty `addressed_to`
(1 false SPEAK, 5 false SILENT). The leftover 30 false SPEAKs sit on **empty addressed_to**.

### 1. Last speaker is already the helper (diagnostic / mid-step)

Nivas SILENT: do not pile on. Teacher SPEAK: "unanswered how-to, no owner".
`helper_in_window=no` because `addressed_to` is empty even though the last speaker *is* the helper.

Examples: `eternalswd: fula_, does it fully boot…`, `DuncanNZ: so did you run the command?`,
`ChogyDan: Melissa_McC, are you on a terminal?`, `cfhowlett: Guddu, could yes. should? no.`,
`_jason: ubotu, tell j1b about easysource`.

### 2. User stuck, helper in the window, but last line has no Nick:

Canonical leftover: `sean_: I did, and it didn't accept` (`24107`). bluefox83 just told him
`su` + root password in the same window. Nivas SILENT. Teacher SPEAK because
`addressed_to=""` so `helper_in_window=no`. Same shape: `kafitz: ive tried removing everything`
(redduck676 already asking), `Syrinx: no dice` (_Tristan already answering),
`brx_: i want like a glow effect` (Ben64/ubottu already on it).

v2.1's Nick: law only fires when the last line is `Nick:` **and** that nick spoke.
Empty `addressed_to` + helper present is the new loud cluster.

### 3. Vague / not a real how-to still SPEAK

`tomengland: what does that do`, `pythonscript: where is things to read`, `sam_: for bash?`,
`Ryanman: oh man`, `apos: drill?`, `kk_: Which icon?`. Teacher over-generalizes "question → SPEAK".

### 4. Quieter overshoot on a few Nivas SPEAK Nick: rows

Teacher SILENT, gold SPEAK: `nusa42: soundray: yeah - doesn't add this ood resolution`,
`soreau: Flannel: … now I do not see where to set the type LVM`,
`reZo: regeya: yeah, it hangs there`. Helper is present; user is stuck; Nivas still wanted SPEAK.
Policy here was "SILENT almost always unless helper left". Prefer quieter: leave these.

If a later retry happens: teach **last speaker is a helper → SILENT** and **helper present even
without Nick: prefix → SILENT**. Do not re-open the v2 still-broken→SPEAK law.

Nivas gold was not overwritten. Few-shots did not use audit_200 ids.
Harvest is blocked unless PASS. No 5k, no LoRA, no v1 mix.
