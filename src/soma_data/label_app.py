"""FastAPI labelling UI. Local only. No GPU, no LLM."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from soma_data.label_store import ANNOTATORS, get_store

HTML_PATH = Path(__file__).resolve().parent / "templates" / "label.html"

app = FastAPI(title="SOMA label", docs_url=None, redoc_url=None)


class LabelIn(BaseModel):
    index: int
    label: str
    notes: str = ""


class IndexIn(BaseModel):
    index: int = Field(ge=0)


class AnnotatorIn(BaseModel):
    name: str


def _cli_annotator() -> str | None:
    raw = (os.environ.get("SOMA_ANNOTATOR") or "").strip().lower()
    return raw if raw in ANNOTATORS else None


def _name(annotator: str | None) -> str:
    raw = (annotator or _cli_annotator() or "").strip().lower()
    if raw not in ANNOTATORS:
        raise HTTPException(400, "pick annotator: manu | punith | nivas")
    return raw


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


@app.get("/api/who")
def who(annotator: str | None = Query(default=None)) -> dict:
    raw = (annotator or _cli_annotator() or "").strip().lower()
    return {
        "annotator": raw if raw in ANNOTATORS else None,
        "names": list(ANNOTATORS),
        "cli": _cli_annotator(),
    }


@app.get("/api/resume")
def resume(annotator: str | None = Query(default=None)) -> dict:
    store = get_store(_name(annotator))
    counts = store.counts()
    i = store.first_unreviewed(-1)
    if i is None:
        return {
            "done": True,
            "counts": counts,
            "stats": store.stats(),
            "annotator": store.reviewer,
            "hide_hints": store.hide_teacher_hints,
        }
    return {
        "done": False,
        "counts": counts,
        "item": store.row_payload(i),
        "annotator": store.reviewer,
        "hide_hints": store.hide_teacher_hints,
    }


@app.get("/api/item/{index}")
def item(index: int, hints: bool = Query(default=False), annotator: str | None = Query(default=None)) -> dict:
    store = get_store(_name(annotator))
    try:
        return store.row_payload(index, show_hints=hints)
    except IndexError as exc:
        raise HTTPException(404, "index out of range") from exc


@app.get("/api/stats")
def stats(annotator: str | None = Query(default=None)) -> dict:
    store = get_store(_name(annotator))
    out = store.stats()
    out["annotator"] = store.reviewer
    out["hide_hints"] = store.hide_teacher_hints
    return out


@app.post("/api/label")
def label(body: LabelIn, annotator: str | None = Query(default=None)) -> dict:
    store = get_store(_name(annotator))
    try:
        return store.save_label(body.index, body.label, body.notes)
    except (IndexError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/skip")
def skip(body: IndexIn, annotator: str | None = Query(default=None)) -> dict:
    return get_store(_name(annotator)).skip(body.index)


@app.post("/api/undo")
def undo(annotator: str | None = Query(default=None)) -> dict:
    return get_store(_name(annotator)).undo_last()


@app.post("/api/finish")
def finish(annotator: str | None = Query(default=None)) -> dict:
    return get_store(_name(annotator)).write_done()


@app.post("/api/export")
def export(annotator: str | None = Query(default=None)) -> dict:
    store = get_store(_name(annotator))
    done = store.write_done()
    if store.reviewer == "nivas":
        try:
            done["queue"] = store.export_queue()
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc
    return done
