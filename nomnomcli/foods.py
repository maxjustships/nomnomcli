from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import replace
from importlib.resources import files
from pathlib import Path

import requests

from nomnomcli.errors import NomnomError
from nomnomcli.models import Food
from nomnomcli.off import OpenFoodFactsClient


def normalize_name(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").strip().split())


def _name_tokens(value: str) -> set[str]:
    return set(re.findall(r"\w+(?:['’]\w+)*", normalize_name(value)))


def _brand_matches_query(food: Food, query: str) -> bool:
    if not food.brand:
        return False
    normalized_query = normalize_name(query)
    brand_parts = re.split(r"[,;/|]+", food.brand)
    return any(
        normalized_brand and normalized_brand in normalized_query
        for part in brand_parts
        if (normalized_brand := normalize_name(part))
    )


class FoodRepository:
    def __init__(self, user_connection: sqlite3.Connection) -> None:
        self.user_connection = user_connection
        self.food_db_path = Path(str(files("nomnomcli.data").joinpath("foods.sqlite")))
        synonyms_path = files("nomnomcli.data").joinpath("synonyms_ru.json")
        raw_synonyms = json.loads(synonyms_path.read_text())
        self.synonyms = {normalize_name(key): value for key, value in raw_synonyms.items()}
        self.off_client = OpenFoodFactsClient()

    def _canonicalize_query(self, query: str) -> str:
        normalized = normalize_name(query)
        if canonical := self.synonyms.get(normalized):
            return canonical
        for synonym, canonical in sorted(
            self.synonyms.items(), key=lambda item: (-len(item[0]), item[0])
        ):
            normalized = re.sub(
                rf"(?<!\w){re.escape(synonym)}(?!\w)", canonical, normalized
            )
        return normalize_name(normalized)

    def _row_to_food(self, row: sqlite3.Row) -> Food:
        columns = set(row.keys())
        alternatives = ()
        if "alternatives_json" in columns and row["alternatives_json"]:
            alternatives = tuple(json.loads(row["alternatives_json"]))
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
            barcode=(str(row["barcode"]) if "barcode" in columns and row["barcode"] else None),
            brand=(str(row["brand"]) if "brand" in columns and row["brand"] else None),
            alternatives=alternatives,
        )

    def _find_exact(self, name: str) -> Food | None:
        cached = self.user_connection.execute(
            """SELECT * FROM food_cache
            WHERE name = ? COLLATE NOCASE OR lookup_query = ? COLLATE NOCASE
            ORDER BY CASE WHEN lookup_query = ? COLLATE NOCASE THEN 0 ELSE 1 END
            LIMIT 1""",
            (name, normalize_name(name), normalize_name(name)),
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
        exact = self._find_exact(normalized)
        if exact:
            return exact, 1.0

        canonical = self._canonicalize_query(normalized)
        exact = self._find_exact(canonical)
        if exact:
            return exact, 0.98 if canonical != normalized else 1.0

        ranked_cache_matches = self._ranked_user_cache_matches(canonical, limit=5)
        if ranked_cache_matches:
            return self._row_to_food(ranked_cache_matches[0]), 0.85

        matches = self.search(canonical, limit=5)
        if len(matches) == 1:
            return matches[0], 0.85
        if matches:
            first = normalize_name(matches[0].name)
            if first.startswith(canonical) or canonical.startswith(first):
                return matches[0], 0.8

        off_enabled = (
            allow_remote
            and not os.getenv("NOMNOM_OFFLINE")
            and not os.getenv("NOMNOM_DISABLE_OFF")
        )
        if off_enabled:
            off_matches = self.off_client.search(query, page_size=5)
            if off_matches:
                matching_brand = next(
                    (food for food in off_matches if _brand_matches_query(food, query)), None
                )
                if matching_brand is not None:
                    off_matches = [
                        matching_brand,
                        *(food for food in off_matches if food is not matching_brand),
                    ]
                alternatives = tuple(
                    {
                        key: value
                        for key, value in {
                            "name": alternative.name,
                            "brand": alternative.brand,
                            "barcode": alternative.barcode,
                        }.items()
                        if value is not None
                    }
                    for alternative in off_matches[1:]
                )
                food = replace(off_matches[0], alternatives=alternatives)
                self._cache_food(food, lookup_query=query)
                return food, 0.76

        api_key = os.getenv("NOMNOM_USDA_KEY")
        if allow_remote and api_key:
            return self._fetch_usda(query, api_key), 0.72
        suggestions = [food.name for food in matches[:3]]
        raise NomnomError(
            "food_not_found",
            f"Could not resolve food: {query}",
            details={
                "food": query,
                "suggestions": suggestions,
                "offline": not off_enabled and not bool(api_key),
                "action": (
                    "Search a more specific product name or pin label values with nomnom add "
                    "--name NAME --brand BRAND --kcal KCAL --protein P --fat F --carbs C"
                ),
            },
        )

    def search(self, query: str, limit: int = 10) -> list[Food]:
        canonical = self._canonicalize_query(query)
        pattern = f"%{canonical}%"
        rows: list[sqlite3.Row] = []
        rows.extend(self._ranked_user_cache_matches(canonical, limit))
        cached = self.user_connection.execute(
            """SELECT * FROM food_cache
            WHERE name LIKE ? COLLATE NOCASE OR lookup_query LIKE ? COLLATE NOCASE
            ORDER BY CASE WHEN name LIKE ? THEN 0 ELSE 1 END, length(name), name LIMIT ?""",
            (pattern, pattern, f"{canonical}%", limit),
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

    def _ranked_user_cache_matches(self, query: str, limit: int) -> list[sqlite3.Row]:
        query_tokens = _name_tokens(query)
        ranked: list[tuple[float, int, int, str, sqlite3.Row]] = []
        rows = self.user_connection.execute(
            """SELECT * FROM food_cache
            WHERE brand IS NOT NULL AND brand != ''
            ORDER BY name COLLATE NOCASE"""
        ).fetchall()
        for row in rows:
            food = self._row_to_food(row)
            if not _brand_matches_query(food, query):
                continue
            brand_tokens = _name_tokens(food.brand or "")
            requested_product_tokens = query_tokens - brand_tokens
            candidate_tokens = _name_tokens(
                " ".join(
                    value
                    for value in (food.name, food.brand, row["lookup_query"])
                    if value
                )
            ) - brand_tokens
            overlap = requested_product_tokens & candidate_tokens
            if not requested_product_tokens or not overlap:
                continue
            ranked.append(
                (
                    len(overlap) / len(requested_product_tokens),
                    len(overlap),
                    len(candidate_tokens - requested_product_tokens),
                    normalize_name(food.name),
                    row,
                )
            )
        ranked.sort(key=lambda match: (-match[0], -match[1], match[2], match[3]))
        return [match[-1] for match in ranked[:limit]]

    def _cache_food(self, food: Food, *, lookup_query: str) -> None:
        self.user_connection.execute(
            """INSERT INTO food_cache
            (name, kcal, protein, fat, carbs, piece_grams, density_g_ml, source, fdc_id,
             barcode, brand, lookup_query, alternatives_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
              kcal=excluded.kcal,
              protein=excluded.protein,
              fat=excluded.fat,
              carbs=excluded.carbs,
              piece_grams=excluded.piece_grams,
              density_g_ml=excluded.density_g_ml,
              source=excluded.source,
              fdc_id=excluded.fdc_id,
              barcode=excluded.barcode,
              brand=excluded.brand,
              lookup_query=excluded.lookup_query,
              alternatives_json=excluded.alternatives_json""",
            (
                food.name,
                food.kcal,
                food.protein,
                food.fat,
                food.carbs,
                food.piece_grams,
                food.density_g_ml,
                food.source,
                food.fdc_id,
                food.barcode,
                food.brand,
                normalize_name(lookup_query),
                json.dumps(food.alternatives, ensure_ascii=False, sort_keys=True),
            ),
        )

    def add_food(
        self,
        *,
        name: str,
        brand: str,
        kcal: float,
        protein: float,
        fat: float,
        carbs: float,
        piece_grams: float | None = None,
    ) -> Food:
        food = Food(
            name=f"{name.strip()} — {brand.strip()}",
            kcal=kcal,
            protein=protein,
            fat=fat,
            carbs=carbs,
            piece_grams=piece_grams,
            source="user",
            brand=brand.strip(),
        )
        self._cache_food(food, lookup_query=f"{name} {brand}")
        return food

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
