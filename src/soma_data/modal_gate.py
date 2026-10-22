"""Serve the trained SOMA gate. Not soma-reply. Not the training app.

Loads Qwen2.5-7B-Instruct plus models/soma-gate-lora-best/best_adapter
(r=16, alpha=32). generate() returns the raw decoded text. gate_label()
applies modal_lora._parse_pred and maps anything else to SILENT.

  uv run python -m modal deploy src/soma_data/modal_gate.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import modal

APP_NAME = "soma-gate"
CLASS_NAME = "Gate"
BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
BASE_REV = "a09a35458c702b33eeacc393d103063234e8bc28"
ADAPTER_REMOTE = "/adapter"
# Inside Modal this file is /root/modal_gate.py. Do not walk parents there.
_REMOTE = os.environ.get("MODAL_IS_REMOTE") == "1"

hf_cache = modal.Volume.from_name("soma-hf-cache", create_if_missing=True)

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.4.1-runtime-ubuntu22.04",
        add_python="3.12",
    )
    .entrypoint([])
    .uv_pip_install(
        "torch",
        index_url="https://download.pytorch.org/whl/cu124",
    )
    .uv_pip_install(
        "transformers==5.16.1",
        "peft==0.20.0",
        "accelerate==1.14.0",
        "safetensors",
        "sentencepiece",
        "huggingface_hub",
    )
    .env(
        {
            "HF_HOME": "/root/.cache/huggingface",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
)
if not _REMOTE:
    _adapter_local = Path(__file__).resolve().parents[2] / "models" / "soma-gate-lora-best" / "best_adapter"
    if not (_adapter_local / "adapter_model.safetensors").is_file():
        raise FileNotFoundError(f"missing adapter weights at {_adapter_local}")
    image = image.add_local_dir(_adapter_local, remote_path=ADAPTER_REMOTE)

app = modal.App(APP_NAME)


@app.cls(
    image=image,
    gpu="H100",
    timeout=10 * 60,
    startup_timeout=30 * 60,
    memory=65536,
    cpu=8.0,
    volumes={"/root/.cache/huggingface": hf_cache},
    secrets=[modal.Secret.from_name("huggingface")],
    scaledown_window=2 * 60,
)
class Gate:
    @modal.enter()
    def load(self) -> None:
        import os

        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        token = (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or "").strip()
        if token:
            os.environ["HF_TOKEN"] = token
            os.environ["HUGGING_FACE_HUB_TOKEN"] = token
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is not available")
        config_path = Path(ADAPTER_REMOTE) / "adapter_config.json"
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        if int(cfg.get("r") or 0) != 16 or int(cfg.get("lora_alpha") or 0) != 32:
            raise RuntimeError(f"adapter r/alpha is {cfg.get('r')}/{cfg.get('lora_alpha')}, expected 16/32")
        if cfg.get("base_model_name_or_path") != BASE_MODEL:
            raise RuntimeError(f"adapter base is {cfg.get('base_model_name_or_path')}")
        self.tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, revision=BASE_REV)
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.tokenizer.padding_side = "left"
        base = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            revision=BASE_REV,
            torch_dtype=torch.bfloat16,
            device_map="auto",
        )
        self.model = PeftModel.from_pretrained(base, ADAPTER_REMOTE)
        self.model.eval()

    @modal.method()
    def generate(self, instruction: str, input: str) -> str:
        """Same prompt pair as _generate_labels. Raw decode, not a label."""
        import torch

        messages = [
            {"role": "system", "content": instruction},
            {"role": "user", "content": input},
        ]
        text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        encoded = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=1024)
        encoded = {key: value.to(self.model.device) for key, value in encoded.items()}
        prompt_len = encoded["input_ids"].shape[-1]
        pad_id = self.tokenizer.pad_token_id or self.tokenizer.eos_token_id
        with torch.inference_mode():
            output = self.model.generate(
                **encoded,
                max_new_tokens=8,
                do_sample=False,
                pad_token_id=pad_id,
            )
        new_tokens = output[0, prompt_len:]
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True)


def gate_raw(instruction: str, user_input: str) -> str:
    """Call the deployed class. Raises if soma-gate is not deployed."""
    gate_cls = modal.Cls.from_name(APP_NAME, CLASS_NAME)
    return str(gate_cls().generate.remote(instruction, user_input) or "")


def gate_label(instruction: str, user_input: str) -> str:
    """Raw generate(), then _parse_pred. Invalid text becomes SILENT."""
    from soma_data.modal_lora import _parse_pred

    parsed = _parse_pred(gate_raw(instruction, user_input))
    if parsed not in {"SPEAK", "SILENT"}:
        return "SILENT"
    return parsed
