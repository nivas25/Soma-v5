"""Quality gates: no secrets in tracked files, window invariants, reconcilation helpers."""

from __future__ import annotations

import regex as re
from pathlib import Path

from soma_data.config import ROOT

TOKEN_RE = re.compile(r"hf_[A-Za-z0-9]{20,}")

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "hf_cache",
    ".cache",
    "data",
}
SKIP_FILE_NAMES = {".env"}
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
    ".json",
    ".jsonl",
    ".csv",
    ".example",
    ".gitignore",
    ".lock",
}


def assert_no_hf_token_in_tree(root: Path = ROOT) -> list[str]:
    """Return paths (relative) that appear to contain a Hugging Face token."""
    hits: list[str] = []
    for path in root.rglob("*"):
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.name in SKIP_FILE_NAMES:
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {".gitignore", "Makefile", "uv.lock"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if TOKEN_RE.search(text):
            hits.append(str(path.relative_to(root)))
    if hits:
        raise AssertionError(
            "Hugging Face token-like string found in tracked-style files: " + ", ".join(hits)
        )
    return hits
