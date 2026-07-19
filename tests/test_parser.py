from __future__ import annotations

import pytest

from nomnomcli.errors import NomnomError
from nomnomcli.parser import parse_free_text, parse_item_phrase, parse_number


def test_parse_russian_grams(repository):
    item = parse_item_phrase("борщ 300г", repository)
    assert item.name == "borscht"
    assert item.grams == 300
    assert item.kcal == 165


def test_parse_english_grams(repository):
    item = parse_item_phrase("bread, wheat 60 grams", repository)
    assert item.grams == 60
    assert item.kcal == 151.2


def test_parse_russian_pieces(repository):
    item = parse_item_phrase("хлеб 2 куска", repository)
    assert item.grams == 60


def test_parse_english_pieces(repository):
    item = parse_item_phrase("egg, whole, boiled 2 pieces", repository)
    assert item.grams == 100


def test_parse_millilitres_uses_density(repository):
    item = parse_item_phrase("молоко 200 мл", repository)
    assert item.grams == 206
    assert item.kcal == 125.66


def test_parse_mixed_fraction():
    assert parse_number("1 1/2") == 1.5


def test_parse_multiple_russian_items(repository):
    items = parse_free_text("борщ 300г, хлеб 2 куска; гречка 150 г", repository)
    assert [item.grams for item in items] == [300, 60, 150]


def test_quantity_required(repository):
    with pytest.raises(NomnomError) as caught:
        parse_item_phrase("борщ", repository)
    assert caught.value.code == "quantity_required"


def test_unknown_food_error_has_item_context(repository, monkeypatch):
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    with pytest.raises(NomnomError) as caught:
        parse_free_text("несуществующая еда 100 г", repository)
    assert caught.value.code == "food_not_found"
    assert caught.value.details["item_index"] == 0


@pytest.mark.parametrize(
    ("phrase", "expected_grams"),
    [
        ("небольшой яйцо", 45),
        ("небольших яйца", 45),
        ("маленький яйцо", 45),
        ("small egg", 45),
        ("средний яйцо", 55),
        ("medium egg", 55),
        ("крупный яйцо", 65),
        ("large egg", 65),
    ],
)
def test_parse_size_descriptors(repository, phrase, expected_grams):
    item = parse_item_phrase(phrase, repository)
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
def test_parse_piece_fractions(repository, fraction, factor):
    item = parse_item_phrase(f"{fraction} small tomato", repository)
    assert item.name == "tomato, raw"
    assert item.grams == 60 * factor
    assert item.to_dict()["assumed"] is True


def test_parse_explicit_per_piece_grams(repository):
    item = parse_item_phrase("хлеб 2 куска по 40г", repository)
    assert item.name == "bread, wheat"
    assert item.grams == 80
    assert "assumed" not in item.to_dict()


def test_parse_explicit_each_grams_for_shtuk(repository):
    item = parse_item_phrase("яйцо 3 штуки по 50 г", repository)
    assert item.name == "egg, whole, boiled"
    assert item.grams == 150


def test_decompose_dish_prefix_with_russian_inflection(repository):
    items = parse_free_text(
        "яичница из 3 небольших яиц, половины небольшого томата "
        "и половины средней луковицы, хлеб 2 куска по 40г",
        repository,
    )
    assert [item.name for item in items] == [
        "egg, whole, boiled",
        "tomato, raw",
        "onion, raw",
        "bread, wheat",
    ]
    assert [item.grams for item in items] == [135, 30, 40, 80]
    assert all(item.name != "oil, sunflower" for item in items)
    assert [item.to_dict().get("assumed") for item in items] == [True, True, True, None]


@pytest.mark.parametrize("prefix", ["яичница из", "омлет из", "салат из", "каша из"])
def test_all_dish_prefixes_split_conjunctions(repository, prefix):
    items = parse_free_text(f"{prefix} small tomato и medium onion", repository)
    assert [item.grams for item in items] == [60, 80]
