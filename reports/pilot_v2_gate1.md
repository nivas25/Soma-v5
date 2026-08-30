# Gate 1 — pilot_v2 vs Nivas gold (audit_200)

**FAIL**

- prompt_version: `pilot_v2`
- model: Qwen/Qwen2.5-32B-Instruct (transformers generate, temp 0, max_new_tokens=80)
- n: 200 (parse-ok 200, fail 0)
- overall agree: **147/200 (73.5%)**  (need ≥ 80%)
- addressed_to nonempty: **62.5%** of 40  (need ≥ 75%)
- last_is_question: 75.8% of 91
- SPEAK rate Nivas: 90/200 (45.0%)
- SPEAK rate v2: 123/200 (61.5%)

## System prompt (pilot_v2)

```
You label SPEAK or SILENT for an EXTRA helper-bot AFTER the last line of a 12-line IRC window.
You are not writing a reply. You do not need to know the Linux command.

Default: SILENT.

SPEAK when:
- The last line is a real how-to / “anyone” / install-boot-wifi-driver-apt question and nobody in the window owns that thread.
- OR the last line is still-broken (“nothing happens”, “still fails”, same error after a step), even if it says Nick:.
Busy room is not a reason to stay silent if that last thread is unanswered.

SILENT when:
- thanks / k / ok / works / fixed / good luck / nevermind
- joke, debate, offtopic, brb
- a human is mid-step on that exact thread and the last line is NOT a failure report
- last line is Nick: to someone already helping AND the last step has not failed
- unsure

Return ONE JSON object, no markdown:
{"label":"SPEAK"|"SILENT","reason":"<=15 words"}
```

## 15 disagreements

- `ubuntu:test:2005-07-06:0:0:924` gold=**SILENT** v2=**SPEAK** — `sktrdie: enrico: nothing happens`
- `ubuntu:test:2008-07-14:3:0:5766` gold=**SILENT** v2=**SPEAK** — `kafitz: ive tried removing everything`
- `ubuntu:test:2014-06-18:6:0:9598` gold=**SILENT** v2=**SPEAK** — `tomengland: what does that do`
- `ubuntu:test:2015-03-18:7:0:10537` gold=**SILENT** v2=**SPEAK** — `brx_: i want like a glow effect when i click the mouse`
- `ubuntu:train:2005-06-12:7:0:9961` gold=**SILENT** v2=**SPEAK** — `pusling: limer: dvd do not get mountet. Pint your mediaplayer to /dev/hdc`
- `ubuntu:train:2005-06-16:8:0:11649` gold=**SILENT** v2=**SPEAK** — `sinnlos: german ?`
- `ubuntu:train:2005-09-26:12:0:17826` gold=**SILENT** v2=**SPEAK** — `pythonscript: so adjacent where is things to read ? I'm absolutely newbie don't know much`
- `ubuntu:train:2005-12-03:15:0:22548` gold=**SILENT** v2=**SPEAK** — `Lokadin: cafuego: yes it is, because netstat says it is, and gtk-gnutella says that it's being blocked by a firewall`
- `ubuntu:train:2005-12-04:16:0:24107` gold=**SILENT** v2=**SPEAK** — `sean_: I did, and it didn't accept`
- `ubuntu:train:2005-12-16:17:0:24869` gold=**SILENT** v2=**SPEAK** — `_jason: ubotu, tell j1b about easysource`
- `ubuntu:train:2005-12-23:18:0:27669` gold=**SPEAK** v2=**SILENT** — `lordjohnny: Somebody Spanish?`
- `ubuntu:train:2006-06-08:31:0:47315` gold=**SILENT** v2=**SPEAK** — `xpat: farous:  sorry, don't know how to access that....advice ?`
- `ubuntu:train:2006-12-10:44:0:67311` gold=**SILENT** v2=**SPEAK** — `Kingsqueak: cmweb: connect with it?`
- `ubuntu:train:2007-01-21:48:0:73240` gold=**SPEAK** v2=**SILENT** — `riotkittie: Dreamglider: no`
- `ubuntu:train:2007-02-06:50:0:76309` gold=**SPEAK** v2=**SILENT** — `haxality_: nexousNET: let me know if anything I say goes over your head`

Nivas gold was not overwritten. Few-shots did not use audit_200 ids.
Harvest is blocked on FAIL.

