"""Reply model on Modal. Not the gate. Not Gemini.

Qwen2.5-7B-Instruct base, same revision as the gate, no LoRA adapter.
complete() is greedy: do_sample=False, which is temperature 0.

  uv run python -m modal deploy src/soma_data/modal_reply.py
"""

from __future__ import annotations

import modal

APP_NAME = "soma-reply"
CLASS_NAME = "Reply"
MODEL_ID = "Qwen/Qwen2.5-7B-Instruct"
MODEL_REV = "a09a35458c702b33eeacc393d103063234e8bc28"

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
        "huggingface_hub",
        "sentencepiece",
    )
    .env(
        {
            "HF_HOME": "/root/.cache/huggingface",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
)

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
    scaledown_window=5 * 60,
)
class Reply:
    @modal.enter()
    def load(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is not available")
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=MODEL_REV)
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID,
            revision=MODEL_REV,
            torch_dtype=torch.bfloat16,
            device_map="auto",
        )
        self.model.eval()

    @modal.method()
    def complete(self, prompt: str) -> str:
        import torch

        messages = [
            {
                "role": "system",
                "content": (
                    "Output one JSON object and nothing else. No markdown. No code fence."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer(text, return_tensors="pt").to(self.model.device)
        with torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=96,
                do_sample=False,
                pad_token_id=self.tokenizer.pad_token_id,
            )
        new_tokens = output[0][inputs["input_ids"].shape[-1] :]
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


def modal_complete(prompt: str) -> str:
    """Call the deployed reply model. Raises if soma-reply is not deployed."""
    reply_cls = modal.Cls.from_name(APP_NAME, CLASS_NAME)
    return str(reply_cls().complete.remote(prompt) or "")
