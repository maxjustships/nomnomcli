from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from html import unescape
from html.parser import HTMLParser

import requests

from nomnomcli.errors import NomnomError
from nomnomcli.foods import FoodRepository
from nomnomcli.models import NUTRIENT_KEYS, round_nutrition, total_items
from nomnomcli.parser import parse_recipe_ingredient


class _RecipeScriptParser:
    class Parser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.in_recipe_script = False
            self.parts: list[str] = []
            self.scripts: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            attributes = {key.casefold(): (value or "") for key, value in attrs}
            if tag.casefold() == "script" and "ld+json" in attributes.get("type", "").casefold():
                self.in_recipe_script = True
                self.parts = []

        def handle_data(self, data: str) -> None:
            if self.in_recipe_script:
                self.parts.append(data)

        def handle_endtag(self, tag: str) -> None:
            if tag.casefold() == "script" and self.in_recipe_script:
                self.scripts.append("".join(self.parts))
                self.in_recipe_script = False


def _walk_json_ld(value):
    if isinstance(value, list):
        for item in value:
            yield from _walk_json_ld(item)
    elif isinstance(value, dict):
        if "@graph" in value:
            yield from _walk_json_ld(value["@graph"])
        yield value


def extract_recipe_json_ld(html: str) -> dict:
    parser = _RecipeScriptParser.Parser()
    parser.feed(html)
    for script in parser.scripts:
        try:
            payload = json.loads(unescape(script).strip())
        except json.JSONDecodeError:
            continue
        for candidate in _walk_json_ld(payload):
            types = candidate.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if any(str(item).casefold() == "recipe" for item in types):
                return candidate
    raise NomnomError("recipe_schema_missing", "Page has no valid schema.org Recipe JSON-LD")


def _servings_from_schema(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, str):
        import re

        match = re.search(r"\d+(?:[.,]\d+)?", value)
        if match:
            return float(match.group().replace(",", "."))
    return 1.0


def build_recipe(
    schema: dict,
    repository: FoodRepository,
    source_url: str,
    servings_override: float | None = None,
) -> dict:
    name = str(schema.get("name") or "").strip()
    raw_ingredients = schema.get("recipeIngredient") or schema.get("ingredients") or []
    if not name or not isinstance(raw_ingredients, list) or not raw_ingredients:
        raise NomnomError("invalid_recipe", "Recipe needs a name and recipeIngredient list")
    servings = servings_override or _servings_from_schema(schema.get("recipeYield"))
    if servings <= 0:
        raise NomnomError("invalid_servings", "Servings must be greater than zero")
    ingredients = [parse_recipe_ingredient(str(item), repository) for item in raw_ingredients]
    totals = total_items(ingredients)
    per_serving = {key: round_nutrition(totals[key] / servings) for key in NUTRIENT_KEYS}
    return {
        "name": name,
        "source_url": source_url,
        "servings": round_nutrition(servings),
        "ingredients": [item.to_dict() for item in ingredients],
        "per_serving": per_serving,
    }


def fetch_recipe(
    url: str,
    repository: FoodRepository,
    servings_override: float | None = None,
) -> dict:
    try:
        response = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "nomnomcli/0.1 (+https://github.com/maxjustships/nomnomcli)"},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise NomnomError("recipe_fetch_failed", f"Could not fetch recipe URL: {url}") from exc
    schema = extract_recipe_json_ld(response.text)
    return build_recipe(schema, repository, url, servings_override)


def save_recipe(connection: sqlite3.Connection, recipe: dict) -> None:
    values = [recipe["per_serving"][key] for key in NUTRIENT_KEYS]
    connection.execute(
        """INSERT INTO recipes
        (name, source_url, servings, ingredients_json, kcal_per_serving,
         protein_per_serving, fat_per_serving, carbs_per_serving, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
          source_url=excluded.source_url,
          servings=excluded.servings,
          ingredients_json=excluded.ingredients_json,
          kcal_per_serving=excluded.kcal_per_serving,
          protein_per_serving=excluded.protein_per_serving,
          fat_per_serving=excluded.fat_per_serving,
          carbs_per_serving=excluded.carbs_per_serving,
          created_at=excluded.created_at""",
        (
            recipe["name"],
            recipe["source_url"],
            recipe["servings"],
            json.dumps(recipe["ingredients"], ensure_ascii=False, sort_keys=True),
            *values,
            datetime.now().astimezone().isoformat(timespec="seconds"),
        ),
    )


def recipe_portion(connection: sqlite3.Connection, name: str, portions: float) -> dict:
    if portions <= 0:
        raise NomnomError("invalid_portions", "Portions must be greater than zero")
    row = connection.execute(
        "SELECT * FROM recipes WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if not row:
        raise NomnomError("recipe_not_found", f"Stored recipe not found: {name}")
    serving_ingredients = json.loads(row["ingredients_json"])
    recipe_servings = float(row["servings"])
    factor = portions / recipe_servings
    items = []
    for ingredient in serving_ingredients:
        scaled = {
            key: round_nutrition(float(value) * factor)
            if key in {"grams", *NUTRIENT_KEYS}
            else value
            for key, value in ingredient.items()
        }
        items.append(scaled)
    totals = {
        key: round_nutrition(float(row[f"{key}_per_serving"]) * portions) for key in NUTRIENT_KEYS
    }
    return {
        "recipe": row["name"],
        "portions": round_nutrition(portions),
        "items": items,
        "totals": totals,
    }
