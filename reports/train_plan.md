# SOMA gate LoRA train plan

Looked up on 2026-08-29 from PyPI + Hub. No guessed versions.

## Choice: TRL SFTTrainer + PEFT, not Unsloth

Unsloth is optional and version-locked (Modal’s public example pins `unsloth==2025.7.8` with `transformers==4.54.0` / `trl==0.19.1`). That stack is a year behind current TRL 1.x and patches `transformers` in ways that break custom eval callbacks.

H100 80GB holds Qwen2.5-7B bf16 LoRA without 4-bit. Custom eval every 100 steps (generate SPEAK/SILENT on Nivas 200, Macro-F1) is a Hugging Face `TrainerCallback`. **TRL + PEFT is the reliable Modal path.** QLoRA / bitsandbytes only if bf16 OOM (not expected).

## Pinned versions (PyPI latest checked 2026-08-29)

| package | version | source |
| --- | --- | --- |
| transformers | 5.16.1 | pypi.org/pypi/transformers |
| trl | 1.12.0 | pypi.org/pypi/trl (`transformers>=4.56.2`, `accelerate>=1.4.0`, `datasets>=4.7.0`) |
| peft | 0.20.0 | pypi.org/pypi/peft |
| accelerate | 1.14.0 | pypi.org/pypi/accelerate |
| datasets | 5.0.1 | pypi.org/pypi/datasets |
| scikit-learn | 1.9.0 | pypi.org/pypi/scikit-learn |
| torch | CUDA 12.4 wheel | same index as teacher image |
| bitsandbytes | not installed unless OOM | QLoRA fallback only |
| unsloth | not used | — |

## Model

- Hub id: `Qwen/Qwen2.5-7B-Instruct` (not gated)
- Revision SHA: `a09a35458c702b33eeacc393d103063234e8bc28` (Hub `lastModified` 2025-01-12)
- Official chat template: `tokenizer.apply_chat_template(...)` (Qwen docs; ChatML `<|im_start|>role\n... <|im_end|>`)
- Generation prompt: `<|im_start|>assistant\n`
- pad_token: `<|endoftext|>`, eos: `<|im_end|>`

System message is the dataset `instruction` (SPEAK/SILENT gate), **not** the default “You are Qwen…” helper prompt.

## Data

| split | file | n | SPEAK | SILENT | source |
| --- | --- | ---: | ---: | ---: | --- |
| train (primary) | `data/processed/sft_train_1to3.jsonl` | 20400 | 5100 | 15300 | qwen32_v2.2 |
| test | `data/processed/sft_test.jsonl` | 200 | 90 | 110 | nivas_gold |

Columns used (do not invent): `window_id`, `instruction`, `input`, `output`, `prompt_version`, `source`, `split`.

Flags for baselines B2/B3 are parsed from the existing `input` string (`question=yes/no`, `helper_in_window=yes/no`).

Train ∩ test must be 0. `output` must be exactly `SPEAK` or `SILENT`.

## Loss

TRL prompt-completion dataset (`prompt`, `completion`) with `completion_only_loss=True` (default for that format in TRL 1.12). Packing **False**.

`prompt` = official chat template of `[system=instruction, user=input]` with `add_generation_prompt=True`.
`completion` = `SPEAK` or `SILENT`.

## Frozen hyperparams

- LoRA r=16, alpha=32, dropout=0.05
- targets: q_proj k_proj v_proj o_proj gate_proj up_proj down_proj
- lr 2e-4, cosine, warmup_steps=0.03 (transformers v5 removed `warmup_ratio`; float `warmup_steps` in [0,1) is the ratio)
- 2 epochs, seed 42
- per_device_batch 8 (drop to 4 on OOM), grad_accum so effective batch = 32
- max_length 1024
- optim `adamw_torch_fused` (fallback `adamw_torch`)
- max_grad_norm 1.0
- bf16 full base on H100 (QLoRA only if VRAM fails)
- attn: PyTorch SDPA (no extra flash-attn wheel)

## Modal

- One function: verify → `Trainer.train()` → generate-eval 200 → write artifacts. **Not** per-step `.remote()`.
- GPU H100 80GB, timeout 4h, `modal run --detach` / `.spawn`
- Volumes: `soma-hf-cache` (weights), `soma-lora-train` (`/run` data + checkpoints + reports)
- Launch must print app id so the laptop can die.

## Eval / selection

Every 100 steps on Nivas 200:

- eval_loss (SFT on prompt-completion test)
- Macro-F1, Speak-P/R/F1, Silent-P/R/F1
- confusion TN FP FN TP with **Silent=0, Speak=1**
- predicted Speak rate

Best checkpoint = highest Macro-F1 on 200, copied to `checkpoints/best_adapter/`.

After train, same-script CPU baselines (no extra GPU):

- B1 always SILENT
- B2 SPEAK iff `question=yes`
- B3 SPEAK iff (`helper_in_window=no` and `question=yes`)

Do not claim a LoRA win if Macro-F1 < B3.

## Artifacts (volume `/run`, then download)

- `reports/train_metrics.jsonl`
- `reports/train_curves.png`
- `checkpoints/step-XXXX/`
- `checkpoints/best_adapter/`
- `reports/test_200_predictions.csv`
- `reports/test_confusion.md`
- `reports/test_metrics.json`
