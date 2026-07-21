from __future__ import annotations

from dataclasses import replace

import pytest
import requests

from nomnomcli.config import ProviderConfig
from nomnomcli.db import connect
from nomnomcli.errors import NomnomError
from nomnomcli.foods import FoodRepository
from nomnomcli.models import Food
from nomnomcli.parser import parse_free_text


def _usda_generic_response(description="Chicken breast, roasted", *, branded=False):
    class Response:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "foods": [
                    {
                        "fdcId": 171477,
                        "description": description,
                        "dataType": "Branded" if branded else "Foundation",
                        "brandOwner": "Acme" if branded else None,
                        "foodCategory": "Poultry Products",
                        "foodNutrients": [
                            {
                                "nutrientId": 1008,
                                "nutrientName": "Energy",
                                "unitName": "KCAL",
                                "value": 165,
                            },
                            {
                                "nutrientId": 1003,
                                "nutrientName": "Protein",
                                "unitName": "G",
                                "value": 31,
                            },
                            {
                                "nutrientId": 1004,
                                "nutrientName": "Total lipid (fat)",
                                "unitName": "G",
                                "value": 3.6,
                            },
                            {
                                "nutrientId": 1005,
                                "nutrientName": "Carbohydrate, by difference",
                                "unitName": "G",
                                "value": 1,
                            },
                        ],
                    }
                ]
            }

    return Response()


def _off_candidate(
    name: str,
    *,
    brand: str | None,
    barcode: str,
    categories: tuple[str, ...],
) -> Food:
    return Food(
        name,
        200,
        20,
        5,
        10,
        source="openfoodfacts",
        barcode=barcode,
        brand=brand,
        categories=categories,
        source_id=barcode,
        provenance="openfoodfacts",
    )


@pytest.mark.parametrize(
    ("query", "candidate"),
    [
        (
            "soy protein isolate",
            _off_candidate(
                "Soy Protein Isolate 2.0 — HSN, HSN Essentials",
                brand="HSN, HSN Essentials",
                barcode="8435611324100",
                categories=("en:soy-protein-isolates",),
            ),
        ),
        (
            "cream cheese",
            _off_candidate(
                "cream-cheese — Cream cheese",
                brand="Cream cheese",
                barcode="8000000000024",
                categories=("en:cream-cheeses",),
            ),
        ),
        (
            "peanuts",
            _off_candidate(
                "Menguy's Peanut 100%",
                brand="Menguy's",
                barcode="3336970205050",
                categories=("en:peanuts",),
            ),
        ),
    ],
)
def test_unbranded_reported_off_matches_are_never_arbitrary_exact_products(
    repository, monkeypatch, query, candidate
):
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [candidate])

    food, confidence = repository.resolve(query)

    assert confidence >= 0.5
    assert food.resolution_mode == "generic_proxy"
    assert food.source == "openfoodfacts"
    assert food.brand == candidate.brand
    assert food.barcode == candidate.barcode
    assert food.assumption is not None
    assert candidate.brand in food.assumption
    assert candidate.barcode in food.assumption
    assert "Open Food Facts" in food.assumption


def test_unsafe_branded_off_match_needs_source_without_cache(repository, monkeypatch):
    candidate = _off_candidate(
        "Original spread — Cream Cheese",
        brand="Cream Cheese",
        barcode="8000000000093",
        categories=("en:cream-cheeses",),
    )
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [candidate])

    with pytest.raises(NomnomError) as caught:
        repository.resolve("cream cheese")

    assert caught.value.code == "food_needs_source"
    assert caught.value.details["candidate"]["brand"] == "Cream Cheese"
    assert caught.value.details["candidate"]["barcode"] == "8000000000093"
    assert repository.user_connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 0


def test_branded_off_proxy_requires_category_type_evidence(repository, monkeypatch):
    candidate = _off_candidate(
        "Soy protein isolate — Example Sports",
        brand="Example Sports",
        barcode="8435611324100",
        categories=(),
    )
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [candidate])

    with pytest.raises(NomnomError) as caught:
        repository.resolve("soy protein isolate")

    assert caught.value.code == "food_needs_source"
    assert caught.value.details["provider_error"]["code"] == "off_low_confidence"
    assert repository.user_connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 0


def test_default_unbranded_usda_fallback_is_explicit_generic_proxy(
    repository, monkeypatch
):
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.delenv("NOMNOM_GENERIC_PROXY_POLICY", raising=False)
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _usda_generic_response())

    food, confidence = repository.resolve("chicken breast roasted")

    assert confidence >= 0.8
    assert food.name == "chicken breast, roasted"
    assert food.source == "usda"
    assert food.source_id == "171477"
    assert food.resolution_mode == "generic_proxy"
    assert food.assumption == (
        "Brand not specified; used USDA generic proxy: chicken breast, roasted."
    )
    row = repository.user_connection.execute(
        """SELECT resolution_mode, source_id, provenance, assumption
        FROM food_cache WHERE name = ?""",
        (food.name,),
    ).fetchone()
    assert tuple(row) == (
        "generic_proxy",
        "171477",
        "usda",
        "Brand not specified; used USDA generic proxy: chicken breast, roasted.",
    )


@pytest.mark.parametrize(
    ("policy", "error_code"),
    [
        ("ask", "generic_proxy_confirmation_required"),
        ("exact_only", "exact_resolution_required"),
    ],
)
def test_generic_proxy_policy_returns_structured_candidate_without_writes(
    user_db, monkeypatch, tmp_path, policy, error_code
):
    config_path = tmp_path / f"{policy}.toml"
    config_path.write_text(
        f'[resolution]\ngeneric_proxy_policy = "{policy}"\n', encoding="utf-8"
    )
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _usda_generic_response())

    with connect(user_db) as connection:
        repository = FoodRepository(
            connection,
            provider_config=ProviderConfig(
                environ={"NOMNOM_USDA_KEY": "test-key"}, config_path=config_path
            ),
        )
        with pytest.raises(NomnomError) as caught:
            repository.resolve("chicken breast roasted")

        assert caught.value.code == error_code
        assert caught.value.details["candidate"] == {
            "name": "chicken breast, roasted",
            "source": "usda",
            "source_id": "171477",
            "resolution_mode": "generic_proxy",
            "confidence": pytest.approx(caught.value.details["candidate"]["confidence"]),
        }
        assert caught.value.details["candidate"]["confidence"] >= 0.8
        assert connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 0


@pytest.mark.parametrize(
    "query", ["Acme chicken breast roasted", "chicken breast roasted 12345"]
)
def test_brand_or_sku_token_denies_usda_generic_fallback_even_when_policy_allows(
    repository, monkeypatch, query
):
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.setenv("NOMNOM_GENERIC_PROXY_POLICY", "allow_for_unbranded")
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _usda_generic_response())

    with pytest.raises(NomnomError) as caught:
        repository.resolve(query)

    assert caught.value.code == "exact_resolution_required"
    assert "barcode" in caught.value.details["action"].casefold()
    assert "photo" in caught.value.details["action"].casefold()
    assert repository.user_connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 0


def test_usda_branded_record_is_never_a_generic_proxy(repository, monkeypatch):
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: _usda_generic_response(branded=True),
    )

    with pytest.raises(NomnomError) as caught:
        repository.resolve("chicken breast roasted")

    assert caught.value.code == "exact_resolution_required"
    assert repository.user_connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 0


def test_cached_generic_proxy_is_not_reused_for_later_branded_query(
    repository, monkeypatch
):
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _usda_generic_response())
    repository.resolve("chicken breast roasted")

    with pytest.raises(NomnomError) as caught:
        repository.resolve("Acme chicken breast roasted")

    assert caught.value.code == "exact_resolution_required"
    assert repository.user_connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 1


def test_cached_branded_generic_proxy_cannot_satisfy_later_brand_query(
    repository, monkeypatch
):
    candidate = _off_candidate(
        "Menguy's Peanut 100%",
        brand="Menguy's",
        barcode="3336970205050",
        categories=("en:peanuts",),
    )
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [candidate])
    proxy, _ = repository.resolve("peanuts")
    assert proxy.resolution_mode == "generic_proxy"

    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [])
    with pytest.raises(NomnomError) as caught:
        repository.resolve(candidate.name)

    assert caught.value.code == "food_needs_source"
    assert repository.user_connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 1


def test_old_arbitrary_exact_off_cache_cannot_replay_for_unbranded_lookup(
    repository, monkeypatch
):
    candidate = _off_candidate(
        "Menguy's Peanut 100%",
        brand="Menguy's",
        barcode="3336970205050",
        categories=("en:peanuts",),
    )
    repository._cache_food(
        replace(candidate, resolution_mode="exact_product"),
        lookup_query="peanuts",
    )
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [candidate])

    food, _ = repository.resolve("peanuts")

    assert food.resolution_mode == "generic_proxy"
    row = repository.user_connection.execute(
        "SELECT resolution_mode FROM food_cache WHERE barcode = ?", (candidate.barcode,)
    ).fetchone()
    assert row["resolution_mode"] == "generic_proxy"


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

    urls = []

    def get(url, *args, **kwargs):
        urls.append(url)
        return Response()

    monkeypatch.delenv("NOMNOM_USDA_KEY", raising=False)
    monkeypatch.setattr(requests, "get", get)

    with pytest.raises(NomnomError) as caught:
        repository.resolve("кедровые орехи")

    assert caught.value.code == "food_needs_source"
    assert caught.value.details["provider_error"]["code"] == "off_low_confidence"
    assert caught.value.details["candidate"]["name"] == "Cheese — Wrong Match"
    assert caught.value.details["alternatives"] == []
    assert set(caught.value.details["source_options"]) == {
        "photo",
        "barcode",
        "capture_label",
        "local_cache",
    }
    assert caught.value.details["optional_usda_enhancement"] == {
        "optional": True,
        "command": "nomnom setup",
        "purpose": "broader no-photo raw/generic food coverage",
        "signup_url": "https://fdc.nal.usda.gov/api-key-signup.html",
    }
    assert urls == ["https://world.openfoodfacts.org/cgi/search.pl"]
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

    assert caught.value.code == "food_needs_source"
    assert caught.value.details["provider_error"]["code"] == "off_low_confidence"
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


def test_unbranded_high_confidence_off_type_is_cached_as_truthful_generic_proxy(
    repository, monkeypatch
):
    candidate = Food(
        "Chickpeas, cooked",
        164,
        8.9,
        2.6,
        27.4,
        source="openfoodfacts",
        barcode="12345678",
        categories=("en:chickpeas",),
        source_id="12345678",
        provenance="openfoodfacts",
    )
    monkeypatch.setenv("NOMNOM_GENERIC_PROXY_POLICY", "allow_for_unbranded")
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [candidate])

    food, confidence = repository.resolve("chickpeas cooked")

    assert confidence == 1.0
    assert food.name == "Chickpeas, cooked"
    assert food.brand is None
    assert food.resolution_mode == "generic_proxy"
    assert food.source_id == "12345678"
    assert food.provenance == "openfoodfacts"
    assert food.assumption == (
        "Brand not specified; used Open Food Facts generic proxy: Chickpeas, cooked."
    )
    row = repository.user_connection.execute(
        """SELECT resolution_mode, source_id, provenance, assumption
        FROM food_cache WHERE name = ?""",
        (food.name,),
    ).fetchone()
    assert tuple(row) == (
        "generic_proxy",
        "12345678",
        "openfoodfacts",
        "Brand not specified; used Open Food Facts generic proxy: Chickpeas, cooked.",
    )


def test_high_confidence_off_without_source_identity_is_not_cached(repository, monkeypatch):
    candidate = Food(
        "Chickpeas, cooked",
        164,
        8.9,
        2.6,
        27.4,
        source="openfoodfacts",
        categories=("en:chickpeas",),
    )
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [candidate])

    with pytest.raises(NomnomError) as caught:
        repository.resolve("chickpeas cooked")

    assert caught.value.code == "food_needs_source"
    assert caught.value.details["provider_error"]["code"] == "off_source_identity_missing"
    assert repository.user_connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 0


@pytest.mark.parametrize("query", ["Acme chickpeas", "chickpeas 12345"])
def test_brand_or_sku_query_never_uses_unbranded_off_proxy(repository, monkeypatch, query):
    candidate = Food(
        "Chickpeas",
        164,
        8.9,
        2.6,
        27.4,
        source="openfoodfacts",
        barcode="12345678",
        categories=("en:chickpeas",),
        source_id="12345678",
        provenance="openfoodfacts",
    )
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [candidate])

    with pytest.raises(NomnomError) as caught:
        repository.resolve(query)

    assert caught.value.code == "food_needs_source"
    assert caught.value.details["provider_error"]["code"] == "off_low_confidence"
    assert repository.user_connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 0


def test_named_sku_can_resolve_only_to_matching_exact_off_product(repository, monkeypatch):
    candidate = Food(
        "Acme Chickpeas 12345",
        164,
        8.9,
        2.6,
        27.4,
        source="openfoodfacts",
        barcode="12345678",
        brand="Acme",
        categories=("en:chickpeas",),
        source_id="12345678",
        provenance="openfoodfacts",
    )
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [candidate])

    food, confidence = repository.resolve("Acme chickpeas 12345")

    assert confidence == 1.0
    assert food.name == "Acme Chickpeas 12345"
    assert food.resolution_mode == "exact_product"
    assert food.source_id == "12345678"


@pytest.mark.parametrize(
    ("policy", "error_code"),
    [("ask", "generic_proxy_confirmation_required"), ("exact_only", "exact_resolution_required")],
)
def test_unbranded_off_proxy_honors_policy_with_off_provenance(
    repository, monkeypatch, policy, error_code
):
    candidate = _off_candidate(
        "Chickpeas, cooked — Acme",
        brand="Acme",
        barcode="12345678",
        categories=("en:chickpeas",),
    )
    monkeypatch.setenv("NOMNOM_GENERIC_PROXY_POLICY", policy)
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [candidate])

    with pytest.raises(NomnomError) as caught:
        repository.resolve("chickpeas cooked")

    assert caught.value.code == error_code
    assert caught.value.details["candidate"] == {
        "name": "Chickpeas, cooked — Acme",
        "source": "openfoodfacts",
        "source_id": "12345678",
        "resolution_mode": "generic_proxy",
        "confidence": 1.0,
        "brand": "Acme",
        "barcode": "12345678",
        "assumption": (
            "Brand not specified; used Open Food Facts generic proxy from candidate "
            "Chickpeas, cooked — Acme (brand: Acme; barcode: 12345678)."
        ),
    }
    assert repository.user_connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 0


def test_configured_usda_generic_beats_safe_branded_off_proxy(repository, monkeypatch):
    off_candidate = _off_candidate(
        "Menguy's Peanut 100%",
        brand="Menguy's",
        barcode="3336970205050",
        categories=("en:peanuts",),
    )
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [off_candidate])
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: _usda_generic_response("Peanuts, raw"),
    )

    food, _ = repository.resolve("peanuts")

    assert food.source == "usda"
    assert food.resolution_mode == "generic_proxy"
    assert food.brand is None


def test_safe_off_generic_survives_invalid_configured_usda_result(
    repository, monkeypatch
):
    off_candidate = _off_candidate(
        "Peanuts — Example Foods",
        brand="Example Foods",
        barcode="10000006",
        categories=("en:peanuts",),
    )
    invalid_usda = Food(
        "Peanuts — USDA Brand",
        210,
        21,
        6,
        11,
        source="usda",
        fdc_id=999001,
        brand="USDA Brand",
        provider_data_type="Branded",
    )
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [off_candidate])
    monkeypatch.setattr(
        repository.usda_client,
        "resolve",
        lambda *args, **kwargs: (invalid_usda, 0.99),
    )

    food, confidence = repository.resolve("peanuts")

    assert confidence >= 0.5
    assert food.source == "openfoodfacts"
    assert food.source_id == "10000006"
    assert food.resolution_mode == "generic_proxy"
    assert food.assumption is not None


def test_invalid_off_is_not_rescued_by_invalid_configured_usda_result(
    repository, monkeypatch
):
    invalid_off = _off_candidate(
        "Chocolate spread — Example Foods",
        brand="Example Foods",
        barcode="10000007",
        categories=("en:chocolate-spreads",),
    )
    invalid_usda = Food(
        "Peanuts — USDA Brand",
        210,
        21,
        6,
        11,
        source="usda",
        fdc_id=999001,
        brand="USDA Brand",
        provider_data_type="Branded",
    )
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [invalid_off])
    monkeypatch.setattr(
        repository.usda_client,
        "resolve",
        lambda *args, **kwargs: (invalid_usda, 0.99),
    )

    with pytest.raises(NomnomError) as caught:
        repository.resolve("peanuts")

    assert caught.value.code == "exact_resolution_required"
    assert repository.user_connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("literal", "candidate"),
    [
        (
            "milk 3% 625 ml",
            _off_candidate(
                "Milk 3% — Example Dairy",
                brand="Example Dairy",
                barcode="10000001",
                categories=("en:milks",),
            ),
        ),
        (
            "soy protein isolate 30 g",
            _off_candidate(
                "Soy protein isolate — Example Sports",
                brand="Example Sports",
                barcode="10000002",
                categories=("en:soy-protein-isolates",),
            ),
        ),
        (
            "chicken pastrami 150 g",
            _off_candidate(
                "Chicken pastrami — Example Deli",
                brand="Example Deli",
                barcode="10000003",
                categories=("en:chicken-pastrami",),
            ),
        ),
        (
            "whole wheat bread 140 g",
            _off_candidate(
                "Whole wheat bread — Example Bakery",
                brand="Example Bakery",
                barcode="10000004",
                categories=("en:whole-wheat-breads",),
            ),
        ),
        (
            "cream cheese 40 g",
            _off_candidate(
                "Cream cheese — Example Dairy",
                brand="Example Dairy",
                barcode="10000005",
                categories=("en:cream-cheeses",),
            ),
        ),
        (
            "peanuts 55 g",
            _off_candidate(
                "Peanuts — Example Foods",
                brand="Example Foods",
                barcode="10000006",
                categories=("en:peanuts",),
            ),
        ),
    ],
)
def test_literal_translated_unbranded_components_are_explicit_generic_proxies(
    repository, monkeypatch, literal, candidate
):
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [candidate])

    item = parse_free_text(literal, repository)[0].to_dict()

    assert item["resolution_mode"] == "generic_proxy"
    assert item["source"] == "openfoodfacts"
    assert item["brand"] == candidate.brand
    assert item["barcode"] == candidate.barcode
    assert "Open Food Facts" in item["assumption"]


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

    assert caught.value.code == "food_needs_source"
    assert caught.value.details["provider_error"]["code"] == "off_low_confidence"
    assert caught.value.details["candidate"]["confidence"] == 0


def test_missing_usda_key_returns_safe_source_options_with_optional_enhancement(
    repository, monkeypatch
):
    monkeypatch.delenv("NOMNOM_USDA_KEY", raising=False)
    monkeypatch.delenv("NOMNOM_OFFLINE", raising=False)
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [])

    with pytest.raises(NomnomError) as caught:
        repository.resolve("chickpeas cooked")

    assert caught.value.code == "food_needs_source"
    assert "USDA" not in caught.value.message
    assert caught.value.details["provider_error"] is None
    assert "photo" in caught.value.details["source_options"]
    assert "barcode" in caught.value.details["source_options"]
    assert "capture_label" in caught.value.details["source_options"]
    assert caught.value.details["optional_usda_enhancement"]["optional"] is True


def test_offline_not_found(repository, monkeypatch):
    monkeypatch.delenv("NOMNOM_USDA_KEY", raising=False)
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    with pytest.raises(NomnomError) as caught:
        repository.resolve("definitely not a food")
    assert caught.value.code == "food_needs_source"
    assert caught.value.details["offline"] is True


def test_usda_fallback_is_cached_with_runtime_source_and_fdc_id(
    repository, monkeypatch, food_fixtures
):
    class Response:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {"foods": [food_fixtures["usda"]]}

    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    food, confidence = repository.resolve("chickpeas cooked")
    assert food.kcal == 164
    assert round(confidence, 2) == 0.98
    assert food.fdc_id == 175200
    assert food.piece_grams == 130
    row = repository.user_connection.execute(
        """SELECT source, fdc_id, piece_grams_source, piece_grams_source_value
        FROM food_cache WHERE name = 'chickpeas, cooked'"""
    ).fetchone()
    assert tuple(row) == ("usda", 175200, "servingSize", "130 g")


def test_usda_fallback_replaces_low_confidence_off_candidate(
    repository, monkeypatch, food_fixtures
):
    class Response:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            if "openfoodfacts.org" in self.url:
                return {"products": [food_fixtures["off"]["cheese"]]}
            return {"foods": [food_fixtures["usda"]]}

    def get(url, *args, **kwargs):
        response = Response()
        response.url = url
        return response

    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setattr(requests, "get", get)

    food, confidence = repository.resolve("chickpeas cooked")

    assert food.source == "usda"
    assert food.fdc_id == 175200
    assert round(confidence, 2) == 0.98


def test_usda_no_result_is_structured_and_actionable(repository, monkeypatch):
    class Response:
        status_code = 200
        headers = {}

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
    assert food.name == "Seeded Bread — Acme"
    assert confidence == 1.0
    assert food.alternatives == (
        {"name": "Whole Grain Bread — Acme", "brand": "Acme", "barcode": "1"},
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
        resolution_mode="exact_product",
        source_id="42",
        provenance="openfoodfacts",
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


def test_user_alias_crud_normalizes_phrase_and_requires_exact_cached_target(repository):
    target = repository.add_food(
        name="Яйцо",
        brand="Ферма",
        kcal=155,
        protein=12.58,
        fat=10.61,
        carbs=1.12,
        piece_grams=50,
    )

    added = repository.add_alias("  Яйцо   варёное  ", target.name.lower())
    assert added == {
        "phrase": "Яйцо варёное",
        "canonical_food_name": "Яйцо — Ферма",
    }
    assert repository.list_aliases() == [added]

    with pytest.raises(NomnomError) as duplicate:
        repository.add_alias("яйцо вареное", target.name)
    assert duplicate.value.code == "alias_exists"

    removed = repository.remove_alias("ЯЙЦО ВАРЕНОЕ")
    assert removed == added
    assert repository.list_aliases() == []

    with pytest.raises(NomnomError) as missing:
        repository.remove_alias("яйцо варёное")
    assert missing.value.code == "alias_not_found"


def test_alias_target_must_be_exact_local_cache_name(repository, monkeypatch):
    repository.add_food(
        name="egg",
        brand="Fixture",
        kcal=155,
        protein=12.58,
        fat=10.61,
        carbs=1.12,
        piece_grams=50,
    )
    monkeypatch.setattr(
        repository.off_client,
        "search",
        lambda *args, **kwargs: pytest.fail("alias creation must stay local"),
    )

    with pytest.raises(NomnomError) as caught:
        repository.add_alias("яйцо", "egg")

    assert caught.value.code == "alias_target_not_found"


def test_alias_precedes_exact_cache_but_only_for_the_exact_phrase(repository):
    shadowed = repository.add_food(
        name="breakfast",
        brand="Cache",
        kcal=100,
        protein=2,
        fat=2,
        carbs=18,
    )
    target = repository.add_food(
        name="egg",
        brand="Target",
        kcal=155,
        protein=12.58,
        fat=10.61,
        carbs=1.12,
        piece_grams=50,
    )
    repository.add_alias(shadowed.name, target.name)

    aliased, confidence = repository.resolve(shadowed.name, allow_remote=False)
    longer, longer_confidence = repository.resolve(
        f"{shadowed.name} bowl", allow_remote=False
    )

    assert aliased == target
    assert confidence == 1.0
    assert longer == shadowed
    assert longer_confidence == 0.85


def test_dangling_alias_fails_without_remote_fallback(repository, monkeypatch):
    target = repository.add_food(
        name="egg",
        brand="Fixture",
        kcal=155,
        protein=12.58,
        fat=10.61,
        carbs=1.12,
    )
    repository.add_alias("яйцо", target.name)
    repository.user_connection.execute(
        "DELETE FROM food_cache WHERE name = ?", (target.name,)
    )
    monkeypatch.setattr(
        repository.off_client,
        "search",
        lambda *args, **kwargs: pytest.fail("dangling aliases must not use remote lookup"),
    )

    with pytest.raises(NomnomError) as caught:
        repository.resolve("яйцо")

    assert caught.value.code == "alias_target_not_found"
    assert caught.value.details["canonical_food_name"] == target.name


def test_barcode_recapture_failure_rolls_back_alias_retargeting(repository, monkeypatch):
    barcode = "0123456789012"
    old = Food(
        "Old Fixture Bar — Acme",
        250,
        9,
        4,
        45,
        source="openfoodfacts",
        barcode=barcode,
        brand="Acme",
        resolution_mode="exact_product",
        source_id=barcode,
        provenance="openfoodfacts",
    )
    unrelated = repository.add_food(
        name="Unrelated Fixture",
        brand="Other",
        kcal=90,
        protein=2,
        fat=1,
        carbs=18,
    )
    repository._cache_food(old, lookup_query=old.name)
    repository.add_alias("fixture favorite", old.name)
    repository.add_alias("other favorite", unrelated.name)
    original_aliases = repository.list_aliases()

    monkeypatch.setattr(
        repository.off_client,
        "product_by_barcode",
        lambda code: replace(old, name="Current Fixture Bar — Acme", kcal=180),
    )

    def fail_cache(*args, **kwargs):
        raise RuntimeError("forced cache failure")

    monkeypatch.setattr(repository, "_cache_food", fail_cache)

    with pytest.raises(RuntimeError, match="forced cache failure"):
        repository.capture_barcode(barcode)

    assert repository.list_aliases() == original_aliases
    assert repository.resolve("fixture favorite", allow_remote=False) == (old, 1.0)
    assert repository.resolve("other favorite", allow_remote=False) == (unrelated, 1.0)
