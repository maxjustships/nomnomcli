from __future__ import annotations

import json
import sqlite3

import pytest
import requests

from nomnomcli.errors import NomnomError
from nomnomcli.models import Food


def test_russian_synonym_resolution(repository):
    food, confidence = repository.resolve("творог")
    assert food.name == "cottage cheese, 4% milkfat"
    assert confidence == 0.98


def test_yo_normalization(repository):
    first, _ = repository.resolve("мед")
    second, _ = repository.resolve("мёд")
    assert first == second


def test_search_russian_query(repository):
    results = repository.search("гречка")
    assert results[0].name == "buckwheat groats, roasted, cooked"
    assert results[0].kcal == 92


def test_offline_not_found(repository, monkeypatch):
    monkeypatch.delenv("NOMNOM_USDA_KEY", raising=False)
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    with pytest.raises(NomnomError) as caught:
        repository.resolve("definitely not a food")
    assert caught.value.details["offline"] is True


def test_usda_fallback_is_cached(repository, monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "foods": [
                    {
                        "fdcId": 42,
                        "description": "Test food",
                        "foodNutrients": [
                            {
                                "nutrientName": "Energy",
                                "nutrientNumber": "208",
                                "unitName": "KCAL",
                                "value": 123,
                            },
                            {"nutrientName": "Protein", "value": 4},
                            {"nutrientName": "Total lipid (fat)", "value": 5},
                            {"nutrientName": "Carbohydrate, by difference", "value": 6},
                        ],
                    }
                ]
            }

    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    food, confidence = repository.resolve("remote test food")
    assert (food.kcal, confidence) == (123, 0.72)
    row = repository.user_connection.execute(
        "SELECT source FROM food_cache WHERE name = 'test food'"
    ).fetchone()
    assert row[0] == "USDA FDC API"


def test_bundled_database_has_target_size(repository):
    with sqlite3.connect(repository.food_db_path) as connection:
        assert connection.execute("SELECT count(*) FROM foods").fetchone()[0] >= 300


def test_synonym_layer_has_target_size(repository):
    raw = json.loads(
        repository.food_db_path.with_name("synonyms_ru.json").read_text(encoding="utf-8")
    )
    assert len(raw) >= 200


def test_every_synonym_target_exists(repository):
    raw = json.loads(
        repository.food_db_path.with_name("synonyms_ru.json").read_text(encoding="utf-8")
    )
    with sqlite3.connect(repository.food_db_path) as connection:
        names = {row[0].casefold() for row in connection.execute("SELECT name FROM foods")}
    assert set(raw.values()) <= names


def test_off_result_is_cached_with_alternatives(repository, monkeypatch):
    calls = []
    matches = [
        Food(
            "Whole Grain Bread — Acme",
            250,
            9,
            4,
            45,
            source="openfoodfacts",
            barcode="1",
            brand="Acme",
        ),
        Food(
            "Seeded Bread — Acme",
            240,
            10,
            5,
            40,
            source="openfoodfacts",
            barcode="2",
            brand="Acme",
        ),
    ]

    def search(query, page_size=5):
        calls.append((query, page_size))
        return matches

    monkeypatch.setattr(repository.off_client, "search", search)
    food, confidence = repository.resolve("Acme bread")
    assert food.name == "Whole Grain Bread — Acme"
    assert confidence == 0.76
    assert food.alternatives == (
        {"name": "Seeded Bread — Acme", "brand": "Acme", "barcode": "2"},
    )

    monkeypatch.setattr(
        repository.off_client,
        "search",
        lambda *args, **kwargs: pytest.fail("cached lookup must not use OFF"),
    )
    cached, cached_confidence = repository.resolve("Acme bread")
    assert cached == food
    assert cached_confidence == 1.0
    assert calls == [("Acme bread", 5)]


def test_named_brand_never_substitutes_generic_food(repository, monkeypatch):
    branded = Food(
        "Acme Wheat Bread",
        260,
        10,
        4,
        46,
        source="openfoodfacts",
        barcode="42",
        brand="Acme",
    )
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [branded])
    food, _ = repository.resolve("bread Acme")
    assert food == branded
    assert food.name != "bread, wheat"


def test_query_matching_off_brand_beats_generic_top_hit(repository, monkeypatch):
    generic = Food(
        "Generic Wheat Bread",
        252,
        9,
        4,
        46,
        source="openfoodfacts",
        barcode="generic",
    )
    branded = Food(
        "Acme Wheat Bread",
        260,
        10,
        4,
        46,
        source="openfoodfacts",
        barcode="branded",
        brand="Acme",
    )
    monkeypatch.setattr(
        repository.off_client, "search", lambda *args, **kwargs: [generic, branded]
    )
    food, _ = repository.resolve("Acme bread")
    assert food.name == branded.name
    assert food.barcode == branded.barcode
    assert food.alternatives[0]["barcode"] == "generic"


def test_off_no_results_has_actionable_error(repository, monkeypatch):
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [])
    with pytest.raises(NomnomError) as caught:
        repository.resolve("Missing Brand bar")
    assert caught.value.code == "food_not_found"
    assert "nomnom add" in caught.value.details["action"]
