from __future__ import annotations

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
