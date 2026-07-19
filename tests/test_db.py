from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from nomnomcli.db import connect, get_stats, store_log

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
