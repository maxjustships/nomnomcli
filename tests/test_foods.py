from __future__ import annotations

import pytest
import requests

from nomnomcli.db import connect
from nomnomcli.errors import NomnomError
from nomnomcli.foods import FoodRepository
from nomnomcli.models import Food


def test_repository_does_not_read_bundled_food_resources(user_db, monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("runtime repository must not read package food resources")

    monkeypatch.setattr("nomnomcli.foods.files", fail, raising=False)

    with connect(user_db) as connection:
        FoodRepository(connection)


def test_v02_cached_food_record_still_resolves_exactly(repository, monkeypatch):
    repository.user_connection.execute(
        """INSERT INTO food_cache
        (name, kcal, protein, fat, carbs, piece_grams, density_g_ml, source, fdc_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("legacy egg", 155, 12.6, 10.6, 1.1, 50, None, "USDA FDC API", 173424),
    )
    monkeypatch.setattr(
        repository.off_client,
        "search",
        lambda *args, **kwargs: pytest.fail("exact cache hit must not use OFF"),
    )

    food, confidence = repository.resolve("legacy egg")

    assert food.fdc_id == 173424
    assert food.piece_grams == 50
    assert confidence == 1.0


def test_cache_search_uses_token_overlap_before_off(repository, monkeypatch):
    repository.user_connection.execute(
        """INSERT INTO food_cache
        (name, kcal, protein, fat, carbs, piece_grams, density_g_ml, source, fdc_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("cooked red lentils", 116, 9, 0.4, 20, None, None, "usda", 172421),
    )
    monkeypatch.setattr(
        repository.off_client,
        "search",
        lambda *args, **kwargs: pytest.fail("cache search must run before OFF"),
    )

    food, confidence = repository.resolve("lentils cooked")

    assert food.name == "cooked red lentils"
    assert confidence >= 0.5


def test_off_low_confidence_does_not_cache_candidate(
    repository, monkeypatch, food_fixtures
):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"products": [food_fixtures["off"]["cheese"]]}

    monkeypatch.delenv("NOMNOM_USDA_KEY", raising=False)
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())

    with pytest.raises(NomnomError) as caught:
        repository.resolve("кедровые орехи")

    assert caught.value.code == "off_low_confidence"
    assert caught.value.details["candidate"]["name"] == "Cheese — Wrong Match"
    assert caught.value.details["alternatives"] == []
    assert repository.user_connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 0


def test_off_category_sanity_rejects_name_match_from_wrong_food_type(
    repository, monkeypatch, food_fixtures
):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            candidate = dict(food_fixtures["off"]["cheese"])
            candidate["product_name"] = "Кедровые орехи"
            return {"products": [candidate]}

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())

    with pytest.raises(NomnomError) as caught:
        repository.resolve("кедровые орехи")

    assert caught.value.code == "off_low_confidence"
    assert caught.value.details["candidate"]["confidence"] < 0.5


def test_off_accepts_inflected_russian_egg_with_serving_weight(
    repository, monkeypatch, food_fixtures
):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"products": [food_fixtures["off"]["egg"]]}

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())

    food, confidence = repository.resolve("яиц")

    assert food.name == "Яйца куриные — Ферма"
    assert food.piece_grams == 50
    assert confidence >= 0.5


def test_off_category_does_not_replace_name_and_brand_token_overlap(
    repository, monkeypatch, food_fixtures
):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            candidate = dict(food_fixtures["off"]["egg"])
            candidate["product_name"] = "Farm Choice"
            candidate["brands"] = "Example"
            return {"products": [candidate]}

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())

    with pytest.raises(NomnomError) as caught:
        repository.resolve("eggs")

    assert caught.value.code == "off_low_confidence"
    assert caught.value.details["candidate"]["confidence"] == 0


def test_missing_usda_key_has_exact_actionable_setup_error(repository, monkeypatch):
    setup_url = "https://fdc.nal.usda.gov/api-key-signup.html"
    monkeypatch.delenv("NOMNOM_USDA_KEY", raising=False)
    monkeypatch.delenv("NOMNOM_OFFLINE", raising=False)
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [])

    with pytest.raises(NomnomError) as caught:
        repository.resolve("chickpeas cooked")

    assert caught.value.code == "usda_key_required"
    assert caught.value.message == (
        f"USDA FoodData Central API key required. Get a free key at {setup_url}, "
        "then set NOMNOM_USDA_KEY."
    )
    assert caught.value.details["setup_url"] == setup_url


def test_offline_not_found(repository, monkeypatch):
    monkeypatch.delenv("NOMNOM_USDA_KEY", raising=False)
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    with pytest.raises(NomnomError) as caught:
        repository.resolve("definitely not a food")
    assert caught.value.details["offline"] is True


def test_usda_fallback_is_cached_with_runtime_source_and_fdc_id(
    repository, monkeypatch, food_fixtures
):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"foods": [food_fixtures["usda"]]}

    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    food, confidence = repository.resolve("chickpeas cooked")
    assert (food.kcal, confidence) == (164, 0.72)
    assert food.fdc_id == 175200
    assert food.piece_grams == 130
    row = repository.user_connection.execute(
        "SELECT source, fdc_id FROM food_cache WHERE name = 'chickpeas, cooked'"
    ).fetchone()
    assert tuple(row) == ("usda", 175200)


def test_usda_fallback_replaces_low_confidence_off_candidate(
    repository, monkeypatch, food_fixtures
):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            if "world.openfoodfacts.org" in self.url:
                return {"products": [food_fixtures["off"]["cheese"]]}
            return {"foods": [food_fixtures["usda"]]}

    def get(url, *args, **kwargs):
        response = Response()
        response.url = url
        return response

    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setattr(requests, "get", get)

    food, confidence = repository.resolve("кедровые орехи")

    assert food.source == "usda"
    assert food.fdc_id == 175200
    assert confidence == 0.72


def test_usda_no_result_is_structured_and_actionable(repository, monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"foods": []}

    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())

    with pytest.raises(NomnomError) as caught:
        repository.resolve("unlisted food")

    assert caught.value.code == "food_not_found"
    assert caught.value.details["food"] == "unlisted food"
    assert "nomnom add" in caught.value.details["action"]


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
    assert confidence == 1.0
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


def test_tokenwise_manual_brand_match_precedes_off(repository, monkeypatch):
    expected = repository.add_food(
        name="harry's sandwich bread",
        brand="Harry's",
        kcal=265,
        protein=8,
        fat=3.2,
        carbs=49,
        piece_grams=40,
    )
    monkeypatch.delenv("NOMNOM_OFFLINE", raising=False)
    monkeypatch.setattr(
        repository.off_client,
        "search",
        lambda *args, **kwargs: pytest.fail("manual brand match must not use OFF"),
    )

    food, confidence = repository.resolve("sandwich bread harry's")

    assert food == expected
    assert confidence == 0.85


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
