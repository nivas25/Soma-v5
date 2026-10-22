---
language:
- en
license: mit
tags:
- text-classification
- lora
- ubuntu-irc
datasets:
- jkkummerfeld/irc_disentangle
---
# SOMA

SOMA is a small Ubuntu group chat. People post in a room. After the room goes quiet, a trained gate decides **SPEAK** or **SILENT**. On SPEAK, a second model drafts one short reply and the room posts it as **SOMA**, quoting the line it answers.

The gate is a Qwen2.5-7B LoRA. The reply model is the same 7B base with no adapter. Both run on Modal. The page is served from this machine at http://127.0.0.1:8787.

Default is SILENT. The nick `soma` is reserved for the bot.

## Run the chat

You need Python 3.11+ with [uv](https://docs.astral.sh/uv/), Node.js with npm, a Modal account, and the local gate adapter (see below). Commands are for PowerShell. Use `python -m` for Modal and pytest. `uv run modal` and `uv run pytest` fail in this environment with “Failed to canonicalize script path”.

### 1. Install Python packages

```powershell
uv sync --extra dev
```

Copy `.env.example` to `.env` only when you download the Hugging Face IRC dumps or run the old data scripts. Leave every secret empty in git. The chat server does not read `GEMINI_API_KEY`.

### 2. Build the page

The server serves `web/dist`. Without that folder the API still runs and the browser has no page.

```powershell
Set-Location web
npm install
npm run build
Set-Location ..
```

### 3. Deploy the two Modal apps

Deploy from the repo root. The gate image refuses to build if `models/soma-gate-lora-best/best_adapter/adapter_model.safetensors` is missing. Those weights are gitignored. Modal also needs a secret named `huggingface` so the container can download `Qwen/Qwen2.5-7B-Instruct`.

```powershell
uv run python -m modal deploy src/soma_data/modal_gate.py
uv run python -m modal deploy src/soma_data/modal_reply.py
```

| App | Class | What it is | GPU idle window |
| --- | --- | --- | --- |
| `soma-gate` | `Gate` | 7B + the trained LoRA. Returns SPEAK or SILENT. | 2 minutes |
| `soma-reply` | `Reply` | 7B base, no LoRA, greedy (`do_sample=False`). Returns one JSON object. | 5 minutes |

The first call after a cold start loads the model on an H100 and can take about a minute. A code change needs a new deploy. Stop a warm container after a deploy, or the old container keeps serving.

### 4. Start the room

```powershell
uv run python -m soma_data.chat_app
```

Open http://127.0.0.1:8787. Join room `ubuntu`. Use any nick except `soma` (letters, digits, `_`, `-`, up to 20 characters). Open the same URL in another browser to add a second person.

The room is in memory. Stopping this process clears every line.

`SOMA_IDLE_S` overrides the quiet time. The default is 4 seconds.

### Stop

```powershell
uv run python -m modal app stop soma-gate -y
uv run python -m modal app stop soma-reply -y
```

Then stop the `python -m soma_data.chat_app` process. Stopping Modal does not clear the room. Stopping the Python process does.

## What the room does

1. A human line is stored at once. Typing expires 1.5 seconds after the last typing post.
2. Idle is true only when nobody is typing, there is a human line, and the last activity is at least 4 seconds old.
3. The room sends the last 12 lines to `soma-gate` once for that line. A second idle on the same line does not call again.
4. SILENT posts nothing.
5. SPEAK asks `soma-reply` for one line. The draft is checked before it is posted.
6. A passing draft is appended as nick `soma`, quoting the human line the gate ran on. If someone else spoke while the model was running, the draft is dropped.
7. The thread shows the name SOMA, the text, and the quoted line. It does not show SPEAK, SILENT, or a reason.

The **Gate** button in the header is off by default. Turn it on to see, for each human line that reached the gate, the line id, nick, token, raw model text, the payload that was sent, and the stages that actually ran. A failed call shows the exception type and that nothing was posted.

### Reply checks

| Check | Result |
| --- | --- |
| Empty draft or `NONE` | Nothing is posted. |
| Command already in the window | Nothing is posted. |
| Draft contradicts the window | Nothing is posted. |
| Denied command, or the question asks to erase or format a disk | A line is posted. It starts with `This will erase data. Be careful.` A denied command is not the whole reply. |
| A normal question such as free disk space | The cleaned draft is posted unchanged. |

## Tests

```powershell
uv run python -m pytest
```

Most tests stub the models. `tests/test_reply_live.py` calls the deployed Modal apps, so those need both apps up.

## Layout

| Path | Role |
| --- | --- |
| `src/soma_data/chat_app.py` | Room, idle, gate call, reply, HTTP on port 8787 |
| `src/soma_data/modal_gate.py` | Deploy the trained gate |
| `src/soma_data/modal_reply.py` | Deploy the reply model |
| `src/soma_data/speak.py` | Draft prompt and the checks above |
| `src/soma_data/speak_validate.py` | Command overlap and contradiction |
| `src/soma_data/validate_reply.py` | Denied-command patterns |
| `src/soma_data/modal_lora.py` | Training app only. It does not serve the room. |
| `web/src` | React page. Build into `web/dist`. |
| `scripts/01`–`17` | Data download, labels, and LoRA training |
| `models/soma-gate-lora-best/` | Local adapter. Not in git. |

These files are in the repo and are not the live decision:

- `src/soma_data/room_gate.py` is an older keyword check. The room does not use it as the gate.
- `scripts/20_speak_demo.py` calls Gemini through `compose_reply`. The room does not call it.
- `scripts/18_run_four_objectives.py` and `scripts/19_llm_replies.py` are offline eval scripts.

## Data

Upstream logs: [`jkkummerfeld/irc_disentangle`](https://huggingface.co/datasets/jkkummerfeld/irc_disentangle) — Kummerfeld et al., ACL 2019 ([P19-1374](https://aclanthology.org/P19-1374/) / [arXiv:1810.11118](https://arxiv.org/abs/1810.11118)). **CC-BY-4.0.** One Hub row is one IRC line (`id`, `raw`, `ascii`, `tokenized`, `date`, `connections`).

We add SPEAK/SILENT labels. Hub has none. This is not the Lowe/McGill Ubuntu Dialogue Corpus.

You must accept the Hugging Face dataset license to download raw dumps. This clone does not ship those parquets.

| In the clone | Not in the clone |
| --- | --- |
| Code (`src/`, `scripts/`, `tests/`, `web/src`) | `data/raw/*.parquet` |
| 200 gold windows (`data/silver/audit_200.csv`, `sft_test.jsonl`) | Teacher silver jsonl |
| Friend holdout CSVs (gold empty) | LoRA adapter / `.safetensors` |
| Reports and figures | `sft_train_1to3.jsonl` |

The train file stays gitignored. Rebuild with harvest, then `scripts/15_export_sft_and_eda.py` and `scripts/16_freeze_friends_and_splits.py`.

## Data scripts

| Script | Role |
| --- | --- |
| `01_download.py` | Hub snapshots → `data/raw/` |
| `02_analyze.py` | parse + EDA → `messages.parquet` |
| `03_build_windows.py` | exact 12-line windows |
| `04_export.py` | 30k `label_queue` (gold empty) |
| `05_select_pilot_2k.py` | freeze 2k ids |
| `06_silver_label_pilot.py` | Qwen-32B v1 silver on 2k (not mixed into train) |
| `07_audit_sample.py` | freeze 200 for human audit |
| `07_label_ui.py` | local gold UI |
| `08_apply_reviewed_gold.py` | copy 200 gold onto the queue |
| `09` / `10` / `11` | teacher vs gold: v2 73.5% → v2.1 77.5% → v2.2 85.5% |
| `12`–`14` | v2.2 silver harvest |
| `15_export_sft_and_eda.py` | 1:1 SFT plus EDA |
| `16_freeze_friends_and_splits.py` | 1:3 train, 400 friend holdout |
| `17_launch_lora_train.py` | 7B LoRA on Modal H100 |

```powershell
uv run python scripts/01_download.py
uv run python scripts/02_analyze.py
uv run python scripts/03_build_windows.py
uv run python scripts/04_export.py
```

No stemming, lemmatizing, stopwords, or lowercasing. See `reports/data_preprocessing.md`.

## Gate score on the 200 gold test

Best checkpoint is step 1200. Silent=0, Speak=1.

| Method | Macro-F1 | Speak-F1 | Silent-F1 |
| --- | ---: | ---: | ---: |
| LoRA 7B | 0.878 | 0.861 | 0.895 |
| B3 question and not helper | 0.775 | 0.716 | 0.833 |
| B2 question | 0.682 | 0.652 | 0.712 |
| B1 always SILENT | 0.355 | 0.000 | 0.710 |

Confusion: TN 102, FP 8, FN 16, TP 74. Details are in `reports/training_eval.md`.

## License

- Code: MIT (`LICENSE`)
- Upstream IRC data: CC-BY-4.0 (Kummerfeld et al. 2019). Accept the Hub license before `01_download.py`.

## Authors

PES University capstone. SOMA is a SPEAK/SILENT helper for multi-party Ubuntu IRC, plus the group-chat room that uses that gate.
