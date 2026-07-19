from __future__ import annotations

import json

import requests

from nomnomcli.cli import main
from nomnomcli.db import connect
from nomnomcli.errors import NomnomError
from nomnomcli.models import Food
from nomnomcli.off import OpenFoodFactsClient


def test_cli_mocked_off_egg_dish_uses_runtime_serving_weight(
    user_db, monkeypatch, capsys, food_fixtures
):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"products": [food_fixtures["off"]["egg"]]}

    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())

    code = main(["log", "--parse", "яичница из 3 небольших яиц", "--json"])
    result = json.loads(capsys.readouterr().out)

    assert code == 0
    assert result["items"][0]["grams"] == 150
    assert result["items"][0]["source"] == "openfoodfacts"


def test_cli_mocked_cheese_for_pine_nuts_is_low_confidence_without_writes(
    user_db, monkeypatch, capsys, food_fixtures
):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"products": [food_fixtures["off"]["cheese"]]}

    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())

    code = main(["log", "--parse", "кедровые орехи 30 г", "--json"])
    captured = capsys.readouterr()
    error = json.loads(captured.err)

    assert code == 2
    assert captured.out == ""
    assert error["error"]["code"] == "off_low_confidence"
    assert error["error"]["candidate"]["name"] == "Cheese — Wrong Match"
    assert error["error"]["alternatives"] == []
    assert error["error"]["details"]["candidate"]["name"] == "Cheese — Wrong Match"
    assert "alternatives" in error["error"]["details"]
    with connect(user_db) as connection:
        assert connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM log_entries").fetchone()[0] == 0


def test_cli_no_usda_key_is_actionable_json_error(user_db, monkeypatch, capsys):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"products": []}

    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.delenv("NOMNOM_USDA_KEY", raising=False)
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())

    code = main(["log", "--food", "chickpeas cooked", "--grams", "100", "--json"])
    captured = capsys.readouterr()
    error = json.loads(captured.err)

    assert code == 2
    assert captured.out == ""
    assert error["error"]["code"] == "usda_key_required"
    assert error["error"]["setup"] == (
        "Get a free key at https://fdc.nal.usda.gov/api-key-signup.html then: "
        "export NOMNOM_USDA_KEY=..."
    )
    assert error["error"]["details"]["setup_url"] == (
        "https://fdc.nal.usda.gov/api-key-signup.html"
    )


def test_cli_log_and_stats_json(seeded_user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(seeded_user_db))
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
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
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


def test_cli_search_json(seeded_user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(seeded_user_db))
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


def test_cli_json_and_text_surface_size_assumptions(
    seeded_user_db, monkeypatch, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(seeded_user_db))
    phrase = "омлет из 2 small eggs, половины небольшого томата"

    code = main(["log", "--parse", phrase, "--json"])
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result["assumptions"] == [
        "2 small eggs = 100g",
        "1/2 small томата = 50g",
    ]
    assert all(item["assumed"] is True for item in result["items"])

    code = main(["log", "--parse", phrase])
    output = capsys.readouterr().out
    assert code == 0
    assert "Assumptions:" in output
    assert "2 small eggs = 100g" in output


def test_cli_add_pins_branded_product_for_offline_piece_lookup(
    user_db, monkeypatch, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    code = main(
        [
            "add",
            "--name",
            "хлеб",
            "--brand",
            "harry's",
            "--kcal",
            "250",
            "--protein",
            "9",
            "--fat",
            "4",
            "--carbs",
            "45",
            "--piece-grams",
            "40",
            "--json",
        ]
    )
    added = json.loads(capsys.readouterr().out)
    assert code == 0
    assert added["source"] == "user"
    assert added["piece_grams"] == 40

    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    code = main(["log", "--parse", "хлеб harry's 2 куска", "--json"])
    logged = json.loads(capsys.readouterr().out)
    assert code == 0
    assert logged["items"][0]["grams"] == 80
    assert logged["items"][0]["name"] == "хлеб — harry's"


def test_cli_add_rejects_invalid_nutrition(user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    code = main(
        [
            "add",
            "--name",
            "test",
            "--brand",
            "brand",
            "--kcal",
            "-1",
            "--protein",
            "0",
            "--fat",
            "0",
            "--carbs",
            "0",
            "--json",
        ]
    )
    error = json.loads(capsys.readouterr().err)
    assert code == 2
    assert error["error"]["code"] == "invalid_nutrition"


def test_exact_issue_phrase_with_pinned_brand(seeded_user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(seeded_user_db))
    assert (
        main(
            [
                "add",
                "--name",
                "harry's sandwich bread",
                "--brand",
                "Harry's",
                "--kcal",
                "265",
                "--protein",
                "8",
                "--fat",
                "3.2",
                "--carbs",
                "49",
                "--piece-grams",
                "40",
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    phrase = (
        "яичница из 3 небольших яиц, половины небольшого томата и половины средней "
        "луковицы, хлеб harry's 2 куска по 40г"
    )
    assert main(["log", "--parse", phrase, "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert [item["grams"] for item in result["items"]] == [150, 50, 40, 80]
    assert result["items"][3]["name"] == "harry's sandwich bread — Harry's"
    assert result["items"][3]["source"] == "user"
    assert all(
        not item["name"].startswith("oil,") and not item["name"].endswith(" oil")
        for item in result["items"]
    )
    assert result["assumptions"] == [
        "3 small яиц = 150g",
        "1/2 small томата = 50g",
        "1/2 medium луковицы = 40g",
    ]


def test_cli_off_alternatives_are_additive_json(user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    matches = [
        Food(
            "Acme Bread",
            250,
            9,
            4,
            45,
            source="openfoodfacts",
            barcode="1",
            brand="Acme",
        ),
        Food(
            "Acme Seeded Bread",
            240,
            10,
            5,
            40,
            source="openfoodfacts",
            barcode="2",
            brand="Acme",
        ),
    ]
    monkeypatch.setattr(OpenFoodFactsClient, "search", lambda *args, **kwargs: matches)
    assert main(["log", "--parse", "Acme bread 100 г", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["items"][0]["source"] == "openfoodfacts"
    assert result["items"][0]["barcode"] == "1"
    assert result["items"][0]["alternatives"] == [
        {"name": "Acme Seeded Bread", "brand": "Acme", "barcode": "2"}
    ]


def test_cli_off_failure_is_clear_error_json(user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))

    def unavailable(*args, **kwargs):
        raise NomnomError(
            "openfoodfacts_unavailable",
            "Open Food Facts lookup is unavailable",
            details={"status": 503, "offline_escape": "nomnom add --name NAME ..."},
        )

    monkeypatch.setattr(OpenFoodFactsClient, "search", unavailable)
    assert main(["log", "--parse", "Acme missing 100 г", "--json"]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "openfoodfacts_unavailable"
    assert error["error"]["details"]["status"] == 503
    assert "nomnom add" in error["error"]["details"]["offline_escape"]
