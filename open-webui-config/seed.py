"""Keep Open WebUI attached to AetherStack's dynamic local gateway.

Open WebUI persists provider settings in SQLite, so changing compose environment
variables alone does not repair an existing installation. This migration changes
only the Ollama/OpenAI provider rows and takes a one-time SQLite backup first.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(os.environ.get("DATA_DIR", "/app/backend/data")) / "webui.db"
BACKUP_PATH = DB_PATH.with_name("webui.db.aetherstack-before-gateway.bak")
BASE_URL = os.environ.get("AETHER_OPENAI_BASE_URL", "http://aether-hub:8766/v1").rstrip("/")
API_KEY = os.environ.get("OPENAI_API_KEY", "")


def _read_json(connection: sqlite3.Connection, key: str, default):
    row = connection.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return default


def seed(path: Path = DB_PATH) -> bool:
    if not path.is_file():
        return False
    connection = sqlite3.connect(path, timeout=30)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(config)")}
        if not {"key", "value"}.issubset(columns):
            print("[aetherstack] Open WebUI config schema is unknown; using environment defaults")
            return False
        backup_path = path.with_name(BACKUP_PATH.name)
        if not backup_path.exists():
            backup = sqlite3.connect(backup_path)
            try:
                connection.backup(backup)
            finally:
                backup.close()
            os.chmod(backup_path, 0o600)
        now = int(time.time())
        old_urls = _read_json(connection, "openai.api_base_urls", [])
        old_keys = _read_json(connection, "openai.api_keys", [])
        old_configs = _read_json(connection, "openai.api_configs", {})
        retained: list[tuple[str, str, dict]] = []
        if isinstance(old_urls, list):
            for index, raw_url in enumerate(old_urls):
                url = str(raw_url or "").rstrip("/")
                key = str(old_keys[index] if isinstance(old_keys, list) and index < len(old_keys) else "")
                # Replace previous Aether routes and discard only the unused OpenAI default.
                if not url or url in {BASE_URL, "http://litellm:4000/v1"}:
                    continue
                if url == "https://api.openai.com/v1" and not key:
                    continue
                config = {}
                if isinstance(old_configs, dict):
                    value = old_configs.get(str(index), old_configs.get(url, {}))
                    if isinstance(value, dict):
                        config = value
                retained.append((url, key, config))
        api_urls = [BASE_URL, *(url for url, _, _ in retained)]
        api_keys = [API_KEY, *(key for _, key, _ in retained)]
        api_configs = {"0": {"enable": True, "provider": "aetherstack"}}
        for index, (_, _, config) in enumerate(retained, start=1):
            if config:
                api_configs[str(index)] = config
        values = {
            "ollama.enable": False,
            "openai.enable": True,
            "openai.api_base_urls": api_urls,
            "openai.api_keys": api_keys,
            "openai.api_configs": api_configs,
        }
        has_updated_at = "updated_at" in columns
        for key, value in values.items():
            encoded = json.dumps(value, separators=(",", ":"))
            if has_updated_at:
                connection.execute(
                    "INSERT INTO config(key,value,updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                    (key, encoded, now),
                )
            else:
                connection.execute(
                    "INSERT INTO config(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, encoded),
                )
        connection.commit()
        os.chmod(path, 0o600)
        print(f"[aetherstack] Open WebUI provider set to {BASE_URL}; direct Ollama listing disabled")
        return True
    finally:
        connection.close()


if __name__ == "__main__":
    seed()
