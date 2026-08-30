"""Professional train/eval figures from disk. No retraining."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

ROOT = Path(__file__).resolve().parents[3]
JSONL = ROOT / "reports" / "lora_run" / "reports" / "train_metrics.jsonl"
METRICS = ROOT / "reports" / "lora_run" / "reports" / "test_metrics.json"
OUT = Path(__file__).resolve().parent

INK = "#111827"
GRID = "#E5E7EB"
LORA = "#059669"
GRAY = "#6B7280"
BLUE = "#2563EB"
AMBER = "#D97706"
MUTED = "#6B7280"


def _font() -> str:
    from matplotlib import font_manager

    names = {f.name for f in font_manager.fontManager.ttflist}
    for cand in ("Lexend Deca", "Lexend", "DejaVu Sans"):
        if cand in names:
            return cand
    return "DejaVu Sans"


def _style() -> None:
    fam = _font()
    plt.rcParams.update(
        {
            "font.family": fam,
            "font.size": 11,
            "axes.titlesize": 13,
            "axes.titleweight": "normal",
            "axes.labelsize": 10,
            "axes.edgecolor": INK,
            "axes.labelcolor": INK,
            "axes.titlecolor": INK,
            "xtick.color": INK,
            "ytick.color": INK,
            "text.color": INK,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "axes.axisbelow": True,
        }
    )


def load_hist() -> list[dict]:
    rows = []
    for ln in JSONL.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            rows.append(json.loads(ln))
    rows.sort(key=lambda r: int(r["step"]))
    return rows


def _save(fig: plt.Figure, name: str) -> None:
    path = OUT / name
    fig.tight_layout()
    fig.savefig(path, dpi=600, bbox_inches="tight", pad_inches=0.12, facecolor="white")
    plt.close(fig)
    print("wrote", path)


def fig_a(hist: list[dict]) -> None:
    steps = [h["step"] for h in hist]
    loss = [h["train_loss"] for h in hist]
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    ax.plot(steps, loss, color=LORA, lw=2.4, marker="o", ms=6, zorder=3)
    ax.set_xlabel("Step")
    ax.set_ylabel("Train loss")
    ax.set_title("Train loss falls quickly on a one-token label")
    ax.text(
        0.03,
        0.08,
        "1-token label, loss falls fast",
        transform=ax.transAxes,
        fontsize=8.5,
        color=MUTED,
    )
    ax.set_ylim(0, 0.042)
    ax.set_xlim(0, 1320)
    _save(fig, "train_loss_vs_step.png")


def fig_b(hist: list[dict]) -> None:
    steps = [h["step"] for h in hist]
    f1 = [h["macro_f1"] for h in hist]
    best_step = max(hist, key=lambda h: (h["macro_f1"], -h["step"]))["step"]
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    ax.plot(steps, f1, color=LORA, lw=2.4, marker="o", ms=6, zorder=3)
    ax.axvline(best_step, color=INK, ls="--", lw=1.1, alpha=0.7)
    ax.text(
        best_step - 12,
        0.882,
        "best",
        color=INK,
        fontsize=9,
        ha="right",
    )
    ax.set_xlabel("Step")
    ax.set_ylabel("Macro-F1")
    ax.set_title("Macro-F1 on 200 gold")
    ax.set_ylim(0.82, 0.89)
    ax.set_xlim(0, 1320)
    _save(fig, "eval_macro_f1_vs_step.png")


def fig_c(hist: list[dict]) -> None:
    steps = [h["step"] for h in hist]
    rate = [100 * h["speak_rate"] for h in hist]
    gold = 100 * hist[0]["gold_speak_rate"]
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    ax.plot(steps, rate, color=LORA, lw=2.4, marker="o", ms=6, zorder=3, label="Predicted SPEAK %")
    ax.axhline(gold, color=AMBER, ls="--", lw=1.2, label=f"Gold SPEAK rate ({gold:.0f}%)")
    ax.set_xlabel("Step")
    ax.set_ylabel("SPEAK rate (%)")
    ax.set_title("Predicted SPEAK rate versus gold 45%")
    ax.set_ylim(30, 50)
    ax.set_xlim(0, 1320)
    ax.legend(frameon=False, loc="lower right")
    _save(fig, "eval_speak_rate_vs_step.png")


def fig_d(m: dict) -> None:
    # rows = gold SILENT, gold SPEAK; cols = pred SILENT, pred SPEAK
    cm = np.array([[m["tn"], m["fp"]], [m["fn"], m["tp"]]], dtype=float)
    cmap = LinearSegmentedColormap.from_list("lora", ["#ECFDF5", LORA])
    fig, ax = plt.subplots(figsize=(4.8, 4.2))
    im = ax.imshow(cm, cmap=cmap, vmin=0, vmax=110)
    ax.set_xticks([0, 1], ["Pred. SILENT", "Pred. SPEAK"])
    ax.set_yticks([0, 1], ["Gold SILENT", "Gold SPEAK"])
    ax.set_title("Confusion on gold (n = 200)")
    ax.grid(False)
    ax.spines["top"].set_visible(True)
    ax.spines["right"].set_visible(True)
    for i in range(2):
        for j in range(2):
            ax.text(j, i, f"{int(cm[i, j])}", ha="center", va="center", fontsize=16, color=INK)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04).set_label("Count")
    ax.text(0.5, -0.18, "Silent = 0, Speak = 1. Best adapter, step 1200.", transform=ax.transAxes, ha="center", fontsize=8, color=MUTED)
    _save(fig, "confusion_heatmap.png")


def fig_e(tm: dict) -> None:
    names = ["LoRA", "B1", "B2", "B3"]
    keys = ["lora", "B1_always_silent", "B2_question", "B3_no_helper_and_question"]
    macro = [tm["lora"]["macro_f1"] if k == "lora" else tm["baselines"][k]["macro_f1"] for k in keys]
    speak = [tm["lora"]["speak_f1"] if k == "lora" else tm["baselines"][k]["speak_f1"] for k in keys]
    x = np.arange(len(names))
    w = 0.36
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    ax.bar(x - w / 2, macro, w, color=LORA, label="Macro-F1")
    ax.bar(x + w / 2, speak, w, color=BLUE, label="Speak-F1")
    ax.set_xticks(x, names)
    ax.set_ylabel("F1")
    ax.set_title("LoRA versus untrained rule baselines")
    ax.set_ylim(0, 1.05)
    ax.legend(frameon=False)
    for i, (a, b) in enumerate(zip(macro, speak)):
        ax.text(i - w / 2, a + 0.02, f"{a:.2f}", ha="center", va="bottom", fontsize=8, color=INK)
        ax.text(i + w / 2, b + 0.02, f"{b:.2f}", ha="center", va="bottom", fontsize=8, color=INK)
    _save(fig, "method_bars.png")


def fig_f(m: dict) -> None:
    fig, ax = plt.subplots(figsize=(4.4, 2.6))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title("SPEAK precision and recall")
    # two cards
    boxes = [
        (0.06, 0.18, 0.42, 0.62, f"{m['speak_p']:.3f}", "Precision"),
        (0.52, 0.18, 0.42, 0.62, f"{m['speak_r']:.3f}", "Recall"),
    ]
    for x, y, w, h, val, lab in boxes:
        rect = plt.Rectangle((x, y), w, h, fill=True, facecolor="#ECFDF5", edgecolor=GRID, lw=1.2, transform=ax.transAxes)
        ax.add_patch(rect)
        ax.text(x + w / 2, y + 0.38, val, transform=ax.transAxes, ha="center", va="center", fontsize=20, color=LORA)
        ax.text(x + w / 2, y + 0.12, lab, transform=ax.transAxes, ha="center", va="center", fontsize=10, color=MUTED)
    ax.text(0.5, 0.05, "Best adapter on 200 gold. Speak-F1 = 0.860.", transform=ax.transAxes, ha="center", fontsize=8, color=MUTED)
    _save(fig, "speak_precision_recall.png")


def main() -> None:
    _style()
    OUT.mkdir(parents=True, exist_ok=True)
    hist = load_hist()
    print("jsonl n", len(hist), "keys", sorted(hist[0].keys()))
    tm = json.loads(METRICS.read_text(encoding="utf-8"))
    fig_a(hist)
    fig_b(hist)
    fig_c(hist)
    fig_d(tm["lora"])
    fig_e(tm)
    fig_f(tm["lora"])


if __name__ == "__main__":
    main()
