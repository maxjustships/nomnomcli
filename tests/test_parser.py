from __future__ import annotations

import pytest

from nomnomcli.db import connect
from nomnomcli.errors import NomnomError
from nomnomcli.foods import FoodRepository
from nomnomcli.models import Food, total_items
from nomnomcli.parser import parse_free_text, parse_item_phrase, parse_number


def test_descriptor_weight_comes_from_resolved_food():
    class Repository:
        def resolve(self, query):
            assert query == "egg"
            return (
                Food(
                    "runtime egg",
                    155,
                    12.6,
                    10.6,
                    1.1,
                    piece_grams=52,
                    piece_grams_source="servingSize",
                    piece_grams_source_value="52 g",
                    source="usda",
                ),
                0.8,
            )

    item = parse_item_phrase("small egg", Repository())

    assert item.name == "runtime egg"
    assert item.grams == 52
    assert item.assumption == "1 small egg = 52g (source: usda.servingSize=52 g)"


def test_descriptor_without_runtime_piece_weight_asks_for_grams():
    class Repository:
        def resolve(self, query):
            return Food("runtime soup", 60, 3, 2, 8), 0.8

    with pytest.raises(NomnomError) as caught:
        parse_item_phrase("small soup", Repository())

    assert caught.value.code == "piece_weight_unknown"
    assert "provide grams" in caught.value.message


def test_descriptor_rejects_opaque_legacy_piece_weight():
    class Repository:
        def resolve(self, query):
            return Food("legacy cache record", 60, 3, 2, 8, piece_grams=64), 1.0

    with pytest.raises(NomnomError) as caught:
        parse_item_phrase("small legacy record", Repository())

    assert caught.value.code == "piece_weight_unknown"
    assert caught.value.details["reason"] == "serving_weight_provenance_missing"


def test_parse_russian_grams(seeded_repository):
    item = parse_item_phrase("борщ 300г", seeded_repository)
    assert item.name == "borscht"
    assert item.grams == 300
    assert item.kcal == 165


def test_parse_english_grams(seeded_repository):
    item = parse_item_phrase("bread, wheat 60 grams", seeded_repository)
    assert item.grams == 60
    assert item.kcal == 151.2


def test_parse_russian_pieces(seeded_repository):
    item = parse_item_phrase("хлеб 2 куска", seeded_repository)
    assert item.grams == 60


def test_parse_english_pieces(seeded_repository):
    item = parse_item_phrase("egg, whole, boiled 2 pieces", seeded_repository)
    assert item.grams == 100


def test_parse_millilitres_uses_density(seeded_repository):
    item = parse_item_phrase("молоко 200 мл", seeded_repository)
    assert item.grams == 206
    assert item.kcal == 125.66


def test_parse_mixed_fraction():
    assert parse_number("1 1/2") == 1.5


def test_parse_multiple_russian_items(seeded_repository):
    items = parse_free_text(
        "борщ 300г, хлеб 2 куска; гречка 150 г", seeded_repository
    )
    assert [item.grams for item in items] == [300, 60, 150]


def test_quantity_required(seeded_repository):
    with pytest.raises(NomnomError) as caught:
        parse_item_phrase("борщ", seeded_repository)
    assert caught.value.code == "quantity_required"


def test_unknown_food_error_has_item_context(seeded_repository, monkeypatch):
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    with pytest.raises(NomnomError) as caught:
        parse_free_text("несуществующая еда 100 г", seeded_repository)
    assert caught.value.code == "food_needs_source"
    assert caught.value.details["item_index"] == 0


@pytest.mark.parametrize(
    ("phrase", "expected_grams"),
    [
        ("небольшой яйцо", 50),
        ("небольших яйца", 50),
        ("маленький яйцо", 50),
        ("small egg", 50),
        ("средний яйцо", 50),
        ("medium egg", 50),
        ("крупный яйцо", 50),
        ("large egg", 50),
    ],
)
def test_parse_size_descriptors(seeded_repository, phrase, expected_grams):
    item = parse_item_phrase(phrase, seeded_repository)
    assert item.name == "egg, whole, boiled"
    assert item.grams == expected_grams
    assert item.to_dict()["assumed"] is True
    assert f"= {expected_grams}g" in item.to_dict()["assumption"]


@pytest.mark.parametrize(
    ("fraction", "factor"),
    [
        ("половина", 0.5),
        ("половины", 0.5),
        ("half", 0.5),
        ("1/2", 0.5),
        ("четверть", 0.25),
        ("quarter", 0.25),
    ],
)
def test_parse_piece_fractions(seeded_repository, fraction, factor):
    item = parse_item_phrase(f"{fraction} small fixture pod", seeded_repository)
    assert item.name == "fixture pod"
    assert item.grams == 100 * factor
    assert item.to_dict()["assumed"] is True


def test_parse_explicit_per_piece_grams(seeded_repository):
    item = parse_item_phrase("хлеб 2 куска по 40г", seeded_repository)
    assert item.name == "bread, wheat"
    assert item.grams == 80
    assert "assumed" not in item.to_dict()


def test_parse_explicit_each_grams_for_shtuk(seeded_repository):
    item = parse_item_phrase("яйцо 3 штуки по 50 г", seeded_repository)
    assert item.name == "egg, whole, boiled"
    assert item.grams == 150


def test_leading_piece_count_with_explicit_user_grams_wins():
    class Repository:
        def resolve(self, query):
            assert query == "egg whole cooked fried"
            return Food("provider candidate", 155, 12.6, 10.6, 1.1, piece_grams=52), 0.9

    item = parse_item_phrase("3 pieces egg whole cooked fried at 38g", Repository())

    assert item.grams == 114
    assert item.kcal == 176.7
    assert item.assumption is None


def test_decompose_dish_prefix_with_russian_inflection(seeded_repository):
    items = parse_free_text(
        "яичница из 3 небольших яиц, half small fixture pod "
        "и half medium fixture bulb, хлеб 2 куска по 40г",
        seeded_repository,
    )
    assert [item.name for item in items] == [
        "egg, whole, boiled",
        "fixture pod",
        "fixture bulb",
        "bread, wheat",
    ]
    assert [item.grams for item in items] == [150, 50, 40, 80]
    assert all(item.name != "oil, sunflower" for item in items)
    assert [item.to_dict().get("assumed") for item in items] == [True, True, True, None]


@pytest.mark.parametrize("prefix", ["яичница из", "омлет из", "салат из", "каша из"])
def test_all_dish_prefixes_split_conjunctions(seeded_repository, prefix):
    items = parse_free_text(
        f"{prefix} small fixture pod и medium fixture bulb", seeded_repository
    )
    assert [item.grams for item in items] == [100, 80]


def test_language_agnostic_contract_inputs_have_identical_items_and_totals(user_db):
    with connect(user_db) as connection:
        connection.execute(
            """INSERT INTO food_cache
            (name, kcal, protein, fat, carbs, piece_grams, density_g_ml, source, fdc_id,
             lookup_query)
            VALUES ('egg', 155, 12.58, 10.61, 1.12, 50, NULL, 'fixture', NULL, 'egg')"""
        )
        repository = FoodRepository(connection)
        repository.add_alias("яйцо", "egg")

        canonical = parse_free_text("egg 3 pieces", repository)
        localized = parse_free_text("яйцо 3 штуки", repository)

    assert [item.to_dict() for item in canonical] == [
        item.to_dict() for item in localized
    ]
    assert total_items(canonical) == total_items(localized)
