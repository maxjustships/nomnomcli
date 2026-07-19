from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from nomnomcli.db import LATEST_SCHEMA_VERSION, connect, get_stats, store_log

ITEM = {
    "name": "borscht",
    "grams": 100.0,
    "kcal": 55.0,
    "protein": 2.5,
    "fat": 2.1,
    "carbs": 6.4,
    "match_confidence": 1.0,
}
TOTALS = {"kcal": 55.0, "protein": 2.5, "fat": 2.1, "carbs": 6.4}


def test_connect_migrates_v1_database_without_losing_data(tmp_path):
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as legacy:
        legacy.executescript(
            """
            CREATE TABLE food_cache (
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
            CREATE TABLE log_entries (
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
            CREATE INDEX idx_log_entries_logged_at ON log_entries(logged_at);
            CREATE TABLE recipes (
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
            INSERT INTO food_cache VALUES
                ('legacy oats', 71, 2.54, 1.52, 12, NULL, NULL, 'legacy cache', 173904);
            INSERT INTO log_entries VALUES
                (7, '2026-07-18T12:00:00+00:00', 'food', 'lunch', '[{"name":"legacy oats"}]',
                 71, 2.54, 1.52, 12);
            INSERT INTO recipes VALUES
                (3, 'Legacy oats', 'https://example.test/oats', 2, '[{"name":"legacy oats"}]',
                 35.5, 1.27, 0.76, 6, '2026-07-18T11:00:00+00:00');
            """
        )

    with connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(food_cache)").fetchall()
        }
        assert "barcode" in columns
        assert {"brand", "lookup_query", "alternatives_json"} <= columns
        assert tuple(connection.execute("SELECT * FROM food_cache").fetchone()) == (
            "legacy oats",
            71.0,
            2.54,
            1.52,
            12.0,
            None,
            None,
            "legacy cache",
            173904,
            None,
            None,
            None,
            None,
        )
        assert tuple(connection.execute("SELECT * FROM log_entries").fetchone()) == (
            7,
            "2026-07-18T12:00:00+00:00",
            "food",
            "lunch",
            '[{"name":"legacy oats"}]',
            71.0,
            2.54,
            1.52,
            12.0,
        )
        assert tuple(connection.execute("SELECT * FROM recipes").fetchone()) == (
            3,
            "Legacy oats",
            "https://example.test/oats",
            2.0,
            '[{"name":"legacy oats"}]',
            35.5,
            1.27,
            0.76,
            6.0,
            "2026-07-18T11:00:00+00:00",
        )

    with connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 1
        assert connection.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION


def test_connect_creates_fresh_database_at_latest_schema(tmp_path):
    with connect(tmp_path / "fresh.sqlite3") as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
        assert {
            row[1] for row in connection.execute("PRAGMA table_info(food_cache)").fetchall()
        } >= {"name", "barcode"}


def test_today_stats_aggregate(user_db):
    now = datetime(2026, 7, 18, 12, tzinfo=UTC)
    with connect(user_db) as connection:
        store_log(connection, [ITEM], TOTALS, logged_at=now)
        store_log(connection, [ITEM], TOTALS, logged_at=now + timedelta(hours=1))
        result = get_stats(connection, "today", now)
    assert result["totals"]["kcal"] == 110
    assert len(result["meals"]) == 2


def test_week_excludes_previous_week(user_db):
    now = datetime(2026, 7, 18, 12, tzinfo=UTC)
    with connect(user_db) as connection:
        store_log(connection, [ITEM], TOTALS, logged_at=now)
        store_log(connection, [ITEM], TOTALS, logged_at=now - timedelta(days=8))
        result = get_stats(connection, "week", now)
    assert result["totals"]["kcal"] == 55


def test_empty_stats(user_db):
    now = datetime(2026, 7, 18, 12, tzinfo=UTC)
    with connect(user_db) as connection:
        result = get_stats(connection, "today", now)
    assert result["meals"] == []
    assert result["totals"]["kcal"] == 0


def test_connect_migrates_v01_food_cache(user_db):
    with sqlite3.connect(user_db) as connection:
        connection.execute(
            """CREATE TABLE food_cache (
                name TEXT PRIMARY KEY COLLATE NOCASE,
                kcal REAL NOT NULL,
                protein REAL NOT NULL,
                fat REAL NOT NULL,
                carbs REAL NOT NULL,
                piece_grams REAL,
                density_g_ml REAL,
                source TEXT NOT NULL,
                fdc_id INTEGER
            )"""
        )
    with connect(user_db) as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(food_cache)")}
    assert {"barcode", "brand", "lookup_query", "alternatives_json"} <= columns
