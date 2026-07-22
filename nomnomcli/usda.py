from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from dataclasses import replace

import requests

from nomnomcli.errors import NomnomError, ProviderUnavailableError
from nomnomcli.models import Food
from nomnomcli.providers import RetryPolicy, request_with_retry

USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
USDA_FOOD_URL = "https://api.nal.usda.gov/fdc/v1/food/{fdc_id}"
USDA_CONFIDENCE_FLOOR = 0.8

_NUTRIENT_SPECS = {
    "kcal": {
        "ids": {1008},
        "numbers": {"208"},
        "names": {"energy"},
        "units": {"kcal"},
    },
    "protein": {
        "ids": {1003},
        "numbers": {"203"},
        "names": {"protein"},
        "units": {"g", "gram", "grams"},
    },
    "fat": {
        "ids": {1004},
        "numbers": {"204"},
        "names": {"total lipid (fat)", "total fat", "fat"},
        "units": {"g", "gram", "grams"},
    },
    "carbs": {
        "ids": {1005},
        "numbers": {"205"},
        "names": {"carbohydrate, by difference", "carbohydrate"},
        "units": {"g", "gram", "grams"},
    },
}
_DATA_TYPE_QUALITY = {
    "foundation": 1.0,
    "sr legacy": 0.95,
    "survey (fndds)": 0.55,
    "branded": 0.35,
}


def _tokens(value: str) -> set[str]:
    tokens = set()
    for raw in re.findall(r"\w+(?:['’]\w+)*", value.casefold()):
        token = (
            raw[:-1]
            if re.fullmatch(r"[a-z]+", raw) and len(raw) > 3 and raw.endswith("s")
            else raw
        )
        tokens.add(token)
    return tokens


def _number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _nutrient_metadata(item: dict) -> tuple[int | None, str, str, str, float | None]:
    nested = item.get("nutrient") if isinstance(item.get("nutrient"), dict) else {}
    raw_id = item.get("nutrientId", nested.get("id"))
    try:
        nutrient_id = int(raw_id)
    except (TypeError, ValueError):
        nutrient_id = None
    number = str(item.get("nutrientNumber", nested.get("number", ""))).strip()
    name = str(
        item.get("nutrientName")
        or item.get("description")
        or nested.get("name")
        or nested.get("description")
        or ""
    ).casefold().strip()
    unit = str(item.get("unitName") or nested.get("unitName") or "").casefold().strip()
    value = _number(item.get("value", item.get("amount")))
    return nutrient_id, number, name, unit, value


def _core_nutrients(record: dict) -> tuple[dict[str, float], list[str]]:
    nutrients: dict[str, float] = {}
    raw_nutrients = record.get("foodNutrients")
    if not isinstance(raw_nutrients, list):
        return nutrients, list(_NUTRIENT_SPECS)
    for item in raw_nutrients:
        if not isinstance(item, dict):
            continue
        nutrient_id, number, name, unit, value = _nutrient_metadata(item)
        if value is None:
            continue
        for key, spec in _NUTRIENT_SPECS.items():
            identity_match = (
                nutrient_id in spec["ids"]
                or number in spec["numbers"]
                or name in spec["names"]
            )
            if identity_match and unit in spec["units"]:
                nutrients.setdefault(key, value)
                break
    missing = [key for key in _NUTRIENT_SPECS if key not in nutrients]
    return nutrients, missing


def _serving_weight(record: dict) -> tuple[float | None, str | None, str | None]:
    unit = str(record.get("servingSizeUnit") or "").casefold().strip()
    serving_size = _number(record.get("servingSize"))
    if serving_size is not None and unit in {"g", "gram", "grams"}:
        return serving_size, "servingSize", f"{serving_size:g} {unit}"
    measures = record.get("foodMeasures")
    if isinstance(measures, list):
        for index, measure in enumerate(measures):
            if not isinstance(measure, dict):
                continue
            gram_weight = _number(measure.get("gramWeight"))
            if gram_weight is not None:
                return gram_weight, f"foodMeasures[{index}].gramWeight", f"{gram_weight:g} g"
    return None, None, None


def _normalize_record(record: dict) -> tuple[Food | None, list[str]]:
    description = str(record.get("description") or "").strip()
    if not description:
        return None, list(_NUTRIENT_SPECS)
    nutrients, missing = _core_nutrients(record)
    if missing:
        return None, missing
    piece_grams, source_field, source_value = _serving_weight(record)
    category = str(record.get("foodCategory") or "").strip()
    food = Food(
        name=description.casefold(),
        kcal=nutrients["kcal"],
        protein=nutrients["protein"],
        fat=nutrients["fat"],
        carbs=nutrients["carbs"],
        piece_grams=piece_grams,
        piece_grams_source=source_field,
        piece_grams_source_value=source_value,
        source="usda",
        fdc_id=int(record["fdcId"]) if record.get("fdcId") is not None else None,
        source_id=(str(record["fdcId"]) if record.get("fdcId") is not None else None),
        provenance="usda",
        provider_data_type=str(record.get("dataType") or "").strip() or None,
        brand=str(record.get("brandOwner") or "").strip() or None,
        categories=(category,) if category else (),
    )
    return food, []


def _confidence(query: str, food: Food, data_type: str) -> float:
    query_tokens = _tokens(query)
    candidate_tokens = _tokens(" ".join((food.name, food.brand or "")))
    if not query_tokens or not candidate_tokens:
        return 0.0
    overlap = query_tokens & candidate_tokens
    coverage = len(overlap) / len(query_tokens)
    precision = len(overlap) / len(candidate_tokens)
    data_quality = _DATA_TYPE_QUALITY.get(data_type.casefold(), 0.5)
    category_tokens = _tokens(" ".join(food.categories))
    category_quality = (
        1.0 if query_tokens & category_tokens else 0.5 if category_tokens else 0.0
    )
    return 0.5 * coverage + 0.3 * precision + 0.15 * data_quality + 0.05 * category_quality


def _candidate_details(food: Food, data_type: str, confidence: float) -> dict:
    return {
        key: value
        for key, value in {
            "name": food.name,
            "fdc_id": food.fdc_id,
            "data_type": data_type or None,
            "category": food.categories[0] if food.categories else None,
            "confidence": round(confidence, 2),
        }.items()
        if value is not None
    }


class USDAClient:
    def __init__(
        self,
        *,
        request_get: Callable | None = None,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._request_get = request_get
        self.retry_policy = retry_policy or RetryPolicy()
        self.sleep = sleep

    def _payload(
        self,
        query: str,
        api_key: str,
        page_size: int,
        *,
        data_types: list[str] | None = None,
    ) -> dict:
        details = {"food": query}
        params = {"api_key": api_key, "query": query, "pageSize": page_size}
        if data_types is not None:
            params["dataType"] = data_types
        response = request_with_retry(
            provider="usda",
            code="usda_unavailable",
            message="USDA FoodData Central lookup is unavailable",
            request_get=self._request_get or requests.get,
            url=USDA_SEARCH_URL,
            request_kwargs={
                "params": params,
                "timeout": 15,
            },
            details=details,
            retry_policy=self.retry_policy,
            sleep=self.sleep,
        )
        if response.status_code in {401, 403}:
            raise NomnomError(
                "usda_key_invalid",
                "USDA FoodData Central rejected the API key",
                details={"setup_url": "https://fdc.nal.usda.gov/api-key-signup.html"},
            )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ProviderUnavailableError(
                "usda",
                "usda_unavailable",
                "USDA FoodData Central lookup is unavailable",
                retryable=False,
                details={**details, "status": response.status_code, "reason": "http_error"},
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise NomnomError(
                "usda_invalid_response",
                "USDA FoodData Central returned malformed JSON",
                details=details,
            ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("foods"), list):
            raise NomnomError(
                "usda_invalid_response",
                "USDA FoodData Central returned an invalid search payload",
                details=details,
            )
        return payload

    def probe(self, api_key: str) -> bool:
        self._payload("a", api_key, 1)
        return True

    def candidates(self, query: str, api_key: str) -> list[tuple[Food, float]]:
        records = self._payload(
            query,
            api_key,
            10,
            data_types=["Foundation", "SR Legacy"],
        )["foods"]
        candidates = []
        for record in records:
            if not isinstance(record, dict):
                continue
            food, missing = _normalize_record(record)
            if food is None or missing:
                continue
            data_type = str(record.get("dataType") or "").strip()
            candidates.append((food, _confidence(query, food, data_type)))
        candidates.sort(
            key=lambda item: (
                0
                if item[0].brand is None
                and (item[0].provider_data_type or "").casefold() in {"foundation", "sr legacy"}
                else 1,
                -item[1],
                -_DATA_TYPE_QUALITY.get((item[0].provider_data_type or "").casefold(), 0.5),
                item[0].name,
                item[0].fdc_id or 0,
            )
        )
        return candidates

    def food_by_fdc_id(self, fdc_id: int, api_key: str) -> Food:
        if isinstance(fdc_id, bool) or not isinstance(fdc_id, int) or fdc_id <= 0:
            raise NomnomError("invalid_fdc_id", "FDC id must be a positive integer")
        details = {"fdc_id": fdc_id}
        response = request_with_retry(
            provider="usda",
            code="usda_unavailable",
            message="USDA FoodData Central lookup is unavailable",
            request_get=self._request_get or requests.get,
            url=USDA_FOOD_URL.format(fdc_id=fdc_id),
            request_kwargs={"params": {"api_key": api_key}, "timeout": 15},
            details=details,
            retry_policy=self.retry_policy,
            sleep=self.sleep,
        )
        if response.status_code in {401, 403}:
            raise NomnomError(
                "usda_key_invalid",
                "USDA FoodData Central rejected the API key",
                details={"setup_url": "https://fdc.nal.usda.gov/api-key-signup.html"},
            )
        if response.status_code == 404:
            raise NomnomError(
                "usda_food_not_found",
                f"USDA has no food for FDC id: {fdc_id}",
                details=details,
            )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ProviderUnavailableError(
                "usda",
                "usda_unavailable",
                "USDA FoodData Central lookup is unavailable",
                retryable=False,
                details={**details, "status": response.status_code, "reason": "http_error"},
            ) from exc
        try:
            record = response.json()
        except ValueError as exc:
            raise NomnomError(
                "usda_invalid_response",
                "USDA FoodData Central returned malformed JSON",
                details=details,
            ) from exc
        if not isinstance(record, dict):
            raise NomnomError(
                "usda_invalid_response",
                "USDA FoodData Central returned an invalid food payload",
                details=details,
            )
        food, missing = _normalize_record(record)
        if food is None:
            raise NomnomError(
                "usda_invalid_nutrition",
                "USDA food lacks complete positive core nutrition",
                details={**details, "missing_or_nonpositive_core": missing},
            )
        if food.fdc_id != fdc_id:
            raise NomnomError(
                "usda_food_mismatch",
                "USDA food id does not match the requested FDC id",
                details={**details, "returned_fdc_id": food.fdc_id},
            )
        return food

    def resolve(self, query: str, api_key: str) -> tuple[Food, float]:
        records = self._payload(
            query,
            api_key,
            10,
            data_types=["Foundation", "SR Legacy"],
        )["foods"]
        if not records:
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

        candidates: list[tuple[Food, str, float]] = []
        rejected = []
        for record in records:
            if not isinstance(record, dict):
                continue
            food, missing = _normalize_record(record)
            if food is None:
                rejected.append(
                    {
                        "name": str(record.get("description") or ""),
                        "fdc_id": record.get("fdcId"),
                        "missing_or_nonpositive_core": missing,
                    }
                )
                continue
            data_type = str(record.get("dataType") or "").strip()
            candidates.append((food, data_type, _confidence(query, food, data_type)))

        if not candidates:
            raise NomnomError(
                "usda_invalid_nutrition",
                f"USDA candidates lack complete positive core nutrition for: {query}",
                details={"food": query, "rejected_candidates": rejected},
            )

        candidates.sort(
            key=lambda item: (
                0
                if item[0].brand is None
                and item[1].casefold() in {"foundation", "sr legacy"}
                else 1,
                -item[2],
                -_DATA_TYPE_QUALITY.get(item[1].casefold(), 0.5),
                item[0].name,
                item[0].fdc_id or 0,
            )
        )
        accepted = [
            candidate for candidate in candidates if candidate[2] >= USDA_CONFIDENCE_FLOOR
        ]
        if not accepted:
            candidate = candidates[0]
            raise NomnomError(
                "usda_low_confidence",
                f"USDA candidate is too weak for: {query}",
                details={
                    "food": query,
                    "threshold": USDA_CONFIDENCE_FLOOR,
                    "candidate": _candidate_details(*candidate),
                    "alternatives": [_candidate_details(*item) for item in candidates[1:]],
                    "action": (
                        "Try a more specific food name or pin verified nutrition "
                        "with nomnom add"
                    ),
                },
            )

        selected = accepted[0]
        alternatives = tuple(
            _candidate_details(*item) for item in candidates if item is not selected
        )
        return replace(selected[0], alternatives=alternatives), selected[2]
