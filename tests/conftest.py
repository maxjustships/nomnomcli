from __future__ import annotations

import json
from pathlib import Path

import pytest

from nomnomcli.db import connect
from nomnomcli.foods import FoodRepository

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "foods.json"


@pytest.fixture(autouse=True)
def isolate_user_provider_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


@pytest.fixture
def user_db(tmp_path: Path) -> Path:
    return tmp_path / "user.sqlite3"


@pytest.fixture(scope="session")
def food_fixtures() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def seed_food_cache(connection, foods: list[dict]) -> None:
    for food in foods:
        connection.execute(
            """INSERT INTO food_cache
            (name, kcal, protein, fat, carbs, piece_grams, density_g_ml, source, fdc_id,
             lookup_query, piece_grams_source, piece_grams_source_value)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                food["name"],
                food["kcal"],
                food["protein"],
                food["fat"],
                food["carbs"],
                food.get("piece_grams"),
                food.get("density_g_ml"),
                "fixture",
                None,
                food.get("lookup_query"),
                "synthetic_serving" if food.get("piece_grams") is not None else None,
                (
                    f"{food['piece_grams']:g} g"
                    if food.get("piece_grams") is not None
                    else None
                ),
            ),
        )


@pytest.fixture
def repository(user_db: Path):
    with connect(user_db) as connection:
        yield FoodRepository(connection)


@pytest.fixture
def seeded_repository(user_db: Path, food_fixtures: dict):
    with connect(user_db) as connection:
        seed_food_cache(connection, food_fixtures["cache"])
        yield FoodRepository(connection)


@pytest.fixture
def seeded_user_db(user_db: Path, food_fixtures: dict) -> Path:
    with connect(user_db) as connection:
        seed_food_cache(connection, food_fixtures["cache"])
    return user_db
