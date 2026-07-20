from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

LATEST_SCHEMA_VERSION = 4
V1_TABLES = frozenset({"food_cache", "log_entries", "recipes"})

LATEST_SCHEMA = (
    """CREATE TABLE food_cache (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    kcal REAL NOT NULL,
    protein REAL NOT NULL,
    fat REAL NOT NULL,
    carbs REAL NOT NULL,
    piece_grams REAL,
    density_g_ml REAL,
    source TEXT NOT NULL,
    fdc_id INTEGER,
    barcode TEXT,
    brand TEXT,
    lookup_query TEXT,
    alternatives_json TEXT,
    piece_grams_source TEXT,
    piece_grams_source_value TEXT
)""",
    """CREATE TABLE log_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'food',
    label TEXT,
    items_json TEXT NOT NULL,
    kcal REAL NOT NULL,
    protein REAL NOT NULL,
    fat REAL NOT NULL,
    carbs REAL NOT NULL
)""",
    "CREATE INDEX idx_log_entries_logged_at ON log_entries(logged_at)",
    """CREATE TABLE recipes (
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
    )""",
    """CREATE TABLE food_aliases (
    phrase TEXT NOT NULL,
    normalized_phrase TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL COLLATE NOCASE
)""",
)


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}


def _set_user_version(connection: sqlite3.Connection, version: int) -> None:
    connection.execute(f"PRAGMA user_version = {version}")


def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    if "food_cache" not in _table_names(connection):
        raise sqlite3.DatabaseError("schema v1 is missing the food_cache table")
    columns = _column_names(connection, "food_cache")
    additions = {
        "barcode": "ALTER TABLE food_cache ADD COLUMN barcode TEXT",
        "brand": "ALTER TABLE food_cache ADD COLUMN brand TEXT",
        "lookup_query": "ALTER TABLE food_cache ADD COLUMN lookup_query TEXT",
        "alternatives_json": "ALTER TABLE food_cache ADD COLUMN alternatives_json TEXT",
    }
    for column, statement in additions.items():
        if column not in columns:
            connection.execute(statement)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_food_cache_lookup_query "
        "ON food_cache(lookup_query COLLATE NOCASE)"
    )


def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS food_aliases (
        phrase TEXT NOT NULL,
        normalized_phrase TEXT PRIMARY KEY,
        canonical_name TEXT NOT NULL COLLATE NOCASE
    )"""
    )


def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
    columns = _column_names(connection, "food_cache")
    additions = {
        "piece_grams_source": "ALTER TABLE food_cache ADD COLUMN piece_grams_source TEXT",
        "piece_grams_source_value": (
            "ALTER TABLE food_cache ADD COLUMN piece_grams_source_value TEXT"
        ),
    }
    for column, statement in additions.items():
        if column not in columns:
            connection.execute(statement)


MIGRATIONS = {1: _migrate_v1_to_v2, 2: _migrate_v2_to_v3, 3: _migrate_v3_to_v4}


def _initialize_database(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version > LATEST_SCHEMA_VERSION:
            raise sqlite3.DatabaseError(
                f"database schema version {version} is newer than supported "
                f"version {LATEST_SCHEMA_VERSION}"
            )

        if version == 0 and _table_names(connection) & V1_TABLES:
            version = 1
            _set_user_version(connection, version)

        if version == 0:
            for statement in LATEST_SCHEMA:
                connection.execute(statement)
            _set_user_version(connection, LATEST_SCHEMA_VERSION)
        else:
            while version < LATEST_SCHEMA_VERSION:
                MIGRATIONS[version](connection)
                version += 1
                _set_user_version(connection, version)
            missing = V1_TABLES - _table_names(connection)
            for statement in LATEST_SCHEMA:
                if "TABLE " not in statement:
                    continue
                table = statement.split("TABLE ", 1)[1].split(" ", 1)[0].strip().strip("(")
                if table in missing:
                    connection.execute(statement)
        connection.commit()
    except Exception:
        connection.rollback()
        raise


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
    try:
        connection.row_factory = sqlite3.Row
        _initialize_database(connection)
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
