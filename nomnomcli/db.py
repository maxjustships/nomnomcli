from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
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
    piece_grams_source_value TEXT,
    resolution_mode TEXT NOT NULL DEFAULT 'legacy',
    source_id TEXT,
    source_note TEXT,
    provenance TEXT,
    assumption TEXT
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


def _ensure_v4_food_cache(connection: sqlite3.Connection) -> None:
    columns = _column_names(connection, "food_cache")
    additions = {
        "piece_grams_source": "ALTER TABLE food_cache ADD COLUMN piece_grams_source TEXT",
        "piece_grams_source_value": (
            "ALTER TABLE food_cache ADD COLUMN piece_grams_source_value TEXT"
        ),
        "resolution_mode": (
            "ALTER TABLE food_cache ADD COLUMN resolution_mode "
            "TEXT NOT NULL DEFAULT 'legacy'"
        ),
        "source_id": "ALTER TABLE food_cache ADD COLUMN source_id TEXT",
        "source_note": "ALTER TABLE food_cache ADD COLUMN source_note TEXT",
        "provenance": "ALTER TABLE food_cache ADD COLUMN provenance TEXT",
        "assumption": "ALTER TABLE food_cache ADD COLUMN assumption TEXT",
    }
    for column, statement in additions.items():
        if column not in columns:
            connection.execute(statement)
    connection.execute(
        """UPDATE food_cache
        SET source_id = COALESCE(barcode, CAST(fdc_id AS TEXT))
        WHERE source_id IS NULL"""
    )
    connection.execute(
        "UPDATE food_cache SET provenance = source WHERE provenance IS NULL"
    )


def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
    _ensure_v4_food_cache(connection)


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
        if "food_cache" in _table_names(connection):
            _ensure_v4_food_cache(connection)
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


@contextmanager
def connect_read_only(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open user state without creating, migrating, committing, or modifying it."""
    db_path = Path(path) if path is not None else default_db_path()
    if db_path.exists():
        uri = f"{db_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    else:
        connection = sqlite3.connect(":memory:")
        for statement in LATEST_SCHEMA:
            connection.execute(statement)
        _set_user_version(connection, LATEST_SCHEMA_VERSION)
        connection.commit()
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        yield connection
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


def local_day_bounds(local_date: date) -> tuple[datetime, datetime]:
    next_date = local_date + timedelta(days=1)
    start = datetime(local_date.year, local_date.month, local_date.day).astimezone()
    end = datetime(next_date.year, next_date.month, next_date.day).astimezone()
    return start, end


def get_stats(
    connection: sqlite3.Connection,
    period: str,
    now: datetime | None = None,
    *,
    local_date: date | None = None,
) -> dict:
    end = None
    if period == "date":
        if local_date is None:
            raise ValueError("local_date is required for the date period")
        start, end = local_day_bounds(local_date)
        rows = connection.execute(
            """SELECT * FROM log_entries
            WHERE julianday(logged_at) >= julianday(?)
              AND julianday(logged_at) < julianday(?)
            ORDER BY logged_at, id""",
            (start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")),
        ).fetchall()
    else:
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
        items = json.loads(row["items_json"])
        meals.append(
            {
                "id": row["id"],
                "logged_at": row["logged_at"],
                "kind": row["kind"],
                "label": row["label"],
                "items": items,
                "totals": meal_totals,
                "approximate": any(item.get("approximate") is True for item in items),
            }
        )
    result = {
        "period": period,
        "from": start.isoformat(timespec="seconds"),
        "totals": {key: round(value, 2) for key, value in totals.items()},
        "meals": meals,
        "approximate": any(meal["approximate"] for meal in meals),
    }
    if end is not None:
        result["to"] = end.isoformat(timespec="seconds")
        result["local_date"] = local_date.isoformat()
    return result
