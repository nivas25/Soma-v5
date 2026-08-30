# Gate 1 — pilot_v2.2 vs Nivas gold (audit_200)

**PASS**

v2.1 leftover: empty `addressed_to` but a helper is already on the last speaker's thread.
v2.2 expands `helper_in_window` (helper language / 2+ answers to last speaker / last speaker
diagnostic / ubotu tell). If helper_in_window=yes and last line is not a brand-new group
how-to → SILENT. Harvest bar is overall ≥78% (not 80%).

- prompt_version: `pilot_v2.2`
- model: Qwen/Qwen2.5-32B-Instruct (transformers generate, temp 0, max_new_tokens=80)
- n: 200 (parse-ok 200, fail 0)
- overall agree: **171/200 (85.5%)**  (harvest need ≥ 78%)
- addressed_to nonempty: **85.0%** of 40  (need ≥ 75%)
- last_is_question: 89.0% of 91
- SPEAK rate Nivas: 90/200 (45.0%)
- SPEAK rate v2.2: 81/200 (40.5%)  (need 35–55%)
- gold SILENT / v2.2 SPEAK: 10
- gold SPEAK / v2.2 SILENT: 19
- helper_in_window=yes: 99/200

## vs v2.1

| metric | v2.1 | v2.2 | harvest need |
| --- | --- | --- | --- |
| overall | 155/200 (77.5%) | 171/200 (85.5%) | ≥78% |
| addressed | 85.0% of 40 | 85.0% of 40 | ≥75% |
| SPEAK rate | 52.5% | 40.5% | 35–55% |
| fixed from v2.1 | — | 29 | — |
| regressed vs v2.1 | — | 13 | — |

## System prompt (pilot_v2.2)

```
You label SPEAK or SILENT for an EXTRA helper-bot AFTER the last line of a 12-line IRC window.
You are not writing a reply. You do not need to know the Linux command.

Default: SILENT. Prefer SILENT when unsure.

SPEAK when:
- helper_in_window=no AND the last line is a real how-to / "anyone" / install-boot-wifi-driver-apt question with no owner.
- OR a follow-up how-to ("what should I use then?") with no owner yet.
Busy room is not a reason to stay silent if that last thread is unanswered and helper_in_window=no.

SILENT when:
- thanks / k / ok / works / fixed / good luck / nevermind
- joke, debate, offtopic, brb, language-chat, interjection ("oh man")
- last speaker is a helper giving steps or a diagnostic
- last line is Nick: to someone who already spoke in the window (helper still present), even if the user says "nothing happens" / "still fails" / "didn't accept"
- SPEAK on Nick: ONLY if that helper clearly left / is going to sleep AND the user is still stuck
- helper_in_window=yes AND the last line is not a brand-new group how-to to the room (continuation / stuck report / helper diagnostic → SILENT)
- two humans already on that thread (pile-on)
- unsure

Return ONE JSON object, no markdown:
{"label":"SPEAK"|"SILENT","reason":"<=15 words"}
```

## 15 disagreements

- `ubuntu:test:2008-07-14:3:0:4730` gold=**SPEAK** v2.2=**SILENT** helper=yes — `danutzu: how do I make it work??`
- `ubuntu:train:2004-12-25:0:0:603` gold=**SILENT** v2.2=**SPEAK** helper=no — `seb128: that's been rewritten; that's a devel branch`
- `ubuntu:train:2004-12-25:0:0:64` gold=**SILENT** v2.2=**SPEAK** helper=no — `Tsjoklate: strace xmms`
- `ubuntu:train:2005-12-23:18:0:27669` gold=**SPEAK** v2.2=**SILENT** helper=no — `lordjohnny: Somebody Spanish?`
- `ubuntu:train:2007-01-12:46:0:70050` gold=**SILENT** v2.2=**SPEAK** helper=no — `erisco: rogue780, this really isn't too good`
- `ubuntu:train:2007-01-21:48:0:73240` gold=**SPEAK** v2.2=**SILENT** helper=yes — `riotkittie: Dreamglider: no`
- `ubuntu:train:2007-02-06:50:0:76309` gold=**SPEAK** v2.2=**SILENT** helper=yes — `haxality_: nexousNET: let me know if anything I say goes over your head`
- `ubuntu:train:2007-02-15:52:0:79386` gold=**SPEAK** v2.2=**SILENT** helper=yes — `nusa42: soundray: yeah - doesn't add this ood resolution`
- `ubuntu:train:2007-06-01:53:0:81409` gold=**SPEAK** v2.2=**SILENT** helper=yes — `djieno: leagris, what is the tool?`
- `ubuntu:train:2007-07-03:56:0:85736` gold=**SILENT** v2.2=**SPEAK** helper=no — `chad_: Bladey - this is coming from a pc stand point but did you unload the is?`
- `ubuntu:train:2007-09-07:60:0:92140` gold=**SPEAK** v2.2=**SILENT** helper=yes — `Mexel: winbound, yes.`
- `ubuntu:train:2008-03-01:67:0:103542` gold=**SPEAK** v2.2=**SILENT** helper=yes — `soreau: Flannel: Selected 'primary', now I do not see where to set the type 'LVM'`
- `ubuntu:train:2008-03-01:67:0:103747` gold=**SPEAK** v2.2=**SILENT** helper=yes — `reZo: regeya: yeah, it hangs there, nothing after that line apart from the pointer blinking.`
- `ubuntu:train:2008-04-27:69:0:106377` gold=**SPEAK** v2.2=**SILENT** helper=no — `dthacker-work: !pastebin | mouseclone`
- `ubuntu:train:2008-06-03:72:0:111745` gold=**SPEAK** v2.2=**SILENT** helper=yes — `koshari: JbCrash isnt it in the repositorys? avant seems to have more support these days,`

## Remaining disagreements

29 remaining (10 false SPEAK + 19 false SILENT). vs v2.1: **fixed 29, regressed 13**.

Quieter overshoot (gold SPEAK, helper_in_window=yes): last thread already has a human, Nivas still wanted SPEAK
(`danutzu: how do I make it work??`, `djieno: leagris, what is the tool?`, `nusa42/soundray`,
`soreau/Flannel`, `reZo/regeya`, `koshari/JbCrash`, `jon1233` auto-install, `awatt` dns,
`FrankChen` ralink). Policy was prefer quieter.

False SPEAK leftover is mostly helper_in_window=no statements the teacher treats as a new how-to
(`strace xmms`, `oh man`, `!steam`, `Majost: thanks! Although…` with Majost absent from the window).

Nivas gold was not overwritten. Few-shots did not use audit_200 ids.

**PASS** (85.5% ≥ 78% AND addressed 85% ≥ 75% AND SPEAK 40.5% in 35–55%). Harvest 5k/5k is allowed.

