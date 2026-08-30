"""Download jkkummerfeld/irc_disentangle snapshots to data/raw/*.parquet.

Fails loud on Hub auth errors. Never prints the full HF token.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from datasets import get_dataset_config_names, get_dataset_split_names, load_dataset
from huggingface_hub import login
from loguru import logger

from soma_data.config import (
    CHANNEL_TWO_DATE_SENTINEL,
    DOWNLOAD_MANIFEST,
    HF_DATASET,
    RAW_DIR,
    SAMPLE_PREVIEW_JSON,
    ensure_dirs,
    hf_token,
    masked_token,
)

# Card-reported *annotated* counts (Kummerfeld ACL 2019 / Hub README).
CARD_ANNOTATED = {
    ("ubuntu", "train"): 67463,
    ("ubuntu", "validation"): 2500,  # Hub uses validation; paper says Dev
    ("ubuntu", "dev"): 2500,
    ("ubuntu", "test"): 5000,
    ("channel_two", "all_"): 2600,
}


def login_hub(token: str) -> None:
    logger.info("huggingface_hub.login (token={})", masked_token(token))
    try:
        login(token=token, add_to_git_credential=False)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Hugging Face login failed ({type(exc).__name__}): {exc}. "
            "Refusing to fall back to a dummy corpus."
        ) from exc
    _cli_login(token)


def _cli_login(token: str) -> None:
    """Also run huggingface-cli login as required. Do not log argv (contains token)."""
    import subprocess
    import sys

    bindir = Path(sys.executable).parent
    candidates = [
        bindir / "hf.exe",
        bindir / "hf",
        bindir / "huggingface-cli.exe",
        bindir / "huggingface-cli",
    ]
    exe = next((p for p in candidates if p.exists()), None)
    if exe is None:
        logger.warning("hf/huggingface-cli binary not found next to python; Python login already succeeded")
        return
    # huggingface-cli is deprecated in hub>=1; `hf auth login` is the current CLI.
    if exe.name.lower().startswith("hf"):
        argv = [str(exe), "auth", "login", "--token", token, "--no-add-to-git-credential"]
    else:
        argv = [str(exe), "login", "--token", token]
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").replace(token, masked_token(token))
        raise RuntimeError(f"huggingface-cli login failed (exit {proc.returncode}): {err}")
    logger.info("huggingface-cli login ok")


def list_configs(token: str) -> list[str]:
    try:
        configs = list(get_dataset_config_names(HF_DATASET, token=token))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Failed to list configs for {HF_DATASET}: {type(exc).__name__}: {exc}"
        ) from exc
    logger.info("Hub configs for {}: {}", HF_DATASET, configs)
    return configs


def list_splits(config: str, token: str) -> list[str]:
    try:
        splits = list(get_dataset_split_names(HF_DATASET, config_name=config, token=token))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Failed to list splits for {HF_DATASET}/{config}: {type(exc).__name__}: {exc}"
        ) from exc
    logger.info("splits for config={}: {}", config, splits)
    return splits


def raw_parquet_path(config: str, split: str) -> Path:
    safe_split = split.replace("/", "_")
    return RAW_DIR / f"{config}__{safe_split}.parquet"


def _to_pandas(ds: Any) -> pd.DataFrame:
    df = ds.to_pandas()
    if "connections" in df.columns:
        df["connections"] = df["connections"].map(_norm_connections)
    if "id" in df.columns:
        df["id"] = df["id"].astype("int64")
    if "date" not in df.columns:
        df["date"] = CHANNEL_TWO_DATE_SENTINEL
    else:
        df["date"] = df["date"].fillna(CHANNEL_TWO_DATE_SENTINEL).astype(str)
    df["row_idx"] = range(len(df))
    return df


def _norm_connections(value: Any) -> list[int]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    try:
        return [int(x) for x in list(value)]
    except TypeError:
        return []


def load_split(config: str, split: str, token: str):
    try:
        return load_dataset(HF_DATASET, name=config, split=split, token=token)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"load_dataset({HF_DATASET!r}, name={config!r}, split={split!r}) "
            f"failed: {type(exc).__name__}: {exc}"
        ) from exc


def sample_rows(config: str, split: str, n: int, token: str) -> list[dict[str, Any]]:
    """Load n rows (Hub slice syntax). Used before the full download."""
    slice_split = f"{split}[:{n}]"
    ds = load_split(config, slice_split, token)
    rows = []
    for i, row in enumerate(ds):
        rec = {k: _jsonable(v) for k, v in dict(row).items()}
        rec["_index"] = i
        rows.append(rec)
    SAMPLE_PREVIEW_JSON.write_text(
        json.dumps(
            {
                "dataset": HF_DATASET,
                "config": config,
                "split": split,
                "n": len(rows),
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    logger.info("Wrote {} sample rows to {}", len(rows), SAMPLE_PREVIEW_JSON)
    return rows


def download_split(config: str, split: str, token: str, *, force: bool = False) -> dict[str, Any]:
    dest = raw_parquet_path(config, split)
    if dest.exists() and not force:
        df = pd.read_parquet(dest)
        logger.info("reuse cached {} ({} rows)", dest.name, len(df))
        return _split_meta(config, split, dest, df)

    logger.info("downloading {} / {} …", config, split)
    ds = load_split(config, split, token)
    df = _to_pandas(ds)
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(dest, index=False)
    logger.info("saved {} rows → {}", len(df), dest)
    return _split_meta(config, split, dest, df)


def _split_meta(config: str, split: str, dest: Path, df: pd.DataFrame) -> dict[str, Any]:
    n_annotated = int((df["connections"].map(len) > 0).sum()) if "connections" in df.columns else 0
    card = CARD_ANNOTATED.get((config, split))
    return {
        "config": config,
        "split": split,
        "path": dest.name,
        "n_rows": int(len(df)),
        "n_annotated_nonempty_connections": n_annotated,
        "card_annotated": card,
        "columns": list(df.columns),
        "has_date_field": "date" in df.columns
        and not (
            config == "channel_two"
            and set(df["date"].astype(str).unique()) <= {CHANNEL_TWO_DATE_SENTINEL}
        ),
        "n_unique_dates": int(df["date"].nunique()) if "date" in df.columns else 0,
        "id_min": int(df["id"].min()) if len(df) else None,
        "id_max": int(df["id"].max()) if len(df) else None,
    }


def download_all(token: str, *, force: bool = False) -> dict[str, Any]:
    ensure_dirs()
    login_hub(token)
    configs = list_configs(token)
    if "ubuntu" not in configs:
        raise RuntimeError(
            f"Required config 'ubuntu' not in Hub configs {configs}. "
            "Pick the Ubuntu IRC builder config — do not silently substitute."
        )

    kept = [c for c in configs if c in {"ubuntu", "channel_two"}]
    skipped = [c for c in configs if c not in kept]
    if skipped:
        logger.warning("Skipping unexpected configs: {}", skipped)

    split_metas: list[dict[str, Any]] = []
    for config in kept:
        for split in list_splits(config, token):
            split_metas.append(download_split(config, split, token, force=force))

    manifest = {
        "dataset": HF_DATASET,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "configs_on_hub": configs,
        "configs_kept": kept,
        "configs_skipped": skipped,
        "note": (
            "Hub row counts INCLUDE unannotated context (typically the first "
            "~1000 messages of each Ubuntu slice). Card numbers are ANNOTATED "
            "messages only (train 67463 / dev 2500 / test 5000 / channel_two 2600)."
        ),
        "splits": split_metas,
    }
    DOWNLOAD_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Wrote manifest {}", DOWNLOAD_MANIFEST)
    return manifest


def load_raw_table(config: str, split: str) -> pd.DataFrame:
    path = raw_parquet_path(config, split)
    if not path.exists():
        raise FileNotFoundError(f"Missing raw snapshot {path}. Run scripts/01_download.py")
    df = pd.read_parquet(path)
    df["config"] = config
    df["split"] = split
    return df


def iter_raw_snapshots() -> list[tuple[str, str, Path]]:
    found = []
    for path in sorted(RAW_DIR.glob("*.parquet")):
        stem = path.stem
        if "__" not in stem:
            continue
        config, split = stem.split("__", 1)
        found.append((config, split, path))
    return found


def _jsonable(value: Any) -> Any:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
