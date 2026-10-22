<p align="center">
  <img src="web/src/assets/logo.png" alt="SOMA compass mark" width="180">
</p>

<p align="center">
  <img src="docs/soma-wordmark.svg" alt="SOMA" width="420">
</p>

<p align="center">
  <strong>Synthetic Orchestrator for Meaningful Assistance</strong><br>
  A SPEAK / SILENT gate for multi-party Ubuntu IRC, and the group chat that uses it.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-0b5d50" alt="MIT license">
  <img src="https://img.shields.io/badge/python-3.11%2B-e6b325" alt="Python 3.11 or newer">
  <img src="https://img.shields.io/badge/model-Qwen2.5--7B-0e6f60" alt="Qwen2.5 7B">
  <img src="https://img.shields.io/badge/serve-Modal%20H100-094e43" alt="Served on Modal H100">
  <img src="https://img.shields.io/badge/room-ubuntu-14967c" alt="Room ubuntu">
</p>

SOMA watches a group chat. People talk. When the room has been quiet, a trained gate decides whether an extra helper should speak. If the decision is SPEAK, a second model drafts one short Ubuntu answer and the room posts it under the name SOMA, quoting the line it answers. If the decision is SILENT, the room stays quiet.

The default decision is SILENT. The nick `soma` is reserved for the bot.

## Contents

- [Overview](#overview)
- [What you see in the room](#what-you-see-in-the-room)
- [How a turn works](#how-a-turn-works)
- [Reply checks](#reply-checks)
- [Models](#models)
- [Requirements](#requirements)
- [Run the chat](#run-the-chat)
- [Stop](#stop)
- [Configuration](#configuration)
- [Tests](#tests)
- [Repository layout](#repository-layout)
- [Data](#data)
- [Data scripts](#data-scripts)
- [Gate score](#gate-score)
- [License](#license)
- [Authors](#authors)

## Overview

| Label | Detail |
| --- | --- |
| Project | SOMA, a capstone group-chat helper for Ubuntu support. |
| Decision | One token after the last line of a 12-line window: `SPEAK` or `SILENT`. |
| Gate | Qwen2.5-7B-Instruct plus a LoRA adapter. Macro-F1 0.878 on the 200 gold windows. Best checkpoint is step 1200. |
| Reply | The same 7B base, no adapter, greedy decoding. One JSON object, one short answer. |
| Where they run | Two Modal apps, `soma-gate` and `soma-reply`, each on an H100. |
| Where people talk | This machine, http://127.0.0.1:8787, room `ubuntu`. |
| Memory | The room lives in the server process. A restart clears every line. |
| Training | The gate is already trained. This repository serves it. It does not retrain it when the chat starts. |

The upstream text is Ubuntu IRC from [jkkummerfeld/irc_disentangle](https://huggingface.co/datasets/jkkummerfeld/irc_disentangle) (Kummerfeld et al., ACL 2019). SOMA adds the SPEAK/SILENT labels. The Hub dump has none.

## What you see in the room

Open http://127.0.0.1:8787 after the server and the page build are up.

| Label | Detail |
| --- | --- |
| Join | Pick a nick and a room. The demo room is `ubuntu`. |
| Nick rules | A nick starts with a letter, then letters, digits, `_`, or `-`, up to 20 characters. `soma` is rejected for a person. |
| Human lines | White bubbles. The name and the text. They appear as soon as they are posted. |
| SOMA lines | A green bubble. The name SOMA is heavier. One quoted line shows the human message it answers. |
| Hidden on the thread | The token, the raw model text, and the reason stay off the bubble. |
| Typing | A line such as “Nivas typing” with three dots. It expires 1.5 seconds after the last typing post. |
| Gate button | In the header. Off when the page loads. The column is not mounted until you turn it on. |
| Gate column | For each human line that reached the gate: line id, nick, token, raw model text, the payload that was sent, and the stages that actually ran. A failed call shows the exception type and that nothing was posted. |
| Several people | Open the same URL in another browser and join the same room with another nick. |

## How a turn works

1. A human line is stored at once.
2. Idle is true only when nobody is typing, the room has a human line, and the last activity is at least `SOMA_IDLE_S` seconds old. The default is 4.
3. The room builds the last 12 lines and calls `soma-gate` once for that line. A second idle on the same settled line does not call again.
4. `SILENT` posts nothing.
5. `SPEAK` asks `soma-reply` for one draft. The draft is checked before anything is posted.
6. A passing draft is appended as nick `soma`, with `reply_to` set to the human line the gate ran on.
7. If another person speaks while the model is running, or the room generation changes, the draft is dropped and nothing is appended.

The payload is the v2.2 window format: room flags, then the chat block, then the instruction to decide after the last line. The gate’s own system text is the training instruction. Anything that is not the token SPEAK or SILENT is treated as SILENT.

## Reply checks

The checks run in this order. A later check still sees the text the earlier step produced.

| Label | What it looks at | What the room does |
| --- | --- | --- |
| JSON | The reply model must return one JSON object. | Invalid JSON posts nothing. Reason `not_json`. |
| Empty or `NONE` | The `reply` field is empty or the word NONE. | Nothing is posted, unless the question itself asks for a destructive action. |
| Clean | The draft is trimmed to one short answer. | An empty clean result posts nothing, unless the question is destructive. |
| Denied or destructive | Commands such as `rm -rf`, `mkfs`, `dd if=`, `chmod 777`, a fork bomb, shutdown, or a pipe into a shell. Also questions about erasing or formatting a disk, overwriting root, or wiping a filesystem. | A line is posted. It starts with `This will erase data. Be careful.` A denied command may follow in backticks. The raw dangerous command is never the whole reply. |
| Overlap | The same command surface is already in the window. `df -h` matches a window that already has `df -h /`. The longer form does not match a window that only has the shorter form. | Nothing is posted. |
| Contradicts | A second model call asks whether the draft contradicts a fact already in the window. A new command by itself is not a contradiction. A failed call fails closed. | Nothing is posted. |
| Ordinary answer | Example: “how do I check free disk space on ubuntu?” | The cleaned draft is posted unchanged. A `df -h` answer stays a `df -h` answer. |

## Models

Both apps use `Qwen/Qwen2.5-7B-Instruct` at revision `a09a35458c702b33eeacc393d103063234e8bc28`.

| Label | `soma-gate` | `soma-reply` |
| --- | --- | --- |
| Module | `src/soma_data/modal_gate.py` | `src/soma_data/modal_reply.py` |
| Class | `Gate` | `Reply` |
| Weights | Base model plus `models/soma-gate-lora-best/best_adapter` | Base model only |
| LoRA | r = 16, alpha = 32, dropout 0.05 | none |
| Decoding | Greedy, 8 new tokens | Greedy, 96 new tokens |
| Output | Raw text, then parsed to SPEAK or SILENT | One JSON object. No markdown and no code fence. |
| GPU | H100, 64 GB RAM, 8 CPU | H100, 64 GB RAM, 8 CPU |
| Cold start budget | 30 minutes | 30 minutes |
| Call budget | 10 minutes | 10 minutes |
| Scale down | 2 minutes with no traffic | 5 minutes with no traffic |
| Secret | Modal secret named `huggingface` | Modal secret named `huggingface` |
| Deploy | `uv run python -m modal deploy src/soma_data/modal_gate.py` | `uv run python -m modal deploy src/soma_data/modal_reply.py` |

The adapter file `adapter_model.safetensors` is gitignored. A gate deploy from a fresh clone fails until that file is present at `models/soma-gate-lora-best/best_adapter/`. The first call after a cold start loads the model and can take about a minute. Deploy again after a code change, and stop the warm container, or the old container keeps serving the previous code.

`src/soma_data/modal_lora.py` is the training app. It is not the server the room calls.

## Requirements

| Label | What you need |
| --- | --- |
| Python | 3.11 or newer. This project is developed on 3.12. |
| uv | [uv](https://docs.astral.sh/uv/) installs the locked dependencies. |
| Node.js | npm, to build the page in `web/`. Node 22 is what the UI tests use. |
| Modal | An account that can deploy the two apps, plus the `huggingface` secret. |
| Adapter | The local LoRA directory above, on the machine that runs `modal deploy` for the gate. |
| Shell note | Commands below are PowerShell. Use `python -m`. `uv run modal` and `uv run pytest` fail here with “Failed to canonicalize script path”. |

Copy `.env.example` to `.env` when you download the Hugging Face IRC dumps or run the older data scripts. Leave every secret empty in git. The chat server does not read `GEMINI_API_KEY`.

## Run the chat

One command from the repo root starts both Modal apps, warms them, and starts the room. One command stops all of that.

```powershell
uv run python scripts/soma_ctl.py up
uv run python scripts/soma_ctl.py down
```

`up` deploys `soma-gate` and `soma-reply`, calls each once so the H100 loads, and serves http://127.0.0.1:8787. If that page is already served by `python -m soma_data.chat_app`, `up` leaves the process alone so the room is not cleared. `down` stops both Modal apps and that local process. A stop clears the in-memory room.

The steps below are the same work, one piece at a time.

Run these from the repository root, in this order.

### 1. Python packages

```powershell
uv sync --extra dev
```

This installs FastAPI, the Modal client, and the data libraries. The optional `dev` extra installs pytest.

### 2. Page

The server serves `web/dist`. Without that folder the API still answers and the browser has no page.

```powershell
Set-Location web
npm install
npm run build
Set-Location ..
```

`npm run dev` is the Vite dev server. The room people join is the build served by the Python process on port 8787.

### 3. Modal apps

```powershell
uv run python -m modal deploy src/soma_data/modal_gate.py
uv run python -m modal deploy src/soma_data/modal_reply.py
```

### 4. Room server

```powershell
uv run python -m soma_data.chat_app
```

Then open http://127.0.0.1:8787 and join room `ubuntu`.

## Stop

```powershell
uv run python -m modal app stop soma-gate -y
uv run python -m modal app stop soma-reply -y
```

Stop the `python -m soma_data.chat_app` process as well. Stopping Modal leaves the lines in the running server. Stopping the Python process clears the room.

## Configuration

| Label | Default | Meaning |
| --- | --- | --- |
| `SOMA_IDLE_S` | `4` | Seconds of quiet before the gate runs. |
| Host | `127.0.0.1` | The server binds to localhost only. |
| Port | `8787` | Fixed in `chat_app.main`. |
| Window | 12 lines | The gate sees the last 12 lines ending at the latest human line. |
| Typing expiry | 1.5 seconds | Composer-quiet. This is not the reply timer. |
| Poll | 2 seconds | The page refreshes the room on this interval. |
| `HF_TOKEN` | empty in `.env.example` | Used by the data download scripts and by the Modal secret, not written into source. |
| `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` | empty in `.env.example` | Modal credentials, if you do not use the Modal CLI login. |
| `GEMINI_API_KEY` | empty in `.env.example` | Read only by the offline Gemini client. The live room does not call it. |

## Tests

```powershell
uv run python -m pytest
```

| Label | File | What it locks |
| --- | --- | --- |
| Room | `tests/test_chat_room.py` | Join, post, typing, and the rule that the nick `soma` is reserved. |
| Idle | `tests/test_gate_idle.py` | The gate is not called before the quiet time, and it is called once after. |
| Thread | `tests/test_reply_thread.py` | A passing draft becomes one SOMA line that quotes the human line. |
| Gate column | `tests/test_gate_column.py` | The column is absent on first paint and present after the Gate button. |
| Stages | `tests/test_gate_stages.py` | The stage list matches the steps that actually ran, including a dropped overlap. |
| Caution | `tests/test_caution.py` | An erase-the-disk question is posted with the caution line. A later `df -h` question is unchanged. Overlap still drops a repeated dangerous command. |
| Speak checks | `tests/test_speak_phase1.py`, `tests/test_speak_phase2.py` | Draft parsing and the check order, with the models stubbed. |
| Denied commands | `tests/test_reply_check.py` | The denylist used by the older checker. |
| Offline objectives | `tests/test_four_objectives.py` | Conflict detection and the offline decide path. |
| Live Modal | `tests/test_reply_live.py` | Real calls to the deployed reply model. Both apps need to be up. |

The UI test renders the page with Vite and happy-dom. It does not open a browser.

## Repository layout

| Label | Path | Detail |
| --- | --- | --- |
| Room | `src/soma_data/chat_app.py` | In-memory rooms, idle, one gate call, draft checks, and HTTP on port 8787. |
| Gate serve | `src/soma_data/modal_gate.py` | Modal app `soma-gate`. |
| Reply serve | `src/soma_data/modal_reply.py` | Modal app `soma-reply`. |
| Draft | `src/soma_data/speak.py` | Reply prompt, clean step, caution path, overlap, and contradiction. |
| Overlap | `src/soma_data/speak_validate.py` | Command surfaces and the contradiction question. |
| Denylist | `src/soma_data/validate_reply.py` | Patterns that mark a command as dangerous. |
| Train | `src/soma_data/modal_lora.py` | LoRA training only. |
| Window text | `src/soma_data/teacher_prompt_v2_2.py` | The v2.2 instruction and payload builder the live gate uses. |
| Page | `web/src` | React room. `npm run build` writes `web/dist`, which is gitignored. |
| Mark | `web/src/assets/logo.png` | Compass mark used by the page and by this README. |
| Wordmark | `docs/soma-wordmark.svg` | Pixel-art SOMA wordmark used by this README. |
| Data scripts | `scripts/01` through `scripts/17` | Download, windows, silver labels, gold audit, and the training launch. |
| Adapter | `models/soma-gate-lora-best/` | Local weights. Not in git. |

These files are in the repository and they are not the live decision:

| Label | Path | Detail |
| --- | --- | --- |
| Keyword gate | `src/soma_data/room_gate.py` | An older pattern check. The room does not call it to decide SPEAK or SILENT. |
| Offline conflict | `src/soma_data/conflict.py`, `src/soma_data/decide.py` | Used by the four-objective eval. |
| Gemini client | `src/soma_data/gemini_client.py` | HTTP client for offline scripts. The key stays in the environment. |
| Gemini demo | `scripts/20_speak_demo.py` | Calls Gemini through `compose_reply`. The room server does not start it. |
| Offline replies | `scripts/18_run_four_objectives.py`, `scripts/19_llm_replies.py` | Write the tables in `reports/v5_*`. |
| Frozen writer | `src/soma_data/modal_writer.py` | An offline 7B writer. It is not `soma-reply`. |

## Data

| Label | Detail |
| --- | --- |
| Source | [`jkkummerfeld/irc_disentangle`](https://huggingface.co/datasets/jkkummerfeld/irc_disentangle). Paper [P19-1374](https://aclanthology.org/P19-1374/) / [arXiv:1810.11118](https://arxiv.org/abs/1810.11118). |
| License of the logs | CC-BY-4.0. Accept the Hub license before `scripts/01_download.py`. |
| One row | One IRC line: `id`, `raw`, `ascii`, `tokenized`, `date`, `connections`. |
| Labels | SPEAK and SILENT, added by this project. |
| Corpus | Ubuntu IRC disentanglement. This is not the Lowe/McGill Ubuntu Dialogue Corpus. |
| Window | 12 lines. No stemming, no lemmatizing, no stopword list, no lowercasing. |
| Gold | 200 human-audited windows in `data/silver/audit_200.csv` and `data/processed/sft_test.jsonl`. |
| Friend holdout | 400 windows. The gold columns in those CSVs are empty until someone fills them. |
| Silver | About 5,100 SPEAK and 16,250 SILENT from the v2.2 teacher. The jsonl dumps are gitignored. |
| Train file | `sft_train_1to3.jsonl` is gitignored. Rebuild it with the harvest scripts, then `scripts/15_export_sft_and_eda.py` and `scripts/16_freeze_friends_and_splits.py`. |

| In this clone | Left out, on purpose |
| --- | --- |
| Code under `src/`, `scripts/`, `tests/`, and `web/src` | `data/raw/*.parquet` |
| The 200 gold windows | Teacher silver jsonl |
| Friend-holdout CSVs | LoRA `.safetensors` |
| Reports and figures | `node_modules`, `web/dist`, `.env` |

Preprocessing notes are in `reports/data_preprocessing.md`.

## Data scripts

| Script | What it does |
| --- | --- |
| `01_download.py` | Hub snapshots into `data/raw/`. Needs `HF_TOKEN`. |
| `02_analyze.py` | Parse the logs and write `messages.parquet` plus EDA. |
| `03_build_windows.py` | Build the exact 12-line windows. |
| `04_export.py` | Write the 30k `label_queue`. Gold starts empty. |
| `05_select_pilot_2k.py` | Freeze the 2,000 pilot ids. |
| `06_silver_label_pilot.py` | Qwen-32B v1 silver on those 2,000. This pass is not mixed into the train file. |
| `07_audit_sample.py` | Freeze 200 windows for the human audit. |
| `07_label_ui.py` | Local page for gold labels. |
| `08_apply_reviewed_gold.py` | Copy the 200 gold labels onto the queue. |
| `09` / `10` / `11` | Teacher against gold. v2 73.5%, v2.1 77.5%, v2.2 85.5%. |
| `12`–`14` | Harvest v2.2 silver. |
| `15_export_sft_and_eda.py` | Write the 1:1 SFT file and the paper EDA. |
| `16_freeze_friends_and_splits.py` | Write the 1:3 train split and the 400-window friend holdout. |
| `17_launch_lora_train.py` | Start the 7B LoRA run on a Modal H100. |

Download and windows, after the Hub license is accepted:

```powershell
uv run python scripts/01_download.py
uv run python scripts/02_analyze.py
uv run python scripts/03_build_windows.py
uv run python scripts/04_export.py
```

Teacher harvest and the LoRA launch need Modal credentials.

## Gate score

Scored on the 200 gold test windows. Silent is class 0. Speak is class 1. The selected checkpoint is step 1200.

| Method | Macro-F1 | Speak-F1 | Silent-F1 |
| --- | ---: | ---: | ---: |
| LoRA 7B | 0.878 | 0.861 | 0.895 |
| B3, question and no helper already in the window | 0.775 | 0.716 | 0.833 |
| B2, question | 0.682 | 0.652 | 0.712 |
| B1, always SILENT | 0.355 | 0.000 | 0.710 |

Confusion counts for the LoRA: TN 102, FP 8, FN 16, TP 74. The write-up is `reports/training_eval.md`.

## License

| Label | Terms |
| --- | --- |
| Code | MIT. See `LICENSE`. |
| IRC logs | CC-BY-4.0, Kummerfeld et al. 2019. Accept the dataset license on Hugging Face before downloading. |
| Model weights | The base model follows the Qwen license. The LoRA adapter is local and is not shipped in this clone. |

## Authors

PES University capstone. SOMA is the SPEAK/SILENT helper for multi-party Ubuntu IRC, and the group-chat room that posts a reply only after that gate says SPEAK.
