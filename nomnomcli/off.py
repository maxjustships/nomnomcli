from __future__ import annotations

import math

import requests

from nomnomcli.errors import NomnomError
from nomnomcli.models import Food

OFF_SEARCH_URL = "https://world.openfoodfacts.org/api/v2/search"
OFF_FIELDS = "product_name,brands,nutriments,code,serving_size"


def _number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def _normalize_product(product: dict) -> Food | None:
    product_name = str(product.get("product_name") or "").strip()
    if not product_name:
        return None
    brand = str(product.get("brands") or "").strip() or None
    nutriments = product.get("nutriments")
    if not isinstance(nutriments, dict):
        return None

    kcal = _number(nutriments.get("energy-kcal_100g"))
    if kcal is None:
        energy_kj = _number(nutriments.get("energy_100g"))
        kcal = energy_kj / 4.184 if energy_kj is not None else None
    protein = _number(nutriments.get("proteins_100g"))
    fat = _number(nutriments.get("fat_100g"))
    carbs = _number(nutriments.get("carbohydrates_100g"))
    if kcal is None and all(value is None for value in (protein, fat, carbs)):
        return None
    protein = protein or 0.0
    fat = fat or 0.0
    carbs = carbs or 0.0
    kcal = kcal if kcal is not None else 4 * protein + 9 * fat + 4 * carbs

    display_name = product_name
    if brand and brand.casefold() not in product_name.casefold():
        display_name = f"{product_name} — {brand}"
    barcode = str(product.get("code") or "").strip() or None
    return Food(
        name=display_name,
        kcal=kcal,
        protein=protein,
        fat=fat,
        carbs=carbs,
        source="openfoodfacts",
        fdc_id=None,
        barcode=barcode,
        brand=brand,
    )


class OpenFoodFactsClient:
    def search(self, query: str, page_size: int = 5) -> list[Food]:
        details = {
            "food": query,
            "offline_escape": (
                "Pin the label values with nomnom add --name NAME --brand BRAND "
                "--kcal KCAL --protein P --fat F --carbs C"
            ),
        }
        try:
            response = requests.get(
                OFF_SEARCH_URL,
                params={
                    "search_terms": query,
                    "fields": OFF_FIELDS,
                    "page_size": page_size,
                },
                timeout=10,
                headers={
                    "User-Agent": "nomnomcli/0.2 (+https://github.com/maxjustships/nomnomcli)"
                },
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None:
                details["status"] = status
                details["reason"] = "http_error"
            else:
                details["reason"] = "network_error"
            raise NomnomError(
                "openfoodfacts_unavailable",
                "Open Food Facts lookup is unavailable",
                details=details,
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise NomnomError(
                "openfoodfacts_invalid_response",
                "Open Food Facts returned malformed JSON",
                details=details,
            ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
            raise NomnomError(
                "openfoodfacts_invalid_response",
                "Open Food Facts returned an invalid product payload",
                details=details,
            )
        return [
            food
            for product in payload["products"]
            if isinstance(product, dict) and (food := _normalize_product(product)) is not None
        ]
