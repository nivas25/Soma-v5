# SOMA v5 four-objective closeout

No retraining. Timing is the frozen step-1200 column in `reports/lora_run/reports/test_200_predictions.csv`. This run refused to flip any SPEAK to SILENT. `helper_in_window` is not a veto: on this file the 8 false speaks all have helper=no, so that veto cannot catch them, and it would silence true speaks that already have a helper.

A clash is two different speakers, the same addressee (or the same package/path when neither line names one), and a real disagreement. Commands in two tangled threads are not a clash.

| item | n |
| --- | ---: |
| windows | 200 |
| gate SPEAK (unchanged) | 82 |
| gate SILENT (unchanged) | 118 |
| clashes recorded | 2 |
| SPEAK rows addressed as REPORT_CONFLICT | 0 |
| SPEAK rows quoting one in-window command | 2 |
| SPEAK rows with no safe command to repeat | 80 |
| SILENT rows that still record a clash | 2 |
| replies that failed the filter | 0 |

Clash kinds: failed_advice=2.

Every non-silent reply passed `check_reply`: no denylisted command, and every command span is a substring of that window. Gate macro-F1 is still **0.8776** from `reports/lora_run/reports/test_metrics.json`. This table does not replace that number.

80 of the 82 SPEAK rows have no command in the window aimed at the asker. Those replies refuse to invent one. The window `ubuntu:test:2005-07-06:0:0:274` contains both `chmod` and `dpkg` on different threads and is not flagged.

## Commands repeated from the window

- `ubuntu:train:2004-12-25:0:0:64` From this window: strace xmms
- `ubuntu:train:2011-02-23:95:0:145351` From this window: sudo apt-get update

## Clashes recorded

- `ubuntu:test:2005-07-06:0:0:924` gate=SILENT action=SILENT (failed_advice)
  - enrico: sktrdie: maybe you mispelled the package name .. search the right name .. with "sudo aptitude search mplayer"
  - sktrdie: enrico: nothing happens
- `ubuntu:train:2015-08-10:140:0:204572` gate=SILENT action=SILENT (failed_advice)
  - popey: Nakul: eek, mistake, should be "sudo apt-get update && sudo apt-get install ubuntu-desktop^" <- note tha ^
  - Nakul: I tried it like 2-3 times does not work
