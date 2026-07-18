from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS food_cache (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    kcal REAL NOT NULL,
    protein REAL NOT NULL,
    fat REAL NOT NULL,
    carbs REAL NOT NULL,
    piece_grams REAL,
    density_g_ml REAL,
    source TEXT NOT NULL,
    fdc_id INTEGER
);
CREATE TABLE IF NOT EXISTS log_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'food',
    label TEXT,
    items_json TEXT NOT NULL,
    kcal REAL NOT NULL,
    protein REAL NOT NULL,
    fat REAL NOT NULL,
    carbs REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_log_entries_logged_at ON log_entries(logged_at);
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    source_url TEXT NOT NULL,
    servings REAL NOT NULL,
    ingredients_json TEXT NOT NULL,
    kcal_per_serving REAL NOT NULL,
    protein_per_serving REAL NOT NULL,
    fat_per_serving REAL NOT NULL,
    carbs_per_serving REAL NOT NULL,
    created_at TEXT NOT NULL
);
"""


def default_db_path() -> Path:
    override = os.getenv("NOMNOM_DB_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "share" / "nomnomcli" / "nomnom.sqlite3"


@contextmanager
def connect(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    db_path = Path(path) if path is not None else default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def store_log(
    connection: sqlite3.Connection,
    items: list[dict],
    totals: dict[str, float],
    *,
    kind: str = "food",
    label: str | None = None,
    logged_at: datetime | None = None,
) -> int:
    timestamp = (logged_at or datetime.now().astimezone()).isoformat(timespec="seconds")
    cursor = connection.execute(
        """INSERT INTO log_entries
        (logged_at, kind, label, items_json, kcal, protein, fat, carbs)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            timestamp,
            kind,
            label,
            json.dumps(items, ensure_ascii=False, sort_keys=True),
            totals["kcal"],
            totals["protein"],
            totals["fat"],
            totals["carbs"],
        ),
    )
    return int(cursor.lastrowid)


def period_start(period: str, now: datetime | None = None) -> datetime:
    current = now or datetime.now().astimezone()
    if period == "today":
        return current.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        today = current.replace(hour=0, minute=0, second=0, microsecond=0)
        return today - timedelta(days=today.weekday())
    raise ValueError(f"unsupported period: {period}")


def get_stats(connection: sqlite3.Connection, period: str, now: datetime | None = None) -> dict:
    start = period_start(period, now)
    rows = connection.execute(
        "SELECT * FROM log_entries WHERE logged_at >= ? ORDER BY logged_at, id",
        (start.isoformat(timespec="seconds"),),
    ).fetchall()
    meals = []
    totals = {key: 0.0 for key in ("kcal", "protein", "fat", "carbs")}
    for row in rows:
        meal_totals = {key: round(float(row[key]), 2) for key in totals}
        for key, value in meal_totals.items():
            totals[key] += value
        meals.append(
            {
                "id": row["id"],
                "logged_at": row["logged_at"],
                "kind": row["kind"],
                "label": row["label"],
                "items": json.loads(row["items_json"]),
                "totals": meal_totals,
            }
        )
    return {
        "period": period,
        "from": start.isoformat(timespec="seconds"),
        "totals": {key: round(value, 2) for key, value in totals.items()},
        "meals": meals,
    }
