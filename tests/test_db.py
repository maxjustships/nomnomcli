from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

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


@pytest.fixture
def v2_database(tmp_path):
    database = tmp_path / "v2.sqlite3"
    with sqlite3.connect(database) as legacy:
        legacy.executescript(
            """
            PRAGMA user_version = 2;
            CREATE TABLE food_cache (
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
                alternatives_json TEXT
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
                ('v2 egg', 155, 12.58, 10.61, 1.12, 50, NULL, 'user', NULL,
                 NULL, 'Fixture', 'v2 egg fixture', '[]');
            INSERT INTO log_entries VALUES
                (9, '2026-07-19T12:00:00+00:00', 'food', 'v2 lunch',
                 '[{"name":"v2 egg"}]', 155, 12.58, 10.61, 1.12);
            INSERT INTO recipes VALUES
                (4, 'V2 eggs', 'https://example.test/v2-eggs', 2,
                 '[{"name":"v2 egg"}]', 77.5, 6.29, 5.305, 0.56,
                 '2026-07-19T11:00:00+00:00');
            """
        )
    return database


@pytest.fixture
def v3_database(tmp_path):
    database = tmp_path / "v3.sqlite3"
    with sqlite3.connect(database) as legacy:
        legacy.executescript(
            """
            PRAGMA user_version = 3;
            CREATE TABLE food_cache (
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
                alternatives_json TEXT
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
            CREATE TABLE food_aliases (
                phrase TEXT NOT NULL,
                normalized_phrase TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL COLLATE NOCASE
            );
            INSERT INTO food_cache VALUES
                ('v3 oats', 71, 2.54, 1.52, 12, NULL, NULL, 'usda', 173904,
                 NULL, NULL, 'v3 oats', '[]');
            INSERT INTO log_entries VALUES
                (3, '2026-07-20T12:00:00+00:00', 'food', 'v3 meal',
                 '[{"name":"v3 oats"}]', 71, 2.54, 1.52, 12);
            INSERT INTO recipes VALUES
                (2, 'V3 oats', 'https://example.test/v3-oats', 1,
                 '[{"name":"v3 oats"}]', 71, 2.54, 1.52, 12,
                 '2026-07-20T11:00:00+00:00');
            INSERT INTO food_aliases VALUES ('my oats', 'my oats', 'v3 oats');
            """
        )
    return database


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
        row = connection.execute(
            """SELECT name, kcal, protein, fat, carbs, piece_grams, density_g_ml,
            source, fdc_id, barcode, brand, lookup_query, alternatives_json,
            piece_grams_source, piece_grams_source_value, resolution_mode, source_id,
            source_note, provenance, assumption FROM food_cache"""
        ).fetchone()
        assert tuple(row) == (
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
            None,
            None,
            "legacy",
            "173904",
            None,
            "legacy cache",
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
        assert "food_aliases" in {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(food_cache)")
        }
        assert {
            "resolution_mode",
            "source_id",
            "source_note",
            "provenance",
            "assumption",
        } <= columns


def test_connect_migrates_v3_to_v4_preserving_all_user_records(v3_database):
    with connect(v3_database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        row = connection.execute(
            """SELECT name, source, fdc_id, resolution_mode, source_id,
            source_note, provenance, assumption FROM food_cache"""
        ).fetchone()
        assert tuple(row) == (
            "v3 oats",
            "usda",
            173904,
            "legacy",
            "173904",
            None,
            "usda",
            None,
        )
        assert connection.execute("SELECT count(*) FROM log_entries").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM recipes").fetchone()[0] == 1
        assert tuple(connection.execute("SELECT * FROM food_aliases").fetchone()) == (
            "my oats",
            "my oats",
            "v3 oats",
        )


def test_connect_migrates_v2_to_latest_without_losing_user_data(v2_database):
    with connect(v2_database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
        row = connection.execute(
            """SELECT name, kcal, protein, fat, carbs, piece_grams, density_g_ml,
            source, fdc_id, barcode, brand, lookup_query, alternatives_json,
            piece_grams_source, piece_grams_source_value, resolution_mode, source_id,
            source_note, provenance, assumption FROM food_cache"""
        ).fetchone()
        assert tuple(row) == (
            "v2 egg",
            155.0,
            12.58,
            10.61,
            1.12,
            50.0,
            None,
            "user",
            None,
            None,
            "Fixture",
            "v2 egg fixture",
            "[]",
            None,
            None,
            "legacy",
            None,
            None,
            "user",
            None,
        )
        assert tuple(connection.execute("SELECT * FROM log_entries").fetchone()) == (
            9,
            "2026-07-19T12:00:00+00:00",
            "food",
            "v2 lunch",
            '[{"name":"v2 egg"}]',
            155.0,
            12.58,
            10.61,
            1.12,
        )
        assert tuple(connection.execute("SELECT * FROM recipes").fetchone()) == (
            4,
            "V2 eggs",
            "https://example.test/v2-eggs",
            2.0,
            '[{"name":"v2 egg"}]',
            77.5,
            6.29,
            5.305,
            0.56,
            "2026-07-19T11:00:00+00:00",
        )
        assert connection.execute("SELECT count(*) FROM food_aliases").fetchone()[0] == 0

    with connect(v2_database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
        assert connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM log_entries").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM recipes").fetchone()[0] == 1


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
