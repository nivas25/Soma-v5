"""Local audit CSV store for the labelling UI. No model calls."""

from __future__ import annotations

import json
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from soma_data.config import (
    AUDIT_200_BAK,
    AUDIT_200_CSV,
    FRIENDS_DIR,
    LABEL_QUEUE_CSV,
    LABEL_QUEUE_PARQUET,
    MANU_200_CSV,
    PUNITH_200_CSV,
)

REVIEWER = "nivas"
ALLOWED = frozenset({"SPEAK", "SILENT"})
ANNOTATORS = ("manu", "punith", "nivas")


def annotator_files(name: str) -> tuple[Path, Path]:
    n = str(name or "").strip().lower()
    if n == "nivas":
        return AUDIT_200_CSV, AUDIT_200_BAK
    if n == "manu":
        return MANU_200_CSV, FRIENDS_DIR / "manu_200.bak.csv"
    if n == "punith":
        return PUNITH_200_CSV, FRIENDS_DIR / "punith_200.bak.csv"
    raise ValueError(f"unknown annotator {name!r}; expected {ANNOTATORS}")


def parse_chat(chat_block: str, last_line: str = "") -> list[dict[str, Any]]:
    lines = [ln for ln in str(chat_block or "").splitlines() if ln.strip()]
    last = str(last_line or "").strip()
    out: list[dict[str, Any]] = []
    for ln in lines:
        action = ln.startswith("* ")
        if action:
            rest = ln[2:].strip()
            nick = rest.split()[0] if rest.split() else ""
            text = rest
        elif ": " in ln:
            nick, text = ln.split(": ", 1)
        elif ln.startswith("==="):
            nick, text = "", ln
        else:
            nick, text = "", ln
        is_last = bool(last) and ln.strip() == last
        out.append({"nick": nick, "text": text, "raw": ln, "action": action, "is_last": is_last})
    if out and not any(m["is_last"] for m in out):
        out[-1]["is_last"] = True
    return out


_NICK_COLON = re.compile(r"^(\S+):\s?(.*)$")


def _truthy_flag(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "t"}


def _chat_lines_for_copy(chat_block: str) -> str:
    """Keep stored nick/text pairs, or split 'nick: text' lines into that shape."""
    raw = str(chat_block or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = raw.split("\n")
    nonempty = [ln for ln in lines if ln.strip()]
    if not nonempty:
        return raw.rstrip("\n")
    scored = [
        ln
        for ln in nonempty
        if not ln.startswith("* ") and not ln.startswith("===")
    ]
    colon_hits = sum(1 for ln in scored if _NICK_COLON.match(ln))
    already_pairs = not scored or colon_hits < max(1, (len(scored) + 1) // 2)
    if already_pairs:
        return "\n".join(lines).rstrip("\n")
    out: list[str] = []
    for ln in lines:
        if ln.startswith("* ") or ln.startswith("==="):
            out.append(ln)
            continue
        m = _NICK_COLON.match(ln)
        if m:
            out.append(m.group(1))
            out.append(m.group(2))
        else:
            out.append(ln)
    return "\n".join(out).rstrip("\n")


def format_copy_text(row: dict[str, Any]) -> str:
    """Plain-text paste block Nivas uses. Does not invent CSV columns."""
    wid = str(row.get("window_id") or "")
    date = str(row.get("date") or "").strip()
    speaker = str(row.get("last_speaker") or "").strip()
    header = f"{wid}{date}last {speaker}"
    chat = _chat_lines_for_copy(str(row.get("chat_block") or ""))
    last = str(row.get("last_line") or "")
    parts = [header]
    if chat:
        parts.append(chat)
    parts.append("Decide after this line")
    parts.append(last)
    return "\n".join(parts)


class AuditStore:
    def __init__(
        self,
        path: Path | None = None,
        bak: Path | None = None,
        *,
        reviewer: str = REVIEWER,
        skip_reset: bool = False,
        hide_teacher_hints: bool = False,
    ) -> None:
        self.path = path or AUDIT_200_CSV
        self.bak = bak or AUDIT_200_BAK
        self.reviewer = str(reviewer or REVIEWER).strip().lower() or REVIEWER
        self.skip_reset = skip_reset
        self.hide_teacher_hints = hide_teacher_hints
        self.lock = threading.Lock()
        self.undo: list[dict[str, Any]] = []
        self.reset_happened = False
        self._prepare()
        self.df = self._read()

    def _read(self) -> pd.DataFrame:
        df = pd.read_csv(self.path, dtype=str, keep_default_na=False)
        if "grok_draft" not in df.columns:
            df["grok_draft"] = ""
        if "reviewed_at" not in df.columns:
            df["reviewed_at"] = ""
        if "notes" not in df.columns:
            df["notes"] = ""
        if "labeler" not in df.columns:
            df["labeler"] = ""
        return df

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.df.to_csv(self.path, index=False)

    def _prepare(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"missing {self.path}")
        if self.skip_reset or self.bak.exists():
            return
        shutil.copy2(self.path, self.bak)
        df = pd.read_csv(self.path, dtype=str, keep_default_na=False)
        if "grok_draft" not in df.columns:
            df["grok_draft"] = ""
        # Preserve the Grok draft before clearing gold.
        if "label_gold" in df.columns:
            empty_draft = df["grok_draft"].astype(str).str.strip() == ""
            df.loc[empty_draft, "grok_draft"] = df.loc[empty_draft, "label_gold"]
        df["label_gold"] = ""
        df["reviewed_by"] = ""
        df["review_ok"] = ""
        df["agree_with_silver"] = ""
        df["reviewed_at"] = ""
        df["notes"] = ""
        df.to_csv(self.path, index=False)
        self.reset_happened = True

    def n(self) -> int:
        return int(len(self.df))

    def counts(self) -> dict[str, int]:
        gold = self.df["label_gold"].str.strip().str.upper()
        ok = self.df["review_ok"].str.strip().str.upper().eq("Y")
        return {
            "n": self.n(),
            "done": int(ok.sum()),
            "speak": int((gold.eq("SPEAK") & ok).sum()),
            "silent": int((gold.eq("SILENT") & ok).sum()),
            "empty": int((~ok).sum()),
        }

    def first_unreviewed(self, after: int = -1) -> int | None:
        n = self.n()
        if n == 0:
            return None
        ok = self.df["review_ok"].str.strip().str.upper()
        for step in range(1, n + 1):
            i = (after + step) % n
            if ok.iloc[i] != "Y":
                return int(i)
        return None

    def row_payload(self, index: int, *, show_hints: bool = False) -> dict[str, Any]:
        if index < 0 or index >= self.n():
            raise IndexError(index)
        r = self.df.iloc[index].to_dict()
        labelled = str(r.get("review_ok") or "").strip().upper() == "Y"
        last = str(r.get("last_line") or "")
        addr = str(r.get("addressed_to") or "").strip()
        helper = False
        try:
            from soma_data.teacher_prompt_v2_2 import helper_in_window as _helper_in_window

            helper = bool(_helper_in_window(r))
        except Exception:
            helper = _truthy_flag(r.get("helper_in_window"))
        payload = {
            "index": index,
            "n": self.n(),
            "window_id": r.get("window_id") or "",
            "date": r.get("date") or "",
            "split": r.get("split") or "",
            "last_speaker": r.get("last_speaker") or "",
            "last_line": last,
            "chat_block": r.get("chat_block") or "",
            "copy_text": format_copy_text(r),
            "last_is_question": _truthy_flag(r.get("last_is_question")),
            "last_is_thanks": _truthy_flag(r.get("last_is_thanks")),
            "addressed_to": addr,
            "helper_in_window": helper,
            "messages": parse_chat(str(r.get("chat_block") or ""), last),
            "label_gold": r.get("label_gold") or "",
            "review_ok": r.get("review_ok") or "",
            "reviewed_by": r.get("reviewed_by") or "",
            "reviewed_at": r.get("reviewed_at") or "",
            "notes": r.get("notes") or "",
            "counts": self.counts(),
        }
        if self.hide_teacher_hints:
            payload["hints"] = None
            payload["hide_hints"] = True
        elif show_hints or labelled:
            payload["hints"] = {
                "label_silver": r.get("label_silver") or "",
                "silver_reason": r.get("reason") or "",
                "grok_draft": r.get("grok_draft") or "",
                "judge_reason": r.get("judge_reason") or "",
                "guideline_hint": r.get("guideline_hint") or "",
            }
        else:
            payload["hints"] = None
        payload["annotator"] = self.reviewer
        payload["hide_hints"] = bool(self.hide_teacher_hints)
        return payload

    def save_label(self, index: int, label: str, notes: str = "") -> dict[str, Any]:
        lab = str(label).strip().upper()
        if lab not in ALLOWED:
            raise ValueError("label must be SPEAK or SILENT")
        with self.lock:
            prev = self.df.iloc[index].to_dict()
            self.undo.append({"index": index, "row": prev})
            self.undo = self.undo[-20:]
            silver = str(self.df.at[index, "label_silver"] or "").strip().upper()
            agree = ""
            if silver in ALLOWED:
                agree = "Y" if lab == silver else "N"
            self.df.at[index, "label_gold"] = lab
            self.df.at[index, "reviewed_by"] = self.reviewer
            if "labeler" in self.df.columns:
                self.df.at[index, "labeler"] = self.reviewer
            self.df.at[index, "review_ok"] = "Y"
            self.df.at[index, "agree_with_silver"] = agree
            self.df.at[index, "reviewed_at"] = datetime.now(timezone.utc).isoformat()
            self.df.at[index, "notes"] = notes
            self._write()
            nxt = self.first_unreviewed(index)
            done = self.counts()["empty"] == 0
            if done:
                self._write_done_unlocked()
            return {
                "saved": self.row_payload(index, show_hints=not self.hide_teacher_hints),
                "next_index": nxt,
                "complete": done,
            }

    def skip(self, index: int) -> dict[str, Any]:
        with self.lock:
            nxt = self.first_unreviewed(index)
            return {"next_index": nxt}

    def undo_last(self) -> dict[str, Any]:
        with self.lock:
            if not self.undo:
                return {"ok": False, "index": self.first_unreviewed(-1)}
            item = self.undo.pop()
            i = int(item["index"])
            for k, v in item["row"].items():
                if k in self.df.columns:
                    self.df.at[i, k] = v if v is not None else ""
            self._write()
            return {"ok": True, "index": i, "item": self.row_payload(i)}

    def stats(self) -> dict[str, Any]:
        df = self.df
        ok = df["review_ok"].str.strip().str.upper().eq("Y")
        gold = df["label_gold"].str.strip().str.upper()
        silver = df["label_silver"].str.strip().str.upper()
        grok = df["grok_draft"].str.strip().str.upper()
        labelled = df[ok]
        n_lab = int(ok.sum())
        vs_silver = labelled[labelled["label_silver"].str.strip().str.upper().isin(ALLOWED)]
        vs_grok = labelled[labelled["grok_draft"].str.strip().str.upper().isin(ALLOWED)]
        n_s = len(vs_silver)
        n_g = len(vs_grok)
        agree_s = int((vs_silver["label_gold"].str.upper() == vs_silver["label_silver"].str.upper()).sum()) if n_s else 0
        agree_g = int((vs_grok["label_gold"].str.upper() == vs_grok["grok_draft"].str.upper()).sum()) if n_g else 0
        unsure = int(labelled["notes"].str.contains("unsure", case=False, na=False).sum())
        return {
            "n": int(len(df)),
            "done": n_lab,
            "speak": int((ok & gold.eq("SPEAK")).sum()),
            "silent": int((ok & gold.eq("SILENT")).sum()),
            "unsure": unsure,
            "agree_silver": agree_s,
            "agree_silver_n": n_s,
            "agree_silver_pct": round(100 * agree_s / n_s, 1) if n_s else None,
            "agree_grok": agree_g,
            "agree_grok_n": n_g,
            "agree_grok_pct": round(100 * agree_g / n_g, 1) if n_g else None,
            "complete": n_lab == int(len(df)),
        }

    def _write_done_unlocked(self) -> dict[str, Any]:
        FRIENDS_DIR.mkdir(parents=True, exist_ok=True)
        name = self.reviewer.lower()
        csv_path = FRIENDS_DIR / f"{name}_done.csv"
        jsonl_path = FRIENDS_DIR / f"{name}_done.jsonl"
        self.df.to_csv(csv_path, index=False)
        recs = self.df.to_dict(orient="records")
        with jsonl_path.open("w", encoding="utf-8") as fh:
            for rec in recs:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return {
            "csv": str(csv_path),
            "jsonl": str(jsonl_path),
            "n": int(len(self.df)),
            "done": int(self.counts()["done"]),
            "annotator": name,
        }

    def write_done(self) -> dict[str, Any]:
        with self.lock:
            return self._write_done_unlocked()

    def export_queue(self) -> dict[str, Any]:
        """Copy reviewed gold onto label_queue for those ids only."""
        with self.lock:
            reviewed = self.df[self.df["review_ok"].str.strip().str.upper().eq("Y")].copy()
            if reviewed.empty:
                raise RuntimeError("no reviewed rows to export")
            bad = reviewed[~reviewed["label_gold"].str.strip().str.upper().isin(ALLOWED)]
            if not bad.empty:
                raise RuntimeError(f"{len(bad)} reviewed rows missing SPEAK/SILENT")
            q = pd.read_csv(LABEL_QUEUE_CSV, dtype=str, keep_default_na=False)
            gold_map = dict(zip(reviewed["window_id"], reviewed["label_gold"].str.strip().str.upper()))
            who_map = dict(zip(reviewed["window_id"], reviewed["reviewed_by"].str.strip()))
            missing = [i for i in gold_map if i not in set(q["window_id"])]
            if missing:
                raise RuntimeError(f"{len(missing)} ids not in label_queue")
            mask = q["window_id"].isin(gold_map)
            q.loc[mask, "label_gold"] = q.loc[mask, "window_id"].map(gold_map)
            q.loc[mask, "labeler"] = q.loc[mask, "window_id"].map(who_map)
            q.to_csv(LABEL_QUEUE_CSV, index=False)
            if LABEL_QUEUE_PARQUET.exists():
                q.to_parquet(LABEL_QUEUE_PARQUET, index=False)
            return {
                "n_applied": int(mask.sum()),
                "queue_gold_filled": int(q["label_gold"].str.strip().ne("").sum()),
                "audit_done": int(len(reviewed)),
                "audit_n": self.n(),
            }


_STORES: dict[str, AuditStore] = {}


def make_store(annotator: str) -> AuditStore:
    name = str(annotator).strip().lower()
    path, bak = annotator_files(name)
    friend = name in {"manu", "punith"}
    return AuditStore(
        path,
        bak,
        reviewer=name,
        skip_reset=friend,
        hide_teacher_hints=friend,
    )


def get_store(annotator: str | None = None) -> AuditStore:
    name = str(annotator or REVIEWER).strip().lower() or REVIEWER
    if name not in ANNOTATORS:
        raise ValueError(f"unknown annotator {annotator!r}")
    if name not in _STORES:
        _STORES[name] = make_store(name)
    return _STORES[name]


def reset_stores() -> None:
    _STORES.clear()
