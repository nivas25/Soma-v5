"""Teacher-LLM client helpers: JSON parse (strict) + Modal detection.

Does not invent labels. SPEAK/SILENT only.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any

from pydantic import BaseModel, field_validator

ALLOWED_LABELS = frozenset({"SPEAK", "SILENT"})
FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)
YES_NO = frozenset({"YES", "NO", "TRUE", "FALSE", "Y", "N", "SPEAK?", "SILENT?"})


class ParseError(ValueError):
    """Teacher output was not a usable SPEAK/SILENT JSON object."""


class TeacherDecision(BaseModel):
    label: str
    reason: str = ""

    @field_validator("label")
    @classmethod
    def _label_ok(cls, v: str) -> str:
        lab = str(v).strip().upper()
        if lab not in ALLOWED_LABELS:
            raise ValueError(f"label must be SPEAK or SILENT, got {v!r}")
        return lab

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        return " ".join(str(v).split())


def parse_teacher_output(text: str | None, *, allow_fence_strip: bool = False) -> TeacherDecision:
    """Parse one teacher response.

    Strict mode (default): raw JSON object only. Markdown fences, YES/NO, and
    extra prose are rejected so retries can ask for a clean object.
    """
    if text is None or not str(text).strip():
        raise ParseError("empty teacher output")
    raw = str(text).strip()

    if FENCE_RE.match(raw) and not allow_fence_strip:
        raise ParseError("markdown fences are not allowed")

    if allow_fence_strip:
        m = FENCE_RE.match(raw)
        if m:
            raw = m.group(1).strip()

    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        if not allow_fence_strip:
            raise ParseError(f"not a JSON object: {exc}") from exc
        brace = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not brace:
            raise ParseError(f"not a JSON object: {exc}") from exc
        try:
            obj = json.loads(brace.group(0))
        except json.JSONDecodeError as exc2:
            raise ParseError(f"not a JSON object: {exc2}") from exc2

    if not isinstance(obj, dict):
        raise ParseError(f"JSON root must be an object, got {type(obj).__name__}")

    label_raw = obj.get("label", obj.get("decision", obj.get("output")))
    if label_raw is None:
        raise ParseError("missing 'label'")
    lab = str(label_raw).strip().upper()
    if lab in YES_NO or lab not in ALLOWED_LABELS:
        raise ParseError(f"label must be SPEAK or SILENT, got {label_raw!r}")

    reason = obj.get("reason", "")
    if reason is None:
        reason = ""
    return TeacherDecision(label=lab, reason=str(reason))


def detect_modal() -> dict[str, Any]:
    """Return Modal usability. Never prints token secrets."""
    info: dict[str, Any] = {
        "usable": False,
        "modal_import": False,
        "cli": None,
        "profile": None,
        "workspace": None,
        "env_token_id": bool(os.environ.get("MODAL_TOKEN_ID")),
        "env_token_secret": bool(os.environ.get("MODAL_TOKEN_SECRET")),
        "toml_exists": (os.path.expanduser("~/.modal.toml") and __import__("pathlib").Path.home().joinpath(".modal.toml").exists()),
        "error": None,
    }
    try:
        import modal  # noqa: F401

        info["modal_import"] = True
        info["modal_version"] = getattr(modal, "__version__", None)
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"import modal failed: {type(exc).__name__}: {exc}"
        return info

    cli = shutil.which("modal")
    info["cli"] = cli
    try:
        proc = subprocess.run(
            ["uv", "run", "modal", "profile", "current"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if proc.returncode == 0:
            info["profile"] = (proc.stdout or "").strip() or None
        proc2 = subprocess.run(
            ["uv", "run", "modal", "token", "info"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if proc2.returncode == 0:
            # Parse non-secret fields only.
            for line in (proc2.stdout or "").splitlines():
                if line.startswith("Workspace:"):
                    info["workspace"] = line.split(":", 1)[1].strip().split()[0]
                if line.startswith("Name:"):
                    info["token_name"] = line.split(":", 1)[1].strip()
            info["usable"] = True
        else:
            info["error"] = (proc2.stderr or proc2.stdout or "modal token info failed").strip()[:400]
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def modal_setup_instructions() -> str:
    return """
Modal is NOT usable on this machine. Do not run the 2k teacher job until this is fixed.
Do NOT substitute a local 7B/8B teacher.

Setup (exact):

  1. Install the CLI in this project:
       uv add modal
       uv run modal --version

  2. Create / refresh a token (opens a browser):
       uv run modal token new

     or, if you already have keys:
       export MODAL_TOKEN_ID=ak-...
       export MODAL_TOKEN_SECRET=as-...
       uv run modal token set --token-id $MODAL_TOKEN_ID --token-secret $MODAL_TOKEN_SECRET

  3. Confirm:
       uv run modal profile current
       uv run modal token info
       uv run modal app list

  4. GPU: Qwen2.5-32B-Instruct (bf16) on 80GB, else Qwen2.5-14B-Instruct.
     transformers AutoModelForCausalLM.generate — no vLLM / FlashInfer / nvcc.
     Confirm your workspace can schedule `gpu="H100"` (or A100-80GB).

  5. Re-run:
       uv run python scripts/05_select_pilot_2k.py
       uv run python scripts/06_silver_label_pilot.py

OpenAI/Anthropic is an allowed fallback ONLY if you add an API key and we
record backend=openai|anthropic in the manifest. It is not automatic.
""".strip()
