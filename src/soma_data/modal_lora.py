"""SOMA gate LoRA: Qwen2.5-7B-Instruct on Modal H100. Whole Trainer.train() in one function.

  uv run python scripts/17_launch_lora_train.py
"""

from __future__ import annotations

import inspect
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import modal

APP_NAME = "soma-gate-lora-7b"
BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
BASE_REV = "a09a35458c702b33eeacc393d103063234e8bc28"
RUN_DIR = "/lora"
DATA_TRAIN = f"{RUN_DIR}/data/sft_train_1to3.jsonl"
DATA_TEST = f"{RUN_DIR}/data/sft_test.jsonl"
CKPT_DIR = f"{RUN_DIR}/checkpoints"
BEST_DIR = f"{RUN_DIR}/checkpoints/best_adapter"
REPORTS_DIR = f"{RUN_DIR}/reports"

# Pinned 2026-08-29 PyPI. See reports/train_plan.md.
TRANSFORMERS_V = "5.16.1"
TRL_V = "1.12.0"
PEFT_V = "0.20.0"
ACCELERATE_V = "1.14.0"
DATASETS_V = "5.0.1"
SKLEARN_V = "1.9.0"

hf_cache = modal.Volume.from_name("soma-hf-cache", create_if_missing=True)
train_vol = modal.Volume.from_name("soma-lora-train", create_if_missing=True)

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.4.1-runtime-ubuntu22.04",
        add_python="3.12",
    )
    .entrypoint([])
    .uv_pip_install("torch", index_url="https://download.pytorch.org/whl/cu124")
    .uv_pip_install(
        f"transformers=={TRANSFORMERS_V}",
        f"trl=={TRL_V}",
        f"peft=={PEFT_V}",
        f"accelerate=={ACCELERATE_V}",
        f"datasets=={DATASETS_V}",
        f"scikit-learn=={SKLEARN_V}",
        "matplotlib",
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
    .add_local_python_source("soma_data")
)

app = modal.App(APP_NAME)

Q_RE = re.compile(r"\bquestion=(yes|no)\b", re.I)
H_RE = re.compile(r"\bhelper_in_window=(yes|no)\b", re.I)


def _load_jsonl(path: str | Path) -> list[dict]:
    rows: list[dict] = []
    with Path(path).open(encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            rec = json.loads(ln)
            if isinstance(rec, dict):
                rows.append(rec)
    return rows


def _flag(pat: re.Pattern, text: str) -> bool:
    m = pat.search(str(text or ""))
    return bool(m) and m.group(1).lower() == "yes"


def _parse_pred(text: str) -> str:
    tok = str(text or "").strip().split()
    if not tok:
        return "INVALID"
    w = tok[0].upper().strip(".,:;\"'")
    if w.startswith("SPEAK"):
        return "SPEAK"
    if w.startswith("SILENT"):
        return "SILENT"
    return "INVALID"


def _metrics(golds: list[str], preds: list[str]) -> dict[str, Any]:
    from sklearn.metrics import f1_score, precision_score, recall_score

    y_true = [1 if g == "SPEAK" else 0 for g in golds]
    y_pred = [1 if p == "SPEAK" else 0 for p in preds]
    tn = fp = fn = tp = 0
    for t, p in zip(y_true, y_pred):
        if t == 0 and p == 0:
            tn += 1
        elif t == 0 and p == 1:
            fp += 1
        elif t == 1 and p == 0:
            fn += 1
        else:
            tp += 1
    def _prf(pos: int) -> tuple[float, float, float]:
        p = precision_score(y_true, y_pred, pos_label=pos, zero_division=0)
        r = recall_score(y_true, y_pred, pos_label=pos, zero_division=0)
        f = f1_score(y_true, y_pred, pos_label=pos, zero_division=0)
        return float(p), float(r), float(f)

    sp, sr, sf = _prf(1)
    np_, nr, nf = _prf(0)
    macro = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
    n = len(golds)
    return {
        "n": n,
        "macro_f1": round(macro, 4),
        "speak_p": round(sp, 4),
        "speak_r": round(sr, 4),
        "speak_f1": round(sf, 4),
        "silent_p": round(np_, 4),
        "silent_r": round(nr, 4),
        "silent_f1": round(nf, 4),
        "speak_rate": round(sum(y_pred) / n, 4) if n else 0.0,
        "gold_speak_rate": round(sum(y_true) / n, 4) if n else 0.0,
        "invalid_n": sum(1 for p in preds if p == "INVALID"),
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "tp": tp,
        "mapping": "Silent=0 Speak=1 ; TN=gold SILENT pred SILENT, FP=gold SILENT pred SPEAK, FN=gold SPEAK pred SILENT, TP=gold SPEAK pred SPEAK",
    }


def _to_prompt_completion(rows: list[dict], tokenizer) -> list[dict]:
    out = []
    for r in rows:
        messages = [
            {"role": "system", "content": r["instruction"]},
            {"role": "user", "content": r["input"]},
        ]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        out.append(
            {
                "prompt": prompt,
                "completion": str(r["output"]).strip().upper(),
                "window_id": r["window_id"],
            }
        )
    return out


def _generate_labels(model, tokenizer, rows: list[dict], *, max_new_tokens: int = 8, batch_size: int = 16) -> list[str]:
    import torch

    device = next(model.parameters()).device
    model.eval()
    preds: list[str] = []
    pad_id = tokenizer.pad_token_id or tokenizer.eos_token_id
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        texts = []
        for r in chunk:
            messages = [
                {"role": "system", "content": r["instruction"]},
                {"role": "user", "content": r["input"]},
            ]
            texts.append(tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True))
        enc = tokenizer(texts, return_tensors="pt", padding=True, truncation=True, max_length=1024)
        enc = {k: v.to(device) for k, v in enc.items()}
        in_len = enc["input_ids"].shape[1]
        with torch.inference_mode():
            gen = model.generate(
                **enc,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=pad_id,
            )
        for j in range(gen.shape[0]):
            new = gen[j, in_len:]
            text = tokenizer.decode(new, skip_special_tokens=True)
            p = _parse_pred(text)
            preds.append("SILENT" if p == "INVALID" else p)
    return preds


def _baselines(rows: list[dict]) -> dict[str, list[str]]:
    gold = [str(r["output"]).strip().upper() for r in rows]
    b1 = ["SILENT"] * len(rows)
    b2, b3 = [], []
    for r in rows:
        q = _flag(Q_RE, r["input"])
        h = _flag(H_RE, r["input"])
        b2.append("SPEAK" if q else "SILENT")
        b3.append("SPEAK" if (q and not h) else "SILENT")
    return {"gold": gold, "B1_always_silent": b1, "B2_question": b2, "B3_no_helper_and_question": b3}


def _plot(history: list[dict], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    steps = [h["step"] for h in history]
    fig, ax1 = plt.subplots(figsize=(7.2, 3.8))
    ax1.set_xlabel("step")
    if any("train_loss" in h for h in history):
        ax1.plot(steps, [h.get("train_loss") for h in history], color="#1f4e79", label="train_loss")
        ax1.set_ylabel("train_loss")
    ax2 = ax1.twinx()
    ax2.plot(steps, [h.get("macro_f1") for h in history], color="#c4892b", label="eval_macro_f1")
    ax2.set_ylabel("eval_macro_f1")
    ax2.set_ylim(0, 1)
    lines = ax1.get_legend_handles_labels()[0] + ax2.get_legend_handles_labels()[0]
    labels = ax1.get_legend_handles_labels()[1] + ax2.get_legend_handles_labels()[1]
    ax1.legend(lines, labels, frameon=False, loc="lower right")
    ax1.set_title("SOMA gate LoRA 7B")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _verify(train_rows: list[dict], test_rows: list[dict], tokenizer) -> None:
    def counts(rows: list[dict]) -> tuple[int, int, int]:
        sp = sum(1 for r in rows if r.get("output") == "SPEAK")
        si = sum(1 for r in rows if r.get("output") == "SILENT")
        return len(rows), sp, si

    n_tr, sp_tr, si_tr = counts(train_rows)
    n_te, sp_te, si_te = counts(test_rows)
    tr_ids = {r["window_id"] for r in train_rows}
    te_ids = {r["window_id"] for r in test_rows}
    overlap = tr_ids & te_ids
    bad = [r["window_id"] for r in train_rows + test_rows if r.get("output") not in {"SPEAK", "SILENT"}]
    print(f"VERIFY n_train={n_tr} speak={sp_tr} silent={si_tr}")
    print(f"VERIFY n_test={n_te} speak={sp_te} silent={si_te}")
    print(f"VERIFY overlap_train_test={len(overlap)}")
    print("VERIFY raw_jsonl_example", json.dumps({k: train_rows[0][k] if k != "input" else train_rows[0][k][:500] for k in train_rows[0]}, ensure_ascii=False))
    messages = [
        {"role": "system", "content": train_rows[0]["instruction"]},
        {"role": "user", "content": train_rows[0]["input"]},
    ]
    templ = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    print("VERIFY chat_template_example\n", templ[-800:])
    if overlap:
        raise RuntimeError(f"FAIL train∩test overlap n={len(overlap)}")
    if bad:
        raise RuntimeError(f"FAIL output not SPEAK/SILENT n={len(bad)} e.g. {bad[0]}")
    if n_tr != 20400 or sp_tr != 5100 or si_tr != 15300:
        raise RuntimeError(f"FAIL unexpected 1to3 counts {n_tr} {sp_tr} {si_tr}")
    if n_te != 200:
        raise RuntimeError(f"FAIL test n={n_te}")


def _make_eval_callback(test_rows, tokenizer, reports_dir: Path, ckpt_dir: Path, best_dir: Path, vol):
    from transformers import TrainerCallback

    state_box = {"best_f1": -1.0, "history": [], "train_loss": None}

    class GateEvalCallback(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            if logs and "loss" in logs:
                state_box["train_loss"] = float(logs["loss"])

        def on_evaluate(self, args, state, control, metrics=None, **kwargs):
            model = kwargs.get("model")
            step = int(state.global_step)
            if step <= 0 or model is None:
                return
            eval_loss = (metrics or {}).get("eval_loss")
            preds = _generate_labels(model, tokenizer, test_rows)
            golds = [r["output"] for r in test_rows]
            m = _metrics(golds, preds)
            rec = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "step": step,
                "epoch": float(getattr(state, "epoch", 0) or 0),
                "eval_loss": None if eval_loss is None else round(float(eval_loss), 6),
                "train_loss": state_box["train_loss"],
                **m,
            }
            state_box["history"].append(rec)
            reports_dir.mkdir(parents=True, exist_ok=True)
            with (reports_dir / "train_metrics.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
            print(
                f"EVAL step={step} eval_loss={rec['eval_loss']} macro_f1={m['macro_f1']} "
                f"speak_f1={m['speak_f1']} silent_f1={m['silent_f1']} speak_rate={m['speak_rate']} "
                f"CM tn={m['tn']} fp={m['fp']} fn={m['fn']} tp={m['tp']}",
                flush=True,
            )
            step_dir = ckpt_dir / f"step-{step:04d}"
            step_dir.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(step_dir)
            tokenizer.save_pretrained(step_dir)
            if m["macro_f1"] > state_box["best_f1"]:
                state_box["best_f1"] = m["macro_f1"]
                if best_dir.exists():
                    shutil.rmtree(best_dir)
                shutil.copytree(step_dir, best_dir)
                print(f"BEST_ADAPTER step={step} macro_f1={state_box['best_f1']}", flush=True)
            _plot(state_box["history"], reports_dir / "train_curves.png")
            try:
                vol.commit()
            except Exception as exc:  # noqa: BLE001
                print(f"VOL_COMMIT {type(exc).__name__}: {exc}", flush=True)

    return GateEvalCallback(), state_box


@app.function(
    image=image,
    gpu="H100",
    timeout=4 * 60 * 60,
    startup_timeout=50 * 60,
    memory=65536,
    cpu=8.0,
    volumes={
        "/root/.cache/huggingface": hf_cache,
        RUN_DIR: train_vol,
    },
    secrets=[modal.Secret.from_name("huggingface")],
    scaledown_window=10 * 60,
)
def train_run() -> dict[str, Any]:
    import torch
    from datasets import Dataset
    from peft import LoraConfig, PeftModel, TaskType
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import SFTConfig, SFTTrainer

    os.environ.setdefault("HF_TOKEN", os.environ.get("HUGGING_FACE_HUB_TOKEN") or os.environ.get("HF_TOKEN") or "")
    Path(CKPT_DIR).mkdir(parents=True, exist_ok=True)
    Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)

    if not Path(DATA_TRAIN).exists() or not Path(DATA_TEST).exists():
        raise FileNotFoundError(f"missing {DATA_TRAIN} or {DATA_TEST} on soma-lora-train volume")

    train_rows = _load_jsonl(DATA_TRAIN)
    test_rows = _load_jsonl(DATA_TEST)

    print(f"LOAD tokenizer {BASE_MODEL} rev={BASE_REV}", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, revision=BASE_REV, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"

    _verify(train_rows, test_rows, tokenizer)

    print(f"LOAD model bf16 H100 {BASE_MODEL}", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        revision=BASE_REV,
        dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
        attn_implementation="sdpa",
    )
    model.config.use_cache = False
    model.enable_input_require_grads()
    try:
        hf_cache.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"HF_CACHE_COMMIT {type(exc).__name__}: {exc}", flush=True)

    train_pc = _to_prompt_completion(train_rows, tokenizer)
    test_pc = _to_prompt_completion(test_rows, tokenizer)
    train_ds = Dataset.from_list([{"prompt": r["prompt"], "completion": r["completion"]} for r in train_pc])
    eval_ds = Dataset.from_list([{"prompt": r["prompt"], "completion": r["completion"]} for r in test_pc])

    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )

    batch, accum = 8, 4
    gate_cb, gate_state = _make_eval_callback(
        test_rows,
        tokenizer,
        Path(REPORTS_DIR),
        Path(CKPT_DIR),
        Path(BEST_DIR),
        train_vol,
    )

    def _make_trainer(bs: int, ga: int, optim: str = "adamw_torch_fused") -> SFTTrainer:
        # transformers v5: warmup_ratio removed; warmup_steps may be a float ratio in [0,1).
        wanted = {
            "output_dir": str(Path(CKPT_DIR) / "hf_out"),
            "max_length": 1024,
            "packing": False,
            "completion_only_loss": True,
            "learning_rate": 2e-4,
            "lr_scheduler_type": "cosine",
            "warmup_steps": 0.03,
            "num_train_epochs": 2,
            "per_device_train_batch_size": bs,
            "per_device_eval_batch_size": bs,
            "gradient_accumulation_steps": ga,
            "max_grad_norm": 1.0,
            "optim": optim,
            "bf16": True,
            "seed": 42,
            "eval_strategy": "steps",
            "eval_steps": 100,
            "save_strategy": "steps",
            "save_steps": 100,
            "save_total_limit": 8,
            "logging_steps": 10,
            "report_to": "none",
            "gradient_checkpointing": True,
            "remove_unused_columns": False,
            "run_name": "soma_gate_lora_1to3",
        }
        params = inspect.signature(SFTConfig.__init__).parameters
        accepts_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
        if accepts_var_kw:
            kw = wanted
        else:
            kw = {k: v for k, v in wanted.items() if k in params}
            dropped = sorted(set(wanted) - set(kw))
            if dropped:
                print(f"SFTConfig dropped unsupported kwargs: {dropped}", flush=True)
        print(f"SFTConfig kwargs={sorted(kw)}", flush=True)
        args = SFTConfig(**kw)
        trainer_kw = dict(
            model=model,
            args=args,
            train_dataset=train_ds,
            eval_dataset=eval_ds,
            peft_config=peft_config,
            callbacks=[gate_cb],
        )
        tparams = inspect.signature(SFTTrainer.__init__).parameters
        if "processing_class" in tparams:
            trainer_kw["processing_class"] = tokenizer
        else:
            trainer_kw["tokenizer"] = tokenizer
        return SFTTrainer(**trainer_kw)

    print(f"TRAIN start batch={batch} accum={accum} effective=32", flush=True)
    try:
        trainer = _make_trainer(batch, accum)
        trainer.train()
    except (ValueError, TypeError) as exc:
        if "adamw_torch_fused" not in str(exc):
            raise
        print("fused AdamW unavailable → adamw_torch", flush=True)
        trainer = _make_trainer(batch, accum, optim="adamw_torch")
        trainer.train()
    except torch.cuda.OutOfMemoryError:
        print("OOM batch=8 → retry batch=4 accum=8 (still effective 32). QLoRA not used yet.", flush=True)
        torch.cuda.empty_cache()
        trainer = _make_trainer(4, 8)
        trainer.train()

    print("TRAIN done; final eval + best adapter", flush=True)
    best_src = Path(BEST_DIR)
    if not best_src.exists():
        trainer.save_model(BEST_DIR)
        tokenizer.save_pretrained(BEST_DIR)

    device = next(trainer.model.parameters()).device
    eval_model = trainer.model
    if Path(BEST_DIR).exists():
        base = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            revision=BASE_REV,
            dtype=torch.bfloat16,
            device_map="auto",
            trust_remote_code=True,
            attn_implementation="sdpa",
        )
        eval_model = PeftModel.from_pretrained(base, BEST_DIR)
        eval_model.eval()

    preds = _generate_labels(eval_model, tokenizer, test_rows)
    golds = [r["output"] for r in test_rows]
    lora_m = _metrics(golds, preds)
    bl = _baselines(test_rows)
    table = [("LoRA_best", lora_m)]
    for name, pred in bl.items():
        if name == "gold":
            continue
        table.append((name, _metrics(bl["gold"], pred)))

    pred_path = Path(REPORTS_DIR) / "test_200_predictions.csv"
    with pred_path.open("w", encoding="utf-8") as fh:
        fh.write("window_id,gold,pred,question,helper_in_window\n")
        for r, p in zip(test_rows, preds):
            q = "yes" if _flag(Q_RE, r["input"]) else "no"
            h = "yes" if _flag(H_RE, r["input"]) else "no"
            fh.write(f"{r['window_id']},{r['output']},{p},{q},{h}\n")

    lines = [
        "# Test confusion — Nivas 200",
        "",
        "Mapping: Silent=0, Speak=1.",
        "TN = gold SILENT pred SILENT. FP = gold SILENT pred SPEAK.",
        "FN = gold SPEAK pred SILENT. TP = gold SPEAK pred SPEAK.",
        "",
        "| method | n | macro-F1 | speak-F1 | silent-F1 | speak rate | TN | FP | FN | TP |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, m in table:
        lines.append(
            f"| {name} | {m['n']} | {m['macro_f1']:.4f} | {m['speak_f1']:.4f} | {m['silent_f1']:.4f} | {m['speak_rate']:.4f} | {m['tn']} | {m['fp']} | {m['fn']} | {m['tp']} |"
        )
    b3 = next(m for n, m in table if n.startswith("B3"))
    win = lora_m["macro_f1"] >= b3["macro_f1"]
    lines += [
        "",
        f"LoRA vs B3: macro-F1 {lora_m['macro_f1']:.4f} vs {b3['macro_f1']:.4f}. "
        + ("LoRA ≥ B3." if win else "Do not claim a win: LoRA < B3."),
        "",
        f"best_adapter_macro_f1={gate_state['best_f1']}",
        f"base={BASE_MODEL} rev={BASE_REV} train=sft_train_1to3.jsonl",
        "",
    ]
    (Path(REPORTS_DIR) / "test_confusion.md").write_text("\n".join(lines), encoding="utf-8")
    (Path(REPORTS_DIR) / "test_metrics.json").write_text(
        json.dumps(
            {
                "lora": lora_m,
                "baselines": {n: m for n, m in table if n != "LoRA_best"},
                "best_f1_during_train": gate_state["best_f1"],
                "win_vs_B3": win,
                "base_model": BASE_MODEL,
                "revision": BASE_REV,
                "train_file": "sft_train_1to3.jsonl",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\n".join(lines), flush=True)
    train_vol.commit()
    try:
        hf_cache.commit()
    except Exception:  # noqa: BLE001
        pass
    return {
        "lora_macro_f1": lora_m["macro_f1"],
        "b3_macro_f1": b3["macro_f1"],
        "win_vs_B3": win,
        "best_f1": gate_state["best_f1"],
        "n_train": len(train_rows),
        "n_test": len(test_rows),
    }


@app.local_entrypoint()
def launch() -> None:
    call = train_run.spawn()
    cid = getattr(call, "object_id", None) or str(call)
    print(f"DETACHED_LORA_SPAWNED call_id={cid}", flush=True)
    print("YES close the lid. Trainer.train() is inside one Modal H100 function.", flush=True)
