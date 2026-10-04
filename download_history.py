"""应用自有的下载历史记录，保存到本地 SQLite，不含任何凭据。"""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from download_models import RECORDED_STATUSES
from ncm_settings import app_data_dir

COMPLETED_STATUSES = ("已完成", "已跳过")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_kind TEXT NOT NULL,
    source_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    artist TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    fmt TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)
"""


def history_path() -> Path:
    return app_data_dir() / "library.sqlite3"


def record(entry: dict, path: Path | None = None) -> int:
    path = path if path is not None else history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=2)
    try:
        with connection:
            connection.execute(_SCHEMA)
            cursor = connection.execute(
                "INSERT INTO downloads (source_kind, source_id, title, artist, url, path, fmt, "
                "status, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(entry.get("source_kind", "")),
                    str(entry.get("source_id", "")),
                    str(entry.get("title", "")),
                    str(entry.get("artist", "")),
                    str(entry.get("url", "")),
                    str(entry.get("path", "")),
                    str(entry.get("fmt", "")),
                    str(entry.get("status", "")),
                    str(entry.get("detail", "")),
                    datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                ),
            )
            return int(cursor.lastrowid)
    finally:
        connection.close()


def load_completed(path: Path | None = None, limit: int = 1000) -> list[dict]:
    path = path if path is not None else history_path()
    if not path.is_file():
        return []
    connection = sqlite3.connect(path, timeout=2)
    connection.row_factory = sqlite3.Row
    try:
        placeholders = ", ".join("?" for _ in COMPLETED_STATUSES)
        rows = connection.execute(
            f"SELECT * FROM downloads WHERE status IN ({placeholders}) "
            "ORDER BY id DESC LIMIT ?",
            (*COMPLETED_STATUSES, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []
    finally:
        connection.close()
