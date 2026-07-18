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


def test_unknown_food_error_has_item_context(repository):
    with pytest.raises(NomnomError) as caught:
        parse_free_text("несуществующая еда 100 г", repository)
    assert caught.value.code == "food_not_found"
    assert caught.value.details["item_index"] == 0
