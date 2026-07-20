from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from dataclasses import replace

from nomnomcli.config import ProviderConfig
from nomnomcli.errors import NomnomError
from nomnomcli.models import Food
from nomnomcli.off import OpenFoodFactsClient
from nomnomcli.usda import USDAClient

USDA_SETUP_URL = "https://fdc.nal.usda.gov/api-key-signup.html"
GENERIC_USDA_DATA_TYPES = frozenset({"foundation", "sr legacy", "survey (fndds)"})
EXACT_CAPTURE_ACTION = (
    "Provide the package barcode or photo so the agent can run nomnom capture "
    "barcode or nomnom capture label"
)


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


def _off_confidence(query: str, food: Food) -> float:
    query_tokens = _name_tokens(query)
    category_tokens = _name_tokens(" ".join(food.categories))
    if category_tokens and query_tokens.isdisjoint(category_tokens):
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


def _generic_proxy_query_is_safe(query: str, food: Food) -> bool:
    query_tokens = _name_tokens(query)
    candidate_tokens = _name_tokens(food.name)
    return bool(query_tokens) and query_tokens <= candidate_tokens and not any(
        token.isdigit() for token in query_tokens
    )


def _off_candidate_query_is_safe(query: str, food: Food) -> bool:
    if food.brand is None:
        return _generic_proxy_query_is_safe(query, food)
    query_tokens = _name_tokens(query)
    candidate_tokens = _name_tokens(" ".join((food.name, food.brand)))
    return bool(query_tokens) and query_tokens <= candidate_tokens


def _generic_proxy_candidate(food: Food, confidence: float) -> dict:
    return {
        "name": food.name,
        "source": food.source,
        "source_id": food.source_id or (str(food.fdc_id) if food.fdc_id is not None else None),
        "resolution_mode": "generic_proxy",
        "confidence": round(confidence, 2),
    }


def _food_needs_source_error(
    query: str,
    *,
    provider_error: NomnomError | None = None,
    offline: bool = False,
) -> NomnomError:
    technical = None
    if provider_error is not None:
        technical = {
            "code": provider_error.code,
            "message": provider_error.message,
            "details": provider_error.details,
        }
    details = {
        "food": query,
        "offline": offline,
        "source_options": {
            "photo": {
                "message": "Send a clear package photo so the agent can extract label facts."
            },
            "barcode": {"command": "nomnom capture barcode BARCODE --json"},
            "capture_label": {
                "command": (
                    "nomnom capture label --name NAME --kcal KCAL --protein P "
                    "--fat F --carbs C --source-note SOURCE --json"
                )
            },
            "local_cache": {
                "command": "nomnom search QUERY --json",
                "aliases": "nomnom alias list --json",
            },
        },
        "optional_usda_enhancement": {
            "optional": True,
            "command": "nomnom setup",
            "purpose": "broader no-photo raw/generic food coverage",
            "signup_url": USDA_SETUP_URL,
        },
        "provider_error": technical,
        "action": (
            "Use a package photo, barcode, verified label capture, or exact local cache entry; "
            "USDA setup is optional for broader generic/raw coverage"
        ),
    }
    if provider_error is not None:
        for key in ("candidate", "alternatives"):
            if key in provider_error.details:
                details[key] = provider_error.details[key]
    return NomnomError(
        "food_needs_source",
        f"Food needs a trusted source: {query}",
        details=details,
    )


class FoodRepository:
    def __init__(
        self,
        user_connection: sqlite3.Connection,
        *,
        provider_config: ProviderConfig | None = None,
        off_client: OpenFoodFactsClient | None = None,
        usda_client: USDAClient | None = None,
    ) -> None:
        self.user_connection = user_connection
        self.provider_config = provider_config or ProviderConfig()
        self.off_client = off_client or OpenFoodFactsClient()
        self.usda_client = usda_client or USDAClient()

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
            piece_grams_source=(
                str(row["piece_grams_source"])
                if "piece_grams_source" in columns and row["piece_grams_source"]
                else None
            ),
            piece_grams_source_value=(
                str(row["piece_grams_source_value"])
                if "piece_grams_source_value" in columns and row["piece_grams_source_value"]
                else None
            ),
            density_g_ml=float(row["density_g_ml"]) if row["density_g_ml"] is not None else None,
            source=row["source"],
            fdc_id=int(row["fdc_id"]) if row["fdc_id"] is not None else None,
            barcode=(str(row["barcode"]) if "barcode" in columns and row["barcode"] else None),
            brand=(str(row["brand"]) if "brand" in columns and row["brand"] else None),
            alternatives=alternatives,
            resolution_mode=(
                str(row["resolution_mode"])
                if "resolution_mode" in columns and row["resolution_mode"]
                else "legacy"
            ),
            source_id=(
                str(row["source_id"])
                if "source_id" in columns and row["source_id"]
                else None
            ),
            source_note=(
                str(row["source_note"])
                if "source_note" in columns and row["source_note"]
                else None
            ),
            provenance=(
                str(row["provenance"])
                if "provenance" in columns and row["provenance"]
                else str(row["source"])
            ),
            assumption=(
                str(row["assumption"])
                if "assumption" in columns and row["assumption"]
                else None
            ),
        )

    def _apply_generic_proxy_policy(
        self, food: Food, confidence: float
    ) -> tuple[Food, float]:
        if food.resolution_mode != "generic_proxy":
            return food, confidence
        policy = self.provider_config.generic_proxy_policy()
        if policy == "allow_for_unbranded":
            return food, confidence
        candidate = _generic_proxy_candidate(food, confidence)
        if policy == "ask":
            raise NomnomError(
                "generic_proxy_confirmation_required",
                f"Confirm the USDA generic proxy for: {food.name}",
                details={
                    "candidate": candidate,
                    "policy": policy,
                    "action": (
                        "Confirm this named USDA proxy by setting the policy to "
                        "allow_for_unbranded, or provide a package barcode/photo"
                    ),
                },
            )
        raise NomnomError(
            "exact_resolution_required",
            f"Exact product resolution is required for: {food.name}",
            details={"candidate": candidate, "policy": policy, "action": EXACT_CAPTURE_ACTION},
        )

    def _prepare_usda_generic_proxy(
        self, query: str, food: Food, confidence: float
    ) -> tuple[Food, float]:
        generic_type = (food.provider_data_type or "").casefold()
        eligible = (
            food.source == "usda"
            and food.fdc_id is not None
            and food.brand is None
            and generic_type in GENERIC_USDA_DATA_TYPES
            and _generic_proxy_query_is_safe(query, food)
        )
        if not eligible:
            raise NomnomError(
                "exact_resolution_required",
                f"Exact product resolution is required for: {query}",
                details={
                    "food": query,
                    "candidate": {
                        "name": food.name,
                        "source": food.source,
                        "source_id": str(food.fdc_id) if food.fdc_id is not None else None,
                        "data_type": food.provider_data_type,
                        "brand": food.brand,
                        "confidence": round(confidence, 2),
                    },
                    "action": EXACT_CAPTURE_ACTION,
                },
            )
        proxy = replace(
            food,
            resolution_mode="generic_proxy",
            source_id=str(food.fdc_id),
            provenance="usda",
            assumption=f"Brand not specified; used USDA generic proxy: {food.name}.",
        )
        return self._apply_generic_proxy_policy(proxy, confidence)

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
            return self._apply_generic_proxy_policy(alias, 1.0)

        exact = self._find_exact(normalized)
        if exact:
            return self._apply_generic_proxy_policy(exact, 1.0)

        canonical = self._canonicalize_query(normalized)
        exact = self._find_exact(canonical)
        if exact:
            return self._apply_generic_proxy_policy(
                exact, 0.98 if canonical != normalized else 1.0
            )

        ranked_cache_matches = self._ranked_user_cache_matches(canonical, limit=5)
        if ranked_cache_matches:
            return self._apply_generic_proxy_policy(
                self._row_to_food(ranked_cache_matches[0]), 0.85
            )

        matches = self.search(canonical, limit=5)
        if len(matches) == 1:
            return matches[0], 0.85
        if matches:
            first = normalize_name(matches[0].name)
            if first.startswith(canonical) or canonical.startswith(first):
                return matches[0], 0.8

        remote_enabled = allow_remote and not os.getenv("NOMNOM_OFFLINE")
        off_enabled = remote_enabled and not os.getenv("NOMNOM_DISABLE_OFF")
        credential = self.provider_config.usda_credential()
        off_error: NomnomError | None = None
        if off_enabled:
            try:
                off_matches = self.off_client.search(query, page_size=5)
            except NomnomError as exc:
                off_error = exc
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
                accepted = [
                    match
                    for match in scored
                    if match[1] >= 0.5
                    and (match[0].source_id or match[0].barcode)
                    and _off_candidate_query_is_safe(query, match[0])
                ]
                if not accepted:
                    candidate, confidence = scored[0]
                    source_identity_missing = (
                        confidence >= 0.5
                        and _off_candidate_query_is_safe(query, candidate)
                        and not (candidate.source_id or candidate.barcode)
                    )
                    code = (
                        "off_source_identity_missing"
                        if source_identity_missing
                        else "off_low_confidence"
                    )
                    message = (
                        f"Open Food Facts candidate has no source identity for: {query}"
                        if source_identity_missing
                        else f"Open Food Facts candidate is too weak for: {query}"
                    )
                    off_error = NomnomError(
                        code,
                        message,
                        details={
                            "food": query,
                            "threshold": 0.5,
                            "candidate": _candidate_details(candidate, confidence),
                            "alternatives": [
                                _candidate_details(food, score) for food, score in scored[1:]
                            ],
                            "action": EXACT_CAPTURE_ACTION,
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
                    selected = off_matches[0]
                    if selected.brand is None:
                        food = replace(
                            selected,
                            alternatives=alternatives,
                            resolution_mode="generic_proxy",
                            source_id=selected.source_id or selected.barcode,
                            provenance=selected.provenance or "openfoodfacts",
                            assumption=(
                                "Brand not specified; used Open Food Facts generic proxy: "
                                f"{selected.name}."
                            ),
                        )
                        food, confidence = self._apply_generic_proxy_policy(food, confidence)
                    else:
                        food = replace(
                            selected,
                            alternatives=alternatives,
                            resolution_mode="exact_product",
                            source_id=selected.source_id or selected.barcode,
                            provenance=selected.provenance or "openfoodfacts",
                        )
                    self._cache_food(food, lookup_query=query)
                    return food, confidence

        if remote_enabled and credential is not None:
            food, confidence = self.usda_client.resolve(query, credential.value)
            food, confidence = self._prepare_usda_generic_proxy(query, food, confidence)
            self._cache_food(food, lookup_query=query)
            return food, confidence
        raise _food_needs_source_error(
            query,
            provider_error=off_error,
            offline=not remote_enabled,
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
            if food.resolution_mode == "generic_proxy" and not _generic_proxy_query_is_safe(
                query, food
            ):
                continue
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
            if food.resolution_mode == "generic_proxy" and not _generic_proxy_query_is_safe(
                query, food
            ):
                continue
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
            (name, kcal, protein, fat, carbs, piece_grams, piece_grams_source,
             piece_grams_source_value, density_g_ml, source, fdc_id, barcode, brand,
             lookup_query, alternatives_json, resolution_mode, source_id, source_note,
             provenance, assumption)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
              kcal=excluded.kcal,
              protein=excluded.protein,
              fat=excluded.fat,
              carbs=excluded.carbs,
              piece_grams=excluded.piece_grams,
              piece_grams_source=excluded.piece_grams_source,
              piece_grams_source_value=excluded.piece_grams_source_value,
              density_g_ml=excluded.density_g_ml,
              source=excluded.source,
              fdc_id=excluded.fdc_id,
              barcode=excluded.barcode,
              brand=excluded.brand,
              lookup_query=excluded.lookup_query,
              alternatives_json=excluded.alternatives_json,
              resolution_mode=excluded.resolution_mode,
              source_id=excluded.source_id,
              source_note=excluded.source_note,
              provenance=excluded.provenance,
              assumption=excluded.assumption""",
            (
                food.name,
                food.kcal,
                food.protein,
                food.fat,
                food.carbs,
                food.piece_grams,
                food.piece_grams_source,
                food.piece_grams_source_value,
                food.density_g_ml,
                food.source,
                food.fdc_id,
                food.barcode,
                food.brand,
                normalize_name(lookup_query),
                json.dumps(food.alternatives, ensure_ascii=False, sort_keys=True),
                food.resolution_mode,
                food.source_id,
                food.source_note,
                food.provenance,
                food.assumption,
            ),
        )

    def capture_barcode(self, barcode: str) -> Food:
        food = self.off_client.product_by_barcode(barcode)
        exact = replace(
            food,
            source="openfoodfacts",
            barcode=barcode.strip(),
            resolution_mode="exact_product",
            source_id=barcode.strip(),
            provenance="openfoodfacts",
            assumption=None,
        )
        self._cache_food(exact, lookup_query=" ".join(filter(None, (exact.name, exact.brand))))
        return exact

    def capture_label(
        self,
        *,
        name: str,
        brand: str | None,
        kcal: float,
        protein: float,
        fat: float,
        carbs: float,
        serving_grams: float | None,
        source_note: str | None,
    ) -> Food:
        clean_name = " ".join(name.strip().split())
        clean_brand = " ".join((brand or "").strip().split()) or None
        note = " ".join((source_note or "").strip().split())
        if not clean_name:
            raise NomnomError("invalid_product", "Package label name must not be empty")
        if not note or any(ord(character) < 32 for character in note):
            raise NomnomError(
                "invalid_source_note",
                "--source-note is required and must contain a nonempty image/barcode reference",
            )
        nutrients = (kcal, protein, fat, carbs)
        if any(not math.isfinite(value) or value < 0 for value in nutrients):
            raise NomnomError(
                "invalid_nutrition", "Nutrition values must be finite and non-negative"
            )
        if serving_grams is not None and (
            not math.isfinite(serving_grams) or serving_grams <= 0
        ):
            raise NomnomError(
                "invalid_serving_grams",
                "Serving grams must be finite and greater than zero",
            )
        canonical_name = f"{clean_name} — {clean_brand}" if clean_brand else clean_name
        food = Food(
            name=canonical_name,
            kcal=kcal,
            protein=protein,
            fat=fat,
            carbs=carbs,
            piece_grams=serving_grams,
            piece_grams_source=("--serving-grams" if serving_grams is not None else None),
            piece_grams_source_value=(
                f"{serving_grams:g} g" if serving_grams is not None else None
            ),
            source="package_label",
            brand=clean_brand,
            resolution_mode="exact_product",
            source_id=note,
            source_note=note,
            provenance="package_label",
        )
        self._cache_food(food, lookup_query=" ".join(filter(None, (clean_name, clean_brand))))
        return food

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
            piece_grams_source="--piece-grams" if piece_grams is not None else None,
            piece_grams_source_value=(f"{piece_grams:g} g" if piece_grams is not None else None),
            source="user",
            brand=brand.strip(),
            resolution_mode="exact_product",
            provenance="legacy_manual",
        )
        self._cache_food(food, lookup_query=f"{name} {brand}")
        return food
