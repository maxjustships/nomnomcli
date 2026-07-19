from __future__ import annotations

import math
import re

import requests

from nomnomcli import __version__
from nomnomcli.errors import NomnomError
from nomnomcli.models import Food

OFF_SEARCH_URL = "https://world.openfoodfacts.org/api/v2/search"
OFF_FIELDS = "product_name,brands,nutriments,code,serving_size,categories,categories_tags"


def _number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def _serving_grams(value) -> float | None:
    matches = re.findall(r"(\d+(?:[.,]\d+)?)\s*(?:g|gr|grams?|г|гр)(?!\w)", str(value), re.I)
    if not matches:
        return None
    grams = _number(matches[-1].replace(",", "."))
    return grams if grams is not None and grams > 0 else None


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
    nutrients = (kcal, protein, fat, carbs)
    if any(value is None or value <= 0 for value in nutrients):
        return None

    display_name = product_name
    if brand and brand.casefold() not in product_name.casefold():
        display_name = f"{product_name} — {brand}"
    barcode = str(product.get("code") or "").strip() or None
    raw_categories = product.get("categories_tags")
    categories = [str(product.get("categories") or "").strip()]
    if isinstance(raw_categories, list):
        categories.extend(str(value).replace(":", " ") for value in raw_categories)
    return Food(
        name=display_name,
        kcal=kcal,
        protein=protein,
        fat=fat,
        carbs=carbs,
        piece_grams=_serving_grams(product.get("serving_size")),
        source="openfoodfacts",
        fdc_id=None,
        barcode=barcode,
        brand=brand,
        categories=tuple(value for value in categories if value),
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
                    "User-Agent": (
                        f"nomnomcli/{__version__} "
                        "(+https://github.com/maxjustships/nomnomcli)"
                    )
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
