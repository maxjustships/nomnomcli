from __future__ import annotations

import json

from nomnomcli.cli import main


def test_cli_log_and_stats_json(user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    code = main(["log", "--parse", "борщ 300г, хлеб 2 куска, гречка 150 г", "--json"])
    logged = json.loads(capsys.readouterr().out)
    assert code == 0
    assert logged["totals"]["kcal"] == 454.2
    assert [item["grams"] for item in logged["items"]] == [300, 60, 150]

    code = main(["stats", "today", "--json"])
    stats = json.loads(capsys.readouterr().out)
    assert code == 0
    assert stats["totals"] == logged["totals"]


def test_cli_unknown_food_json_error(user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    code = main(["log", "--parse", "неведомая штука 50 г", "--json"])
    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert code == 2
    assert captured.out == ""
    assert error["error"]["code"] == "food_not_found"


def test_cli_direct_requires_grams(user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    code = main(["log", "--food", "borscht", "--json"])
    error = json.loads(capsys.readouterr().err)
    assert code == 2
    assert error["error"]["code"] == "grams_required"


def test_cli_search_json(user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    code = main(["search", "борщ", "--json"])
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result[0] == {
        "name": "borscht",
        "kcal_per_100g": 55.0,
        "protein_per_100g": 2.5,
        "fat_per_100g": 2.1,
        "carbs_per_100g": 6.4,
    }
