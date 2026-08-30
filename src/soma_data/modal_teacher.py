"""Modal teacher: transformers generate, one window per .remote().

No vLLM, no FlashInfer, no nvcc, no 72B-AWQ.
Weights load once per container (@modal.enter). Each label_one.remote()
is exactly one window.

  uv run python scripts/06_silver_label_pilot.py
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any

import modal

from soma_data.config import (
    HARVEST_SILENT_N,
    HARVEST_SPEAK_N,
    PROMPT_VERSION_V2_2,
    TEACHER_MAX_NEW_TOKENS,
    TEACHER_RETRIES,
    teacher_model_candidates,
)
from soma_data.teacher import ParseError, parse_teacher_output
from soma_data.teacher_prompt_v2_2 import build_chat_messages

APP_NAME = "soma-gate-teacher-pilot"
MINUTES = 60

hf_cache = modal.Volume.from_name("soma-hf-cache", create_if_missing=True)
harvest_vol = modal.Volume.from_name("soma-harvest", create_if_missing=True)

HARVEST_NEED_SPEAK = HARVEST_SPEAK_N + 100  # 5100: 5k train + 100 dev
HARVEST_NEED_SILENT = HARVEST_SILENT_N + 100
HARVEST_DIR = "/harvest"
HARVEST_LABELS = f"{HARVEST_DIR}/pilot_v2_2_labels.jsonl"
HARVEST_FAILS = f"{HARVEST_DIR}/pilot_v2_2_failures.jsonl"
HARVEST_PENDING = f"{HARVEST_DIR}/pending_items.jsonl"
HARVEST_STATUS = f"{HARVEST_DIR}/harvest_status.json"

# Runtime CUDA only (libs, not nvcc). debian_slim + torch also works on Modal
# GPUs; the runtime image makes device libs explicit without a devel/nvcc toolchain.
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
        "transformers>=4.45.0",
        "accelerate",
        "huggingface_hub",
        "pydantic",
        "safetensors",
        "sentencepiece",
    )
    .env(
        {
            "HF_HOME": "/root/.cache/huggingface",
            "TRANSFORMERS_CACHE": "/root/.cache/huggingface",
            "HF_HUB_DISABLE_TELEMETRY": "1",
        }
    )
    .add_local_python_source("soma_data")
)

app = modal.App(APP_NAME)

REPAIR_SUFFIX = (
    "\n\nReturn ONLY one JSON object, no markdown: "
    '{"label":"SPEAK"|"SILENT","reason":"<=15 words"}'
)


def _nvidia_name() -> str:
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            check=True,
            capture_output=True,
            text=True,
        )
        return (proc.stdout or "").strip().splitlines()[0].strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _vram_gb() -> float:
    import torch

    if not torch.cuda.is_available():
        return 0.0
    return float(torch.cuda.get_device_properties(0).total_memory) / (1024**3)


def _ensure_hf_token() -> None:
    tok = (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or "").strip()
    if not tok:
        raise RuntimeError("HF_TOKEN missing — Modal secret 'huggingface' is not mounted")
    os.environ["HF_TOKEN"] = tok
    os.environ["HUGGING_FACE_HUB_TOKEN"] = tok


def _ok_rec(item: dict[str, Any], decision, health: dict[str, Any], raw: str, latency: int, attempt: int) -> dict[str, Any]:
    return {
        "window_id": item["window_id"],
        "label_silver": decision.label,
        "reason": decision.reason,
        "model_id": health["model_id"],
        "backend": "modal",
        "prompt_version": PROMPT_VERSION_V2_2,
        "latency_ms": latency,
        "retries": attempt,
        "raw_ok": True,
        "chat_block": item.get("chat_block") or "",
        "last_speaker": item.get("last_speaker") or "",
        "last_is_question": item.get("last_is_question") or "",
        "addressed_to": item.get("addressed_to") or "",
        "guideline_hint": item.get("guideline_hint") or "",
        "split": item.get("split") or "",
        "date": item.get("date") or "",
        "t_id": item.get("t_id") or "",
        "raw_text": raw,
        "gpu": health.get("gpu"),
        "model_revision": health.get("model_revision"),
        "quantization": health.get("quantization"),
    }


def _fail_rec(item: dict[str, Any], error: str, health: dict[str, Any], raw: str, latency: int) -> dict[str, Any]:
    return {
        "window_id": item["window_id"],
        "error": error,
        "model_id": health.get("model_id"),
        "backend": "modal",
        "prompt_version": PROMPT_VERSION_V2_2,
        "latency_ms": latency,
        "retries": TEACHER_RETRIES,
        "raw_ok": False,
        "raw_text": raw,
        "split": item.get("split") or "",
        "date": item.get("date") or "",
        "t_id": item.get("t_id") or "",
        "gpu": health.get("gpu"),
        "model_revision": health.get("model_revision"),
        "quantization": health.get("quantization"),
    }


@app.cls(
    image=image,
    gpu=["H100", "H200", "A100-80GB"],
    timeout=10 * 60 * 60,  # harvest_until is a single in-container loop; lid-close safe
    startup_timeout=50 * MINUTES,
    memory=65536,
    cpu=8.0,
    volumes={
        "/root/.cache/huggingface": hf_cache,
        HARVEST_DIR: harvest_vol,
    },
    secrets=[modal.Secret.from_name("huggingface")],
    scaledown_window=10 * MINUTES,
)
class Teacher:
    @modal.enter()
    def load(self) -> None:
        import torch
        from huggingface_hub import HfApi
        from transformers import AutoModelForCausalLM, AutoTokenizer

        _ensure_hf_token()
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA not available — refusing CPU teacher")

        gpu = _nvidia_name()
        vram = _vram_gb()
        last: Exception | None = None
        self.model = None
        self.tokenizer = None
        self.model_id = ""
        self.health = {}

        for mid in teacher_model_candidates(vram):
            try:
                print(f"LOAD {mid} gpu={gpu} vram={vram:.1f}GiB dtype=bfloat16", flush=True)
                tokenizer = AutoTokenizer.from_pretrained(mid, trust_remote_code=True)
                if tokenizer.pad_token_id is None:
                    tokenizer.pad_token = tokenizer.eos_token
                model = AutoModelForCausalLM.from_pretrained(
                    mid,
                    torch_dtype=torch.bfloat16,
                    device_map="auto",
                    trust_remote_code=True,
                )
                model.eval()
                self.tokenizer = tokenizer
                self.model = model
                self.model_id = mid
                last = None
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
                print(f"LOAD_FAIL {mid} {type(exc).__name__}: {exc}", flush=True)
                try:
                    del model  # type: ignore[name-defined]
                except Exception:  # noqa: BLE001
                    pass
                try:
                    import gc

                    gc.collect()
                    torch.cuda.empty_cache()
                except Exception:  # noqa: BLE001
                    pass

        if self.model is None or self.tokenizer is None:
            raise RuntimeError(f"could not load teacher: {last}")

        try:
            rev = HfApi().model_info(self.model_id).sha or "unknown"
        except Exception:  # noqa: BLE001
            rev = "unknown"

        self.health = {
            "model_id": self.model_id,
            "model_revision": rev,
            "gpu": gpu,
            "vram_gb": round(vram, 1),
            "quantization": "bf16",
            "backend": "modal",
            "engine": "transformers.AutoModelForCausalLM.generate",
            "prompt_version": PROMPT_VERSION_V2_2,
            "max_new_tokens": int(TEACHER_MAX_NEW_TOKENS),
            "temperature": 0.0,
            "do_sample": False,
        }
        try:
            hf_cache.commit()
        except Exception as exc:  # noqa: BLE001
            print(f"HF_CACHE_COMMIT {type(exc).__name__}: {exc}", flush=True)
        print(f"TEACHER_READY {self.health}", flush=True)

    def _generate(self, user_payload: str) -> tuple[str, int]:
        import torch

        t0 = time.perf_counter()
        prompt = self.tokenizer.apply_chat_template(
            build_chat_messages(user_payload),
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self.tokenizer(prompt, return_tensors="pt")
        device = next(self.model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}
        input_len = int(inputs["input_ids"].shape[1])
        # Greedy == temperature 0. Do not pass temperature while do_sample=False
        # (recent transformers raises / warns).
        with torch.inference_mode():
            out = self.model.generate(
                **inputs,
                max_new_tokens=int(TEACHER_MAX_NEW_TOKENS),
                do_sample=False,
                pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
            )
        new_tokens = out[0, input_len:]
        text = self.tokenizer.decode(new_tokens, skip_special_tokens=True)
        return text, int((time.perf_counter() - t0) * 1000)

    def _infer_one(self, item: dict[str, Any]) -> dict[str, Any]:
        """One window, one generate (plus parse retries). Never concatenates windows."""
        health = dict(self.health)
        last_err = "unknown"
        raw = ""
        latency = 0
        payload = item["user_payload"]
        for attempt in range(TEACHER_RETRIES + 1):
            user = payload if attempt == 0 else payload + REPAIR_SUFFIX
            try:
                raw, latency = self._generate(user)
            except Exception as exc:  # noqa: BLE001
                last_err = f"generate {type(exc).__name__}: {exc}"
                print(f"GEN_FAIL {item.get('window_id')} {last_err}", flush=True)
                continue
            try:
                decision = parse_teacher_output(raw, allow_fence_strip=attempt > 0)
                rec = _ok_rec(item, decision, health, raw, latency, attempt)
                print(
                    f"OK {item['window_id']} {rec['label_silver']} {latency}ms attempt={attempt}",
                    flush=True,
                )
                return rec
            except ParseError as exc:
                last_err = str(exc)
                print(
                    f"PARSE_FAIL {item.get('window_id')} attempt={attempt} {last_err} raw={raw[:240]!r}",
                    flush=True,
                )
        rec = _fail_rec(item, last_err, health, raw, latency)
        print(f"FAIL {item.get('window_id')} {last_err}", flush=True)
        return rec

    @modal.method()
    def health_info(self) -> dict[str, Any]:
        return dict(self.health)

    @modal.method()
    def label_one(self, item: dict[str, Any]) -> dict[str, Any]:
        return self._infer_one(item)

    @modal.method()
    def harvest_until(self) -> dict[str, Any]:
        """Resume-only in-container loop. Skip done window_ids. Stop at 5100 SPEAK.

        Survives laptop lid / client disconnect. Writes to soma-harvest volume.
        """
        import json
        from datetime import datetime, timezone
        from pathlib import Path

        labels_path = Path(HARVEST_LABELS)
        fail_path = Path(HARVEST_FAILS)
        pending_path = Path(HARVEST_PENDING)
        status_path = Path(HARVEST_STATUS)

        def _load(path: Path) -> list[dict[str, Any]]:
            if not path.exists():
                return []
            out: list[dict[str, Any]] = []
            for ln in path.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rec = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
            return out

        def _counts(recs: list[dict[str, Any]]) -> tuple[int, int, set[str]]:
            speak = silent = 0
            seen: set[str] = set()
            for r in recs:
                wid = r.get("window_id") or ""
                if not wid or wid in seen:
                    continue
                seen.add(wid)
                lab = str(r.get("label_silver") or "").strip().upper()
                if r.get("raw_ok") and lab == "SPEAK":
                    speak += 1
                elif r.get("raw_ok") and lab == "SILENT":
                    silent += 1
            return speak, silent, seen

        def _append(path: Path, rec: dict[str, Any]) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())

        def _status(**kw: Any) -> None:
            payload = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "prompt_version": PROMPT_VERSION_V2_2,
                **kw,
            }
            status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            try:
                harvest_vol.commit()
            except Exception as exc:  # noqa: BLE001
                print(f"HARVEST_COMMIT {type(exc).__name__}: {exc}", flush=True)

        recs = _load(labels_path)
        speak, silent, done = _counts(recs)
        fail_recs = _load(fail_path)
        done |= {r.get("window_id") for r in fail_recs if r.get("window_id")}
        print(
            f"HARVEST_RESUME speak={speak}/{HARVEST_NEED_SPEAK} "
            f"silent={silent}/{HARVEST_NEED_SILENT} done={len(done)}",
            flush=True,
        )
        if not labels_path.exists() or speak < 1000:
            raise RuntimeError(
                f"REFUSE restart-from-zero: labels_exist={labels_path.exists()} "
                f"speak={speak} (need existing snapshot on /harvest)"
            )
        _status(phase="start", speak=speak, silent=silent, done=len(done), last_wid="")
        if speak >= HARVEST_NEED_SPEAK and silent >= HARVEST_NEED_SILENT:
            _status(phase="already_done", speak=speak, silent=silent, done=len(done), last_wid="")
            return {"status": "already_done", "speak": speak, "silent": silent, "done": len(done)}
        if not pending_path.exists():
            raise RuntimeError("missing /harvest/pending_items.jsonl")

        n_new = 0
        last_wid = ""
        with pending_path.open(encoding="utf-8") as fh:
            for line in fh:
                if speak >= HARVEST_NEED_SPEAK and silent >= HARVEST_NEED_SILENT:
                    print("HARVEST_QUOTAS_FILLED", flush=True)
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                wid = item.get("window_id") or ""
                if not wid or wid in done:
                    continue
                rec = self._infer_one(item)
                rec["prompt_version"] = PROMPT_VERSION_V2_2
                rec["label_silver_v2"] = rec.get("label_silver") or ""
                last_wid = wid
                done.add(wid)
                n_new += 1
                if rec.get("raw_ok"):
                    _append(labels_path, rec)
                    lab = str(rec.get("label_silver") or "").strip().upper()
                    if lab == "SPEAK":
                        speak += 1
                    elif lab == "SILENT":
                        silent += 1
                else:
                    _append(fail_path, rec)
                if n_new == 1 or n_new % 10 == 0:
                    print(
                        f"HARVEST {n_new} {wid} speak={speak}/{HARVEST_NEED_SPEAK} "
                        f"silent={silent}/{HARVEST_NEED_SILENT}",
                        flush=True,
                    )
                    _status(
                        phase="running",
                        speak=speak,
                        silent=silent,
                        done=len(done),
                        n_new=n_new,
                        last_wid=last_wid,
                    )

        phase = "done" if speak >= HARVEST_NEED_SPEAK and silent >= HARVEST_NEED_SILENT else "incomplete"
        _status(phase=phase, speak=speak, silent=silent, done=len(done), n_new=n_new, last_wid=last_wid)
        print(f"HARVEST_END phase={phase} speak={speak} silent={silent} n_new={n_new}", flush=True)
        return {
            "status": phase,
            "speak": speak,
            "silent": silent,
            "done": len(done),
            "n_new": n_new,
            "last_wid": last_wid,
        }


@app.local_entrypoint()
def main() -> None:
    print("Use: uv run python scripts/06_silver_label_pilot.py")
    print("Teacher.health_info / Teacher.label_one are the remote methods.")
    print("Detached harvest: uv run modal run --detach src/soma_data/modal_teacher.py::harvest_cloud")


@app.local_entrypoint()
def harvest_cloud() -> None:
    """Spawn harvest_until on GPU. Pair with `modal run --detach` so lid-close is safe."""
    T = Teacher.with_options(timeout=10 * 60 * 60, max_containers=1)
    call = T().harvest_until.spawn()
    cid = getattr(call, "object_id", None) or getattr(call, "call_id", None) or str(call)
    print(f"DETACHED_HARVEST_SPAWNED call_id={cid}", flush=True)
    print("YES you can close the lid. Loop is inside one Modal GPU function; resume-only.", flush=True)
