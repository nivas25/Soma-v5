"""Gemini client for the speak path.

The key is read from GEMINI_API_KEY only. It is sent as a header, never placed
in a URL, and stripped from any error text this module raises.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Callable

import httpx
from dotenv import load_dotenv

from soma_data.config import ROOT

MODEL = "gemini-3.8-flash"
_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
_RETRY_STATUS = {500, 502, 503, 504}

load_dotenv(ROOT / ".env")


class GeminiError(RuntimeError):
    """Model call failed. The message never contains the API key."""


def _key() -> str:
    return (os.environ.get("GEMINI_API_KEY") or "").strip()


def _redact(text: str, key: str) -> str:
    if key and key in text:
        return text.replace(key, "[redacted]")
    return text


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def parse_model_json(text: str) -> dict:
    """Parse one JSON object from a model reply. Raises ValueError on failure."""
    raw = _FENCE.sub("", (text or "").strip())
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("model did not return JSON") from None
        value = json.loads(raw[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model JSON was not an object")
    return value


def _retry_after(text: str) -> float | None:
    """Seconds to wait, only when the server asks for a short pause."""
    match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", text or "", re.I)
    if not match or re.search(r"retry in \d+\s*h|\d+\s*m", text or "", re.I):
        return None
    seconds = float(match.group(1))
    if seconds <= 0 or seconds > 20:
        return None
    return seconds


def _extract_text(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise GeminiError("model returned no candidates")
    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    visible = [p.get("text") or "" for p in parts if p.get("text") and not p.get("thought")]
    if not visible:
        visible = [p.get("text") or "" for p in parts if p.get("text")]
    text = "\n".join(piece for piece in visible if piece).strip()
    if not text:
        raise GeminiError("model returned empty text")
    return text


class GeminiClient:
    """One generateContent call. Pass `transport` in tests to skip the network."""

    def __init__(self, transport: Callable[[str], str] | None = None) -> None:
        self._transport = transport

    def complete(self, prompt: str) -> str:
        if self._transport is not None:
            return self._transport(prompt)
        key = _key()
        if not key:
            raise GeminiError("GEMINI_API_KEY is not set")
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 1024,
                "thinkingConfig": {"thinkingLevel": "low"},
            },
        }
        headers = {"Content-Type": "application/json", "x-goog-api-key": key}
        last_error = "model request failed"
        with httpx.Client(timeout=90.0) as http:
            for attempt in range(5):
                try:
                    response = http.post(_ENDPOINT, headers=headers, json=body)
                except httpx.HTTPError as exc:
                    last_error = _redact(str(exc), key)
                    time.sleep(2 * (attempt + 1))
                    continue
                if response.status_code == 400 and "thinkingConfig" in body["generationConfig"]:
                    body = {
                        "contents": body["contents"],
                        "generationConfig": {"temperature": 0, "maxOutputTokens": 1024},
                    }
                    continue
                if response.status_code == 429:
                    delay = _retry_after(response.text) if attempt == 0 else None
                    if delay is None:
                        raise GeminiError("model HTTP 429")
                    time.sleep(delay)
                    continue
                if response.status_code in _RETRY_STATUS:
                    last_error = f"model HTTP {response.status_code}"
                    time.sleep(4 * (attempt + 1))
                    continue
                if response.status_code >= 400:
                    detail = _redact(response.text[:300], key)
                    raise GeminiError(f"model HTTP {response.status_code}: {detail}")
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise GeminiError(_redact(f"model returned non-json: {exc}", key)) from None
                return _extract_text(payload)
        raise GeminiError(last_error)
