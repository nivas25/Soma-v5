# Nivas gold vs Qwen silver vs Grok draft

Audit: 200 student-reviewed rows (`review_ok=Y`). Nivas `label_gold` is the reference. Qwen = `label_silver` (one empty parse fail). Grok = `grok_draft`. No new labelling. No training.

## 1. Headline numbers

Speak rates on this sheet (error-finding sample, **not** the full 2k):

| judge | SPEAK | SILENT | SPEAK % | n |
|---|---:|---:|---:|---:|
| **Nivas (gold)** | 90 | 110 | **45.0** | 200 |
| Qwen 32B | 95 | 104 | 47.7 | 199 |
| Grok draft | 71 | 129 | **35.5** | 200 |

Agreement:

| pair | agree | n | % |
|---|---:|---:|---:|
| Nivas vs Grok | 175 | 200 | **87.5** |
| Nivas vs Qwen | 122 | 199 | **61.3** |
| Qwen vs Grok | 127 | 199 | 63.8 |

Confusion vs Nivas:

|  | Qwen SPEAK | Qwen SILENT |
|---|---:|---:|
| Nivas SPEAK | 54 | **36** |
| Nivas SILENT | **41** | 68 |

|  | Grok SPEAK | Grok SILENT |
|---|---:|---:|
| Nivas SPEAK | 68 | **22** |
| Nivas SILENT | **3** | 107 |

Grok almost never speaks when Nivas is silent (3 rows). Qwen does it 41 times. Qwen also stays silent on 36 Nivas-SPEAK how-tos. Those two Qwen errors are about the same size and **point opposite ways**.

Slices (Nivas–Qwen / Nivas–Grok agree %):

| slice | n | NvQ | NvG | Nivas SPEAK % |
|---|---:|---:|---:|---:|
| last line addressed to a nick | 41 | **55.0** | 87.8 | 14.6 |
| not addressed | 159 | 62.9 | 87.4 | 52.8 |
| last_is_question | 91 | 61.5 | **92.3** | 64.8 |
| not question | 109 | 61.1 | 83.5 | 28.4 |
| thanks | 10 | **100** | **100** | 0.0 |
| hint: addressed to human | 36 | **48.6** | 86.1 | 16.7 |
| hint: open question in last 3 | 40 | **50.0** | 80.0 | 30.0 |
| hint: question + no clear addressee | 80 | 61.2 | 91.2 | 73.8 |
| mentions ubotu | 34 | 67.6 | **97.1** | 38.2 |
| thread_overlap > 0 | 56 | 58.2 | 82.1 | 51.8 |

Thanks is the only slice all three own. The Qwen hole is **addressed-to-human** and **open-in-last-3**.

88 rows differ on at least one pair. Primary tags on those 88:

| tag | n |
|---|---:|
| hanging_question | 25 |
| mid_instruction | 23 |
| owned_thread | 16 |
| new_user_stuck | 10 |
| pile_on | 6 |
| offtopic | 4 |
| other | 3 |
| bot_already | 1 |

## 2. Where Qwen differs from Nivas

**41× Qwen SPEAK / Nivas SILENT** — Qwen talks at a thread that already has a human (or a bot).

| tag | n |
|---|---:|
| mid_instruction | 20 |
| owned_thread | 16 |
| new_user_stuck | 3 |
| bot_already | 1 |
| offtopic | 1 |

Pattern: last line is `Helper: user, …` or `user: Helper: …`, often with dpkg/mplayer/LVM/strace in the text. Qwen keys off “still a problem / still a ?” and ignores who is holding the thread.

**36× Qwen SILENT / Nivas SPEAK** — Qwen walks past a room-facing how-to.

| tag | n |
|---|---:|
| hanging_question | 24 |
| pile_on (Nivas spoke; Qwen correctly silent) | 6 |
| offtopic | 3 |
| other | 2 |
| new_user_stuck | 1 |

Qwen’s own reasons on these often say “new topic”, “unrelated questions flying”, “not directly unanswered”. That is a copout: a fresh `anyone know how to X?` is exactly when the gate should SPEAK.

Quoted examples — Qwen SPEAK, Nivas SILENT:

1. `sktrdie: enrico: nothing happens` — Enrico is already debugging mplayer. Owned.
2. `pusling: limer: dvd do not get mountet. Pint your mediaplayer to /dev/hdc` — last speaker **is** the helper.
3. `ubotu: lsuactiafner: Wish i knew` — bot already took the turn.
4. `Tsjoklate: strace xmms` — helper answering “how do I strace”.
5. `ikonia: Skunkwaffle: could you explain the problem a bit more than "doesn't work"` — helper intake.
6. `Ryanman: oh man` — no ask.

Quoted examples — Qwen SILENT, Nivas SPEAK:

1. `jblack: Does the livecd come with sata support?`
2. `xtraitorx: how do i find out which version of ubuntu i have?`
3. `carthik: What's an easy to use mp3 tag editor that is intuitive to use too?`
4. `CJKay: Has anyone had any luck getting Sun Java 6 (not 7) installed on Precise 12.04?`
5. `j_: hey, question on getting GameRanger to install under Wine`
6. `lleberg: would ubuntu work better? ;=` (PII / Win98)

## 3. Where Grok differs from Nivas

Grok is the conservative copy of Nivas. **22 misses are Grok SILENT / Nivas SPEAK. Only 3 are extra SPEAK.**

**Grok SPEAK / Nivas SILENT (3)** — all `new_user_stuck` without a clean owner:

1. `kafitz: ive tried removing everything`
2. `sean_: I did, and it didn't accept`
3. `Syrinx: no dice`

Nivas wanted more of a question / an active helper. Grok treated “still broken” as SPEAK.

**Grok SILENT / Nivas SPEAK (22)**

| tag | n |
|---|---:|
| pile_on | 6 |
| new_user_stuck | 6 |
| offtopic | 3 |
| other | 3 |
| hanging_question | 2 |
| mid_instruction | 2 |

The real Grok bug (6 rows): **Name: in the last line → SILENT even when that user is still failing** (wrong resolution after `dpkg-reconfigure`, LVM type missing, fsck hang, wiki 404). That is the “every `Nick:` is owned” shortcut.

The other 6 are Nivas speaking while a helper is already mid-step (`!pastebin`, `Dreamglider: no`, walking someone through wifi). Those are Nivas pile-ons; Grok matches the rubric.

Quoted examples — Grok SILENT, Nivas SPEAK (Grok too quiet):

1. `nusa42: soundray: yeah - doesn't add this ood resolution`
2. `soreau: Flannel: Selected 'primary', now I do not see where to set the type 'LVM'`
3. `reZo: regeya: yeah, it hangs there, nothing after that line apart from the pointer blinking.`
4. `demophobia: oh, but that was last updated 2 years ago`
5. `jon1233: One big file that has it all and can auto-install?`
6. `godsring: I honestly dont know where else to go`

Quoted examples — Grok SILENT, Nivas SPEAK (Nivas probably too loud):

1. `lordjohnny: Somebody Spanish?`
2. `Aleks-0: hello i need help`
3. `steven__: gonna start to cry, love ubuntu but if i cant adjust my player on my hp or broadcast... then no go.... gonna have to reinstall xp...cry`
4. `riotkittie: Dreamglider: no`
5. `haxality_: nexousNET: let me know if anything I say goes over your head`
6. `KazaLite: but did not know earlier that we need to be careful when running graphical applications`

## 4. Qwen vs Grok, Nivas picks a side

On the 72 rows where Qwen ≠ Grok and both are SPEAK/SILENT:

- **Nivas with Grok: 62**
- **Nivas with Qwen: 10**

With Grok, the tags are owned_thread (16), mid_instruction (20), hanging_question (23). Translation: when Qwen and Grok fight, Nivas takes Grok’s **don’t pile on a live helper** *and* Grok’s **do answer a hanging how-to**. Qwen is wrong on both ends of that fight.

The 10 times Nivas sides with Qwen against Grok are almost all **new_user_stuck** addressed to a helper (resolution still wrong, installer hang). There Grok’s `Nick:` rule is too cheap.

## 5. Hackiness scorecard

Hackiness = a shortcut instead of the rubric.

**Qwen**
- Habit 1: SPEAK if the last line has a problem keyword or a `?`, even when the last speaker is the helper (`strace xmms`, `Pint your mediaplayer`, `I meant htop`).
- Habit 2: SILENT on a clean group how-to if another thread is in the window (“unrelated questions flying”).
- Habit 3: Treats ubotu’s turn as “still unanswered” (`Wish i knew`).
- Failures: 20 mid_instruction false SPEAK; 16 owned_thread false SPEAK; 24 hanging_question false SILENT.
- Trust when: last line is thanks (perfect) or a brand-new group ask **and** you have checked nobody is already on it. Do not trust Qwen SPEAK on `Name:`.

**Grok**
- Habit 1: SILENT on `Name:` almost always (good on helpers, blind on stuck follow-ups).
- Habit 2: SPEAK on unanswered room-facing how-tos, including recs and “does X exist”.
- Habit 3: Almost never invents a SPEAK Nivas didn’t want (3 extras, all “still broken”).
- Failures: 6 addressed-stuck false SILENT; slightly over-silent on “I don’t know where else to go”.
- Trust when: deciding whether to pile onto an active helper. Do not trust Grok SILENT just because a nick appears in the last line.

**Nivas**
- Habit 1: SPEAK on hanging how-tos even in a busy room (SATA, version, Java 6, vm-builder).
- Habit 2: SILENT on thanks (10/10 with both models).
- Habit 3: Sometimes SPEAK when the last line is the helper talking, or when the line is venting / “anybody Spanish” / “hello I need help”.
- Failures: 6 pile_on; 3 offtopic SPEAK; 3 vague/other SPEAK.
- Trust when: “is this a real unanswered Ubuntu how-to?” Less trust on helper-last-line and offtopic.

Nobody is copying `guideline_hint` blindly. On `addressed to human` Nivas speaks 16.7%; Qwen still fights him (48.6% agree). On `question + no clear addressee` Nivas speaks 73.8% and Grok tracks him; Qwen does not.

## 6. What the gold policy actually is

Nivas’s gate is: **default SILENT, but SPEAK if the last line is a group-facing Ubuntu how-to or a stuck user with no owner.** He does not need a `?`. He does not wait for the room to go quiet. He stays silent on thanks, greetings, and (usually) on a helper who is already in the middle of steps. He will SPEAK over a `Nick:` if the user is reporting that the last step failed. He is slightly more willing than the written rubric to SPEAK on soft asks (recs, “would it work”, “is forums down”) and he has a handful of pile-ons.

## 7. Next silver-teacher prompt — add / delete

**Delete / stop rewarding**
- Any path that treats “other questions in the window” as a reason to SILENT on the **last** line.
- Reasons like “new topic, not unanswered”.
- SPEAK just because the line contains a package, command, or `?`.

**Add, verbatim**
- If the last speaker is a helper already giving steps to someone in the window, SILENT. Do not pile on.
- If the last line is addressed to a nick who is in the window **and** that nick is handling the thread, SILENT — **unless** the last line reports the previous step failed (nothing happens, hangs, didn’t accept, still the same error). Then SPEAK.
- If the last line is a group-facing how-to / anyone / does Ubuntu do X, and nobody in the window has taken that thread, SPEAK even if other conversations are running.
- If ubotu/ubottu already answered that last ask, SILENT.
- Thanks / works / k / good luck / going to sleep: SILENT. No exceptions in this file.

## 8. Do we still want Qwen as the volume teacher?

**No, not with this prompt.** Speak rate looks close (47.7 vs 45.0) and that is a trap: Qwen is loud on owned threads and quiet on hanging how-tos, so the averages cancel and the labels are wrong in the two buckets that matter. 61% vs Nivas on an adversarial 200 is not a volume teacher.

Grok is the better clone of Nivas (87.5%) and the remaining errors are a small, named bug (`Nick:` + still stuck). For the next 30k, either:

1. keep Qwen 32B **only after** the prompt rewrite above, then re-pilot 200 new ids, or
2. use a Grok-class teacher with the same rewrite (do not ship Grok’s `Nick:` shortcut as-is).

Do not train LoRA on Qwen silver. Do not promote the 1,800 unreviewed silver rows.
