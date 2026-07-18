from __future__ import annotations

import json
import os
import sqlite3
from importlib.resources import files
from pathlib import Path

import requests

from nomnomcli.errors import NomnomError
from nomnomcli.models import Food


def normalize_name(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").strip().split())


class FoodRepository:
    def __init__(self, user_connection: sqlite3.Connection) -> None:
        self.user_connection = user_connection
        self.food_db_path = Path(str(files("nomnomcli.data").joinpath("foods.sqlite")))
        synonyms_path = files("nomnomcli.data").joinpath("synonyms_ru.json")
        raw_synonyms = json.loads(synonyms_path.read_text())
        self.synonyms = {normalize_name(key): value for key, value in raw_synonyms.items()}

    def _row_to_food(self, row: sqlite3.Row) -> Food:
        return Food(
            name=row["name"],
            kcal=float(row["kcal"]),
            protein=float(row["protein"]),
            fat=float(row["fat"]),
            carbs=float(row["carbs"]),
            piece_grams=float(row["piece_grams"]) if row["piece_grams"] is not None else None,
            density_g_ml=float(row["density_g_ml"]) if row["density_g_ml"] is not None else None,
            source=row["source"],
            fdc_id=int(row["fdc_id"]) if row["fdc_id"] is not None else None,
        )

    def _find_exact(self, name: str) -> Food | None:
        cached = self.user_connection.execute(
            "SELECT * FROM food_cache WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        if cached:
            return self._row_to_food(cached)
        with sqlite3.connect(self.food_db_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM foods WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
            return self._row_to_food(row) if row else None

    def resolve(self, query: str, *, allow_remote: bool = True) -> tuple[Food, float]:
        normalized = normalize_name(query)
        canonical = self.synonyms.get(normalized, normalized)
        exact = self._find_exact(canonical)
        if exact:
            return exact, 0.98 if canonical != normalized else 1.0

        matches = self.search(canonical, limit=5)
        if len(matches) == 1:
            return matches[0], 0.85
        if matches:
            first = normalize_name(matches[0].name)
            if first.startswith(canonical) or canonical.startswith(first):
                return matches[0], 0.8

        api_key = os.getenv("NOMNOM_USDA_KEY")
        if allow_remote and api_key:
            return self._fetch_usda(query, api_key), 0.72
        suggestions = [food.name for food in matches[:3]]
        raise NomnomError(
            "food_not_found",
            f"Could not resolve food: {query}",
            details={"food": query, "suggestions": suggestions, "offline": not bool(api_key)},
        )

    def search(self, query: str, limit: int = 10) -> list[Food]:
        normalized = normalize_name(query)
        canonical = self.synonyms.get(normalized, normalized)
        pattern = f"%{canonical}%"
        rows: list[sqlite3.Row] = []
        cached = self.user_connection.execute(
            """SELECT * FROM food_cache WHERE name LIKE ? COLLATE NOCASE
            ORDER BY CASE WHEN name LIKE ? THEN 0 ELSE 1 END, length(name), name LIMIT ?""",
            (pattern, f"{canonical}%", limit),
        ).fetchall()
        rows.extend(cached)
        with sqlite3.connect(self.food_db_path) as connection:
            connection.row_factory = sqlite3.Row
            bundled = connection.execute(
                """SELECT * FROM foods WHERE name LIKE ? COLLATE NOCASE
                ORDER BY CASE WHEN name LIKE ? THEN 0 ELSE 1 END, length(name), name LIMIT ?""",
                (pattern, f"{canonical}%", limit),
            ).fetchall()
            rows.extend(bundled)
        unique: dict[str, Food] = {}
        for row in rows:
            food = self._row_to_food(row)
            unique.setdefault(normalize_name(food.name), food)
        return list(unique.values())[:limit]

    def _fetch_usda(self, query: str, api_key: str) -> Food:
        try:
            response = requests.get(
                "https://api.nal.usda.gov/fdc/v1/foods/search",
                params={"api_key": api_key, "query": query, "pageSize": 1},
                timeout=15,
            )
            response.raise_for_status()
            foods = response.json().get("foods", [])
        except (requests.RequestException, ValueError) as exc:
            raise NomnomError(
                "usda_unavailable", "USDA fallback request failed", details={"food": query}
            ) from exc
        if not foods:
            raise NomnomError("food_not_found", f"USDA could not resolve food: {query}")
        record = foods[0]
        nutrients = {}
        for item in record.get("foodNutrients", []):
            name = item.get("nutrientName", "").casefold()
            if name == "energy" and (
                str(item.get("nutrientNumber", "")) != "208"
                and str(item.get("unitName", "")).casefold() != "kcal"
            ):
                continue
            nutrients[name] = float(item.get("value") or 0)
        food = Food(
            name=record["description"].casefold(),
            kcal=nutrients.get("energy", 0.0),
            protein=nutrients.get("protein", 0.0),
            fat=nutrients.get("total lipid (fat)", 0.0),
            carbs=nutrients.get("carbohydrate, by difference", 0.0),
            source="USDA FDC API",
            fdc_id=record.get("fdcId"),
        )
        self.user_connection.execute(
            """INSERT OR REPLACE INTO food_cache
            (name, kcal, protein, fat, carbs, piece_grams, density_g_ml, source, fdc_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                food.name,
                food.kcal,
                food.protein,
                food.fat,
                food.carbs,
                None,
                None,
                food.source,
                food.fdc_id,
            ),
        )
        return food
