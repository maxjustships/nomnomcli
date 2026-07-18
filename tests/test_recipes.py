from __future__ import annotations

from pathlib import Path

import pytest

from nomnomcli.db import connect
from nomnomcli.errors import NomnomError
from nomnomcli.foods import FoodRepository
from nomnomcli.recipes import (
    build_recipe,
    extract_recipe_json_ld,
    recipe_portion,
    save_recipe,
)

FIXTURE = Path(__file__).parent / "fixtures" / "recipe.html"


def test_extract_recipe_json_ld():
    schema = extract_recipe_json_ld(FIXTURE.read_text())
    assert schema["name"] == "Buckwheat and Eggs"


def test_recipe_missing_schema():
    with pytest.raises(NomnomError) as caught:
        extract_recipe_json_ld("<html></html>")
    assert caught.value.code == "recipe_schema_missing"


def test_build_recipe_math(repository):
    schema = extract_recipe_json_ld(FIXTURE.read_text())
    recipe = build_recipe(schema, repository, "https://example.test/recipe")
    assert recipe["servings"] == 2
    assert recipe["per_serving"]["kcal"] == 169.5


def test_servings_override(repository):
    schema = extract_recipe_json_ld(FIXTURE.read_text())
    recipe = build_recipe(schema, repository, "https://example.test/recipe", 4)
    assert recipe["per_serving"]["kcal"] == 84.75


def test_save_and_log_fractional_portion(user_db):
    with connect(user_db) as connection:
        repository = FoodRepository(connection)
        recipe = build_recipe(
            extract_recipe_json_ld(FIXTURE.read_text()),
            repository,
            "https://example.test/recipe",
        )
        save_recipe(connection, recipe)
        portion = recipe_portion(connection, "buckwheat and eggs", 1.5)
    assert portion["totals"]["kcal"] == 254.25
    assert portion["portions"] == 1.5


def test_missing_stored_recipe(user_db):
    with connect(user_db) as connection, pytest.raises(NomnomError) as caught:
        recipe_portion(connection, "missing", 1)
    assert caught.value.code == "recipe_not_found"
