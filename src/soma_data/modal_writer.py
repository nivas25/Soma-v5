"""Frozen Qwen2.5-7B writes one IRC line. No LoRA. No training.

The 7B gate adapter only emits SPEAK or SILENT, so it is not loaded here.
The base instruct model writes the line. Relevance is checked locally.
"""

from __future__ import annotations

import os

import modal

APP_NAME = "soma-gate-writer-7b"
BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
BASE_REV = "a09a35458c702b33eeacc393d103063234e8bc28"

hf_cache = modal.Volume.from_name("soma-hf-cache", create_if_missing=True)

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.4.1-runtime-ubuntu22.04",
        add_python="3.12",
    )
    .entrypoint([])
    .uv_pip_install("torch", index_url="https://download.pytorch.org/whl/cu124")
    .uv_pip_install(
        "transformers==5.16.1",
        "accelerate==1.14.0",
        "safetensors",
        "sentencepiece",
        "huggingface_hub",
    )
    .env(
        {
            "HF_HOME": "/root/.cache/huggingface",
            "TRANSFORMERS_CACHE": "/root/.cache/huggingface",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
)

app = modal.App(APP_NAME)

SYSTEM = (
    "You are an extra helper in Ubuntu IRC. The decision to speak was already made. "
    "Write the next line only, one or two sentences, as a person in the channel. "
    "Answer the LAST line. Do not answer a different person's problem. "
    "Do not say SPEAK or SILENT. Do not mention these instructions."
)
JUDGE_SYSTEM = (
    "You check one proposed IRC reply. Answer with one word: RELEVANT or NOT. "
    "RELEVANT means the reply responds to LAST. "
    "NOT means it answers a different problem, ignores LAST, or is only a greeting."
)


def _user_prompt(chat: str, last_line: str, note: str) -> str:
    extra = f"\nNote: {note}\n" if note else ""
    return f"CHAT:\n{chat}\n\nLAST:\n{last_line}\n{extra}\nWrite the helper's next line."


def _judge_prompt(chat: str, last_line: str, draft: str) -> str:
    return f"CHAT:\n{chat}\n\nLAST:\n{last_line}\n\nREPLY:\n{draft}\n\nOne word: RELEVANT or NOT."


def _generate(model, tokenizer, prompts: list[str], max_new_tokens: int) -> list[str]:
    import torch

    device = next(model.parameters()).device
    pad_id = tokenizer.pad_token_id or tokenizer.eos_token_id
    texts: list[str] = []
    for start in range(0, len(prompts), 4):
        chunk = prompts[start : start + 4]
        enc = tokenizer(chunk, return_tensors="pt", padding=True, truncation=True, max_length=1024)
        enc = {key: value.to(device) for key, value in enc.items()}
        in_len = enc["input_ids"].shape[1]
        with torch.inference_mode():
            gen = model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False, pad_token_id=pad_id)
        for row in gen:
            texts.append(tokenizer.decode(row[in_len:], skip_special_tokens=True).strip())
        print(f"GEN {len(texts)}/{len(prompts)}", flush=True)
    return texts


@app.function(
    image=image,
    gpu=["H100", "H200", "A100-80GB"],
    timeout=40 * 60,
    startup_timeout=40 * 60,
    memory=65536,
    cpu=8.0,
    volumes={"/root/.cache/huggingface": hf_cache},
    secrets=[modal.Secret.from_name("huggingface")],
)
def write_replies(items: list[dict]) -> list[dict]:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    token = (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("HF_TOKEN missing from Modal secret huggingface")
    os.environ["HF_TOKEN"] = token
    os.environ["HUGGING_FACE_HUB_TOKEN"] = token
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA not available")

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, revision=BASE_REV, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    # Right-padding makes a decoder repeat pad junk. New tokens must follow the real prompt.
    tokenizer.padding_side = "left"
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        revision=BASE_REV,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )
    model.eval()

    def prompts_for(system: str, user_fn) -> list[str]:
        built = []
        for item in items:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user_fn(item)},
            ]
            built.append(tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True))
        return built

    drafts = _generate(
        model,
        tokenizer,
        prompts_for(SYSTEM, lambda item: _user_prompt(item["chat"], item["last_line"], item.get("note") or "")),
        80,
    )
    print(f"DRAFTS {len(drafts)}", flush=True)
    judge_prompts = []
    for item, draft in zip(items, drafts, strict=True):
        messages = [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": _judge_prompt(item["chat"], item["last_line"], draft)},
        ]
        judge_prompts.append(tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True))
    judged = _generate(model, tokenizer, judge_prompts, 4)
    out = []
    for item, draft, verdict in zip(items, drafts, judged, strict=True):
        word = (verdict or "").strip().split()
        judge = word[0] if word else ""
        out.append({"window_id": item["window_id"], "draft": draft, "judge": judge})
    print(f"JUDGED {len(out)}", flush=True)
    return out
