from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from dataclasses import replace

import requests

from nomnomcli.errors import NomnomError
from nomnomcli.models import Food
from nomnomcli.off import OpenFoodFactsClient

USDA_SETUP_URL = "https://fdc.nal.usda.gov/api-key-signup.html"
USDA_KEY_REQUIRED_MESSAGE = (
    f"USDA FoodData Central API key required. Get a free key at {USDA_SETUP_URL}, "
    "then set NOMNOM_USDA_KEY."
)
USDA_KEY_SETUP = f"Get a free key at {USDA_SETUP_URL} then: export NOMNOM_USDA_KEY=..."


def normalize_name(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").strip().split())


def _name_tokens(value: str) -> set[str]:
    return {
        _comparison_token(token)
        for token in re.findall(r"\w+(?:['’]\w+)*", normalize_name(value))
    }


def _comparison_token(token: str) -> str:
    if re.fullmatch(r"я(?:й|и)ц(?:о|а|у|ом|е|ы)?", token):
        return "яйц"
    if re.fullmatch(r"[a-z]+", token) and len(token) > 3 and token.endswith("s"):
        return token[:-1]
    if re.search(r"[а-я]", token):
        for ending in ("ыми", "ими", "ого", "ему", "ами", "ями", "ые", "ие", "ый", "ий"):
            if len(token) > len(ending) + 2 and token.endswith(ending):
                return token[: -len(ending)]
    return token


_FOOD_TYPE_MARKERS = {
    "cheese": {"cheese", "сыр", "сыры"},
    "eggs": {"egg", "яйц"},
    "nuts": {"nut", "орех", "орехи", "орехов"},
}


def _food_types(tokens: set[str]) -> set[str]:
    return {
        food_type
        for food_type, markers in _FOOD_TYPE_MARKERS.items()
        if tokens & markers
    }


def _off_confidence(query: str, food: Food) -> float:
    query_tokens = _name_tokens(query)
    category_tokens = _name_tokens(" ".join(food.categories))
    query_types = _food_types(query_tokens)
    category_types = _food_types(category_tokens)
    if query_types and category_types and query_types.isdisjoint(category_types):
        return 0.0
    candidate_tokens = _name_tokens(" ".join((food.name, food.brand or "")))
    if not query_tokens:
        return 0.0
    return len(query_tokens & candidate_tokens) / len(query_tokens)


def _candidate_details(food: Food, confidence: float) -> dict:
    return {
        key: value
        for key, value in {
            "name": food.name,
            "brand": food.brand,
            "barcode": food.barcode,
            "confidence": round(confidence, 2),
        }.items()
        if value is not None
    }


def _usda_serving_grams(record: dict) -> float | None:
    if str(record.get("servingSizeUnit") or "").casefold() not in {"g", "gram", "grams"}:
        return None
    try:
        value = float(record.get("servingSize"))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


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
        self.off_client = OpenFoodFactsClient()

    def _canonicalize_query(self, query: str) -> str:
        return normalize_name(query)

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
        return self._row_to_food(cached) if cached else None

    def _find_name_exact(self, name: str) -> Food | None:
        cached = self.user_connection.execute(
            "SELECT * FROM food_cache WHERE name = ? COLLATE NOCASE LIMIT 1",
            (name,),
        ).fetchone()
        if cached is not None:
            return self._row_to_food(cached)
        normalized = normalize_name(name)
        rows = self.user_connection.execute("SELECT * FROM food_cache").fetchall()
        return next(
            (self._row_to_food(row) for row in rows if normalize_name(row["name"]) == normalized),
            None,
        )

    def _alias_target(self, query: str) -> Food | None:
        alias = self.user_connection.execute(
            """SELECT phrase, canonical_name FROM food_aliases
            WHERE normalized_phrase = ?""",
            (normalize_name(query),),
        ).fetchone()
        if alias is None:
            return None
        target = self._find_name_exact(alias["canonical_name"])
        if target is None:
            raise NomnomError(
                "alias_target_not_found",
                f"Alias target is not in the user cache: {alias['canonical_name']}",
                details={
                    "phrase": alias["phrase"],
                    "canonical_food_name": alias["canonical_name"],
                    "action": "Remove the alias or add the exact canonical food to the user cache",
                },
            )
        return target

    def resolve(self, query: str, *, allow_remote: bool = True) -> tuple[Food, float]:
        normalized = normalize_name(query)
        alias = self._alias_target(normalized)
        if alias is not None:
            return alias, 1.0

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

        remote_enabled = allow_remote and not os.getenv("NOMNOM_OFFLINE")
        off_enabled = remote_enabled and not os.getenv("NOMNOM_DISABLE_OFF")
        api_key = os.getenv("NOMNOM_USDA_KEY")
        low_confidence_error: NomnomError | None = None
        if off_enabled:
            try:
                off_matches = self.off_client.search(query, page_size=5)
            except NomnomError:
                if not api_key:
                    raise
                off_matches = []
            if off_matches:
                matching_brand = next(
                    (food for food in off_matches if _brand_matches_query(food, query)), None
                )
                if matching_brand is not None:
                    off_matches = [
                        matching_brand,
                        *(food for food in off_matches if food is not matching_brand),
                    ]
                scored = [(food, _off_confidence(query, food)) for food in off_matches]
                accepted = [match for match in scored if match[1] >= 0.5]
                if not accepted:
                    candidate, confidence = scored[0]
                    low_confidence_error = NomnomError(
                        "off_low_confidence",
                        f"Open Food Facts candidate is too weak for: {query}",
                        details={
                            "food": query,
                            "threshold": 0.5,
                            "candidate": _candidate_details(candidate, confidence),
                            "alternatives": [
                                _candidate_details(food, score) for food, score in scored[1:]
                            ],
                            "action": (
                                "Try a more specific name, configure NOMNOM_USDA_KEY, or pin "
                                "verified label values with nomnom add"
                            ),
                        },
                    )
                else:
                    accepted.sort(key=lambda match: -match[1])
                    selected, confidence = accepted[0]
                    off_matches = [
                        selected,
                        *(food for food in off_matches if food is not selected),
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
                    return food, confidence

        if remote_enabled and api_key:
            return self._fetch_usda(query, api_key), 0.72
        if low_confidence_error is not None:
            raise low_confidence_error
        suggestions = [food.name for food in matches[:3]]
        if remote_enabled:
            raise NomnomError(
                "usda_key_required",
                USDA_KEY_REQUIRED_MESSAGE,
                details={
                    "food": query,
                    "setup_url": USDA_SETUP_URL,
                    "setup": USDA_KEY_SETUP,
                    "environment_variable": "NOMNOM_USDA_KEY",
                    "action": (
                        "Set NOMNOM_USDA_KEY or pin verified nutrition with nomnom add "
                        "--name NAME --brand BRAND --kcal KCAL --protein P --fat F --carbs C"
                    ),
                },
            )
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
        unique: dict[str, Food] = {}
        for row in rows:
            food = self._row_to_food(row)
            unique.setdefault(normalize_name(food.name), food)
        return list(unique.values())[:limit]

    def add_alias(self, phrase: str, canonical_food_name: str) -> dict[str, str]:
        display_phrase = " ".join(phrase.strip().split())
        canonical_input = " ".join(canonical_food_name.strip().split())
        normalized_phrase = normalize_name(display_phrase)
        if not normalized_phrase or not canonical_input:
            raise NomnomError(
                "invalid_alias", "Alias phrase and canonical food name must not be empty"
            )
        target = self._find_name_exact(canonical_input)
        if target is None:
            raise NomnomError(
                "alias_target_not_found",
                f"Canonical food is not in the user cache: {canonical_input}",
                details={
                    "phrase": display_phrase,
                    "canonical_food_name": canonical_input,
                    "action": "Resolve or add the exact canonical food before creating its alias",
                },
            )
        existing = self.user_connection.execute(
            "SELECT phrase, canonical_name FROM food_aliases WHERE normalized_phrase = ?",
            (normalized_phrase,),
        ).fetchone()
        if existing is not None:
            raise NomnomError(
                "alias_exists",
                f"Alias already exists: {existing['phrase']}",
                details={
                    "phrase": existing["phrase"],
                    "canonical_food_name": existing["canonical_name"],
                },
            )
        self.user_connection.execute(
            """INSERT INTO food_aliases (phrase, normalized_phrase, canonical_name)
            VALUES (?, ?, ?)""",
            (display_phrase, normalized_phrase, target.name),
        )
        return {"phrase": display_phrase, "canonical_food_name": target.name}

    def list_aliases(self) -> list[dict[str, str]]:
        rows = self.user_connection.execute(
            """SELECT phrase, canonical_name FROM food_aliases
            ORDER BY normalized_phrase"""
        ).fetchall()
        return [
            {"phrase": str(row["phrase"]), "canonical_food_name": str(row["canonical_name"])}
            for row in rows
        ]

    def remove_alias(self, phrase: str) -> dict[str, str]:
        normalized_phrase = normalize_name(phrase)
        if not normalized_phrase:
            raise NomnomError("invalid_alias", "Alias phrase must not be empty")
        existing = self.user_connection.execute(
            "SELECT phrase, canonical_name FROM food_aliases WHERE normalized_phrase = ?",
            (normalized_phrase,),
        ).fetchone()
        if existing is None:
            raise NomnomError(
                "alias_not_found",
                f"Alias not found: {' '.join(phrase.strip().split())}",
                details={"phrase": " ".join(phrase.strip().split())},
            )
        self.user_connection.execute(
            "DELETE FROM food_aliases WHERE normalized_phrase = ?", (normalized_phrase,)
        )
        return {
            "phrase": str(existing["phrase"]),
            "canonical_food_name": str(existing["canonical_name"]),
        }

    def _ranked_user_cache_matches(self, query: str, limit: int) -> list[sqlite3.Row]:
        query_tokens = _name_tokens(query)
        ranked: list[tuple[float, int, int, int, str, sqlite3.Row]] = []
        rows = self.user_connection.execute(
            "SELECT * FROM food_cache ORDER BY name COLLATE NOCASE"
        ).fetchall()
        for row in rows:
            food = self._row_to_food(row)
            candidate_tokens = _name_tokens(
                " ".join(
                    value
                    for value in (food.name, food.brand, row["lookup_query"])
                    if value
                )
            )
            overlap = query_tokens & candidate_tokens
            if not query_tokens or len(overlap) / len(query_tokens) < 0.5:
                continue
            ranked.append(
                (
                    len(overlap) / len(query_tokens),
                    len(overlap),
                    0 if food.source == "user" else 1,
                    len(candidate_tokens - query_tokens),
                    normalize_name(food.name),
                    row,
                )
            )
        ranked.sort(
            key=lambda match: (-match[0], -match[1], match[2], match[3], match[4])
        )
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
            raise NomnomError(
                "food_not_found",
                f"USDA could not resolve food: {query}",
                details={
                    "food": query,
                    "action": (
                        "Try a more specific name or pin verified nutrition with nomnom add "
                        "--name NAME --brand BRAND --kcal KCAL --protein P --fat F --carbs C"
                    ),
                },
            )
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
            piece_grams=_usda_serving_grams(record),
            source="usda",
            fdc_id=record.get("fdcId"),
        )
        self._cache_food(food, lookup_query=query)
        return food
