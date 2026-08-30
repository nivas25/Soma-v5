# Judge disagreement examples (last lines)

Nivas = gold. `+` SPEAK, `-` SILENT. Tags: A owned_thread, B hanging_question, C offtopic, E bot_already, F mid_instruction, G new_user_stuck, I pile_on, J other.

## Qwen SPEAK, Nivas SILENT (Qwen piles on)

| tag | last line | Grok |
|---|---|---|
| A | `sktrdie: enrico: nothing happens` | − |
| F | `pusling: limer: dvd do not get mountet. Pint your mediaplayer to /dev/hdc` | − |
| E | `ubotu: lsuactiafner: Wish i knew` | − |
| F | `Tsjoklate: strace xmms` | − |
| F | `ikonia: Skunkwaffle: could you explain the problem a bit more than "doesn't work"` | − |
| C | `Ryanman: oh man` | − |
| A | `Ccdc_DuckZ: Pici: I see... and what's the best way to change the symlink? …` | − |
| F | `gasull: Sean93: I meant htop` | − |
| F | `mutante: toothfairy_: just "w" for the group but no "r" or "x" ?` | − |
| A | `wafflejock: corba, strange so you can see file listings but just can't copy and paste them?` | − |

## Qwen SILENT, Nivas SPEAK (Qwen walks past a how-to)

| tag | last line | Grok |
|---|---|---|
| B | `jblack: Does the livecd come with sata support?` | + |
| B | `xtraitorx: how do i find out which version of ubuntu i have?` | + |
| B | `carthik: What's an easy to use mp3 tag editor that is intuitive to use too?` | + |
| B | `StephenL: Anyone know of good open source Project Management software?` | + |
| B | `CJKay: Has anyone had any luck getting Sun Java 6 (not 7) installed on Precise 12.04?` | + |
| B | `j_: hey, question on getting GameRanger to install under Wine` | + |
| B | `lleberg: would ubuntu work better? ;=` | + |
| B | `AshyIsMe: how do i enable the 64bit kernel in ubuntu 10?` | + |
| B | `elky: can someone remind me of the "easy" way to add a bookmark to nautilus?` | + |
| B | `Sabin: how easy is it to get KDE running on ubuntu?` | + |

## Grok SILENT, Nivas SPEAK — Grok’s `Nick:` shortcut (user still stuck)

| tag | last line |
|---|---|
| G | `nusa42: soundray: yeah - doesn't add this ood resolution` |
| G | `soreau: Flannel: Selected 'primary', now I do not see where to set the type 'LVM'` |
| G | `reZo: regeya: yeah, it hangs there, nothing after that line apart from the pointer blinking.` |
| G | `demophobia: oh, but that was last updated 2 years ago` |
| G | `jon1233: One big file that has it all and can auto-install?` |

## Grok SILENT, Nivas SPEAK — Nivas probably too loud

| tag | last line |
|---|---|
| C | `lordjohnny: Somebody Spanish?` |
| J | `Aleks-0: hello i need help` |
| C | `steven__: gonna start to cry, love ubuntu but if i cant adjust my player on my hp or broadcast... then no go.... gonna have to reinstall xp...cry` |
| I | `riotkittie: Dreamglider: no` |
| I | `haxality_: nexousNET: let me know if anything I say goes over your head` |
| I | `dthacker-work: !pastebin \| mouseclone` |
| C | `KazaLite: but did not know earlier that we need to be careful when running graphical applications` |

## Grok SPEAK, Nivas SILENT (only 3)

| tag | last line |
|---|---|
| G | `kafitz: ive tried removing everything` |
| G | `sean_: I did, and it didn't accept` |
| G | `Syrinx: no dice` |

## All three split (Qwen ≠ Grok, Nivas picks)

Nivas with Grok on hanging how-tos Qwen missed: SATA, Ubuntu version, mp3 tagger, Java 6, vm-builder, KDE, 64-bit kernel, nautilus bookmark.

Nivas with Qwen on stuck-but-addressed Grok missed: LVM type, fsck hang, resolution not added, offline codecs bundle.
