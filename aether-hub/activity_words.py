"""Small editable local database for inference activity text."""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = ROOT / "activity_words.json"
DB_PATH = Path(
    os.environ.get("AETHER_ACTIVITY_WORDS_PATH", str(ROOT.parent / ".aetherstack" / "activity_words.json"))
)
_LOCK = threading.RLock()
_LANGUAGES = {"en", "et", "uk"}
_TONES = {"playful", "neutral", "mild-vulgar"}


def _read() -> dict[str, Any]:
    with _LOCK:
        if not DB_PATH.is_file() and DEFAULT_DB_PATH.is_file():
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            DB_PATH.write_bytes(DEFAULT_DB_PATH.read_bytes())
        value = json.loads(DB_PATH.read_text(encoding="utf-8"))
    words = value.get("words") if isinstance(value, dict) else None
    if not isinstance(words, list):
        raise ValueError("invalid activity words database")
    return value


def list_words() -> dict[str, Any]:
    value = _read()
    value["path"] = str(DB_PATH)
    return value


def add_word(body: dict[str, Any]) -> dict[str, Any]:
    text = str(body.get("text") or "").strip()
    if not text or len(text) > 160 or any(ord(char) < 32 for char in text):
        raise ValueError("text must be 1-160 printable characters")
    language = str(body.get("language") or "en").lower()
    tone = str(body.get("tone") or "playful").lower()
    if language not in _LANGUAGES:
        raise ValueError("language must be en, et, or uk")
    if tone not in _TONES:
        raise ValueError("tone must be playful, neutral, or mild-vulgar")
    value = _read()
    if any(str(item.get("text") or "").casefold() == text.casefold() for item in value["words"]):
        raise ValueError("activity text already exists")
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:28] or "word"
    item = {
        "id": f"{language}-{slug}-{uuid.uuid4().hex[:6]}",
        "text": text,
        "language": language,
        "tone": tone,
        "enabled": True,
    }
    value["words"].append(item)
    _write(value)
    return item


def delete_word(word_id: str) -> dict[str, Any]:
    word_id = str(word_id or "").strip()
    value = _read()
    kept = [item for item in value["words"] if item.get("id") != word_id]
    if len(kept) == len(value["words"]):
        raise ValueError("unknown activity word id")
    value["words"] = kept
    _write(value)
    return {"ok": True, "deleted": word_id}


def _write(value: dict[str, Any]) -> None:
    with _LOCK:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = DB_PATH.with_suffix(DB_PATH.suffix + ".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(DB_PATH)
