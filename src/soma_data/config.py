"""Frozen pipeline constants. Changing these after export requires a schema note."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    # Modal image has no python-dotenv. HF_TOKEN comes from Secret.from_name("huggingface").
    pass

# ---------------------------------------------------------------------------
# Hugging Face
# ---------------------------------------------------------------------------
HF_DATASET = "jkkummerfeld/irc_disentangle"
HF_TOKEN_ENV = "HF_TOKEN"
# Lowe / McGill Ubuntu Dialogue Corpus is intentionally NOT a source.
FORBIDDEN_DATASETS = (
    "ubuntu_dialogs_corpus",
    "ubuntu_dialogue_corpus",
    "McGill-NLP/ubuntu-dialogue",
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"
REPORTS_DIR = ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"

MESSAGES_PARQUET = INTERIM_DIR / "messages.parquet"
WINDOWS_FULL_PARQUET = PROCESSED_DIR / "windows_full.parquet"
LABEL_QUEUE_PARQUET = PROCESSED_DIR / "label_queue.parquet"
LABEL_QUEUE_CSV = PROCESSED_DIR / "label_queue.csv"
SFT_TEMPLATE_JSONL = PROCESSED_DIR / "sft_template.jsonl"
STATS_JSON = REPORTS_DIR / "stats.json"
SCHEMA_MD = REPORTS_DIR / "schema.md"
EDA_MD = REPORTS_DIR / "eda.md"
SAMPLE_PREVIEW_JSON = REPORTS_DIR / "sample_preview.json"
DOWNLOAD_MANIFEST = RAW_DIR / "download_manifest.json"

SILVER_DIR = DATA_DIR / "silver"
PILOT_2K_IDS = SILVER_DIR / "pilot_2k_ids.txt"
PILOT_2K_MANIFEST = SILVER_DIR / "pilot_2k_manifest.json"
USED_WINDOW_IDS = SILVER_DIR / "used_window_ids.txt"
PILOT_2K_LABELS_PARQUET = SILVER_DIR / "pilot_2k_labels.parquet"
PILOT_2K_LABELS_JSONL = SILVER_DIR / "pilot_2k_labels.jsonl"
PILOT_2K_FAILURES_JSONL = SILVER_DIR / "pilot_2k_failures.jsonl"
PILOT_2K_RAW_DIR = SILVER_DIR / "pilot_2k_raw"
PILOT_2K_RESULTS_MD = REPORTS_DIR / "pilot_2k_results.md"
AUDIT_N = 200
AUDIT_200_IDS = SILVER_DIR / "audit_200_ids.txt"
AUDIT_200_CSV = SILVER_DIR / "audit_200.csv"
AUDIT_200_BAK = SILVER_DIR / "audit_200.bak.csv"
AUDIT_200_MANIFEST = SILVER_DIR / "audit_200_manifest.json"
AUDIT_200_MD = REPORTS_DIR / "audit_200.md"
LABEL_UI_HOST = "127.0.0.1"
LABEL_UI_PORT = 7860

PILOT_V2_AUDIT200_JSONL = SILVER_DIR / "pilot_v2_audit200.jsonl"
PILOT_V2_AUDIT200_FAIL_JSONL = SILVER_DIR / "pilot_v2_audit200_failures.jsonl"
PILOT_V2_GATE1_MD = REPORTS_DIR / "pilot_v2_gate1.md"
PILOT_V2_1_AUDIT200_JSONL = SILVER_DIR / "pilot_v2_1_audit200.jsonl"
PILOT_V2_1_AUDIT200_FAIL_JSONL = SILVER_DIR / "pilot_v2_1_audit200_failures.jsonl"
PILOT_V2_1_GATE1_MD = REPORTS_DIR / "pilot_v2_1_gate1.md"
PILOT_V2_2_AUDIT200_JSONL = SILVER_DIR / "pilot_v2_2_audit200.jsonl"
PILOT_V2_2_AUDIT200_FAIL_JSONL = SILVER_DIR / "pilot_v2_2_audit200_failures.jsonl"
PILOT_V2_2_GATE1_MD = REPORTS_DIR / "pilot_v2_2_gate1.md"
PILOT_V2_2_LABELS_JSONL = SILVER_DIR / "pilot_v2_2_labels.jsonl"
PILOT_V2_2_FAILURES_JSONL = SILVER_DIR / "pilot_v2_2_failures.jsonl"
PILOT_V2_2_HARVEST_MD = REPORTS_DIR / "pilot_v2_2_harvest.md"
PILOT_V2_LABELS_JSONL = SILVER_DIR / "pilot_v2_labels.jsonl"
PILOT_V2_FAILURES_JSONL = SILVER_DIR / "pilot_v2_failures.jsonl"
PILOT_V2_HARVEST_MD = REPORTS_DIR / "pilot_v2_harvest.md"
TRAIN_10K_IDS = SILVER_DIR / "train_10k_ids.txt"
SFT_TRAIN_JSONL = PROCESSED_DIR / "sft_train.jsonl"
SFT_TRAIN_1TO1_JSONL = PROCESSED_DIR / "sft_train_1to1.jsonl"
SFT_TRAIN_1TO3_JSONL = PROCESSED_DIR / "sft_train_1to3.jsonl"
SFT_TEST_JSONL = PROCESSED_DIR / "sft_test.jsonl"
SFT_DEV_JSONL = PROCESSED_DIR / "sft_dev.jsonl"
FRIENDS_DIR = DATA_DIR / "friends"
MANU_200_CSV = FRIENDS_DIR / "manu_200.csv"
PUNITH_200_CSV = FRIENDS_DIR / "punith_200.csv"
FRIEND_400_IDS = FRIENDS_DIR / "friend_400_ids.txt"
FRIEND_ASSIGNMENT_MD = FRIENDS_DIR / "ASSIGNMENT.md"
SPLIT_CARD_MD = REPORTS_DIR / "split_card.md"

# ---------------------------------------------------------------------------
# Ordering / windowing (frozen)
# ---------------------------------------------------------------------------
# New run when consecutive original_ids differ by more than GAP_THRESHOLD.
# Justification (also in reports/eda.md): Kummerfeld 2019 samples 173 time
# slices. Within a slice, log-line ids are contiguous (diff == 1). A jump of
# 6+ is a slice boundary or a second file of the same calendar date, not a
# dropped JOIN. Tiny gaps (1–5) stay in-run so we do not shatter a real burst.
GAP_THRESHOLD = 5

# Labelling UI is uniform: emit windows with EXACTLY W messages.
# MIN_HISTORY is recorded but not used to emit short leading windows.
WINDOW_SIZE = 12
MIN_HISTORY = 8
REQUIRE_EXACT_W = True
EXCLUDE_SYSTEM_FROM_WINDOWS = True
TIME_CAP_MINUTES = 3

# ---------------------------------------------------------------------------
# Sampling (label queue only; windows_full is unsampled)
# ---------------------------------------------------------------------------
SEED = 42
LABEL_QUEUE_CAP = 30_000
# After taking ALL question + ALL addressed windows, fill remaining quota
# with "other" so questions cannot dominate the sheet (~90%).
TARGET_OTHER_FRACTION = 0.35

# ---------------------------------------------------------------------------
# Domain-shift partition
# ---------------------------------------------------------------------------
# channel_two has no `date` field on the Hub card. Sentinel keeps the
# (config, date, id) sort key well-defined without inventing a calendar day.
CHANNEL_TWO_DATE_SENTINEL = "undated"

# channel_two Hub splits overlap (all_ is the union). Windows use all_ only.
CHANNEL_TWO_WINDOW_SPLIT = "all_"

# ---------------------------------------------------------------------------
# SFT template (output left empty — no model labels)
# ---------------------------------------------------------------------------
SFT_INSTRUCTION = (
    "You are a silent helper in a multi-party Ubuntu IRC support channel. "
    "Default is SILENT. Answer with one token: SPEAK or SILENT."
)

UBUNTU_IRC_LOGS_URL = "https://irclogs.ubuntu.com/"
PAPER_CITE = "Kummerfeld et al., ACL 2019 (P19-1374 / arXiv:1810.11118)"
LICENSE = "CC-BY-4.0"

# ---------------------------------------------------------------------------
# Silver-label PILOT (2,000 windows). Do not grow this without a new freeze.
# ---------------------------------------------------------------------------
PILOT_N = 2_000
PILOT_STRATA = {
    "question": 700,  # last_is_question True
    "addressed_not_question": 700,  # addressed_to set AND not a question
    "other": 600,  # neither
}
PROMPT_VERSION = "pilot_v1"
PROMPT_VERSION_V2 = "pilot_v2"
PROMPT_VERSION_V2_1 = "pilot_v2.1"
PROMPT_VERSION_V2_2 = "pilot_v2.2"
GATE1_AGREE_MIN = 0.80
GATE1_V2_2_AGREE_MIN = 0.78  # harvest bar for v2.2 retry
GATE1_ADDRESSED_AGREE_MIN = 0.75
GATE1_SPEAK_MIN = 0.35
GATE1_SPEAK_MAX = 0.55
HARVEST_SPEAK_N = 5_000
HARVEST_SILENT_N = 5_000
TEACHER_TEMPERATURE = 0.0
TEACHER_TOP_P = 1.0
TEACHER_MAX_NEW_TOKENS = 80
TEACHER_RETRIES = 2  # plus the first attempt = 3 tries
TEACHER_TIMEOUT_S = 180
# 32B-bf16 on 80GB (H100 / H200 / A100-80GB). 14B if VRAM is smaller.
# No 72B, no AWQ, no vLLM. 7B/8B are forbidden as teacher.
TEACHER_MODEL_PRIMARY = "Qwen/Qwen2.5-32B-Instruct"
TEACHER_MODEL_FALLBACK = "Qwen/Qwen2.5-14B-Instruct"
TEACHER_MODEL_DISPLAY_PRIMARY = "Qwen/Qwen2.5-32B-Instruct"
TEACHER_VRAM_32B_MIN_GB = 75.0


def teacher_model_candidates(vram_gb: float) -> list[str]:
    """32B on 80GB-class GPUs, 14B otherwise. 14B is always the OOM fallback."""
    out: list[str] = []
    if vram_gb >= TEACHER_VRAM_32B_MIN_GB:
        out.append(TEACHER_MODEL_PRIMARY)
    out.append(TEACHER_MODEL_FALLBACK)
    seen: set[str] = set()
    uniq: list[str] = []
    for mid in out:
        if mid not in seen:
            seen.add(mid)
            uniq.append(mid)
    return uniq


def hf_token() -> str:
    token = os.environ.get(HF_TOKEN_ENV, "").strip()
    if not token:
        raise RuntimeError(
            "HF_TOKEN is not set. Copy .env.example to .env and add a Hugging Face "
            "read token, or export HF_TOKEN in the environment."
        )
    if not token.startswith("hf_"):
        raise RuntimeError("HF_TOKEN does not look like a Hugging Face token.")
    return token


def masked_token(token: str | None = None) -> str:
    t = token if token is not None else os.environ.get(HF_TOKEN_ENV, "")
    if len(t) < 8:
        return "***"
    return f"{t[:3]}…{t[-4:]}"


def ensure_dirs() -> None:
    for p in (RAW_DIR, INTERIM_DIR, PROCESSED_DIR, REPORTS_DIR, FIGURES_DIR, SILVER_DIR, PILOT_2K_RAW_DIR, FRIENDS_DIR):
        p.mkdir(parents=True, exist_ok=True)
