from __future__ import annotations

import sqlite3
from pathlib import Path

from .paths import resource_root, writable_root

BASE_DIR = resource_root()
DATA_DIR = writable_root() / "data"
THUMBS_DIR = DATA_DIR / "thumbs"
DB_PATH = DATA_DIR / "image_cube.db"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    ensure_dirs()
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                ext TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                dhash TEXT NOT NULL,
                blur_score REAL NOT NULL,
                quality_score REAL NOT NULL,
                category TEXT NOT NULL,
                exact_group TEXT NOT NULL DEFAULT '',
                name_group TEXT NOT NULL DEFAULT '',
                similar_group TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_images_sha ON images(sha256)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_images_dhash ON images(dhash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_images_category ON images(category)")


def row_to_dict(row: sqlite3.Row) -> dict[str, object]:
    return dict(row)
