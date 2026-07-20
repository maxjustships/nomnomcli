from __future__ import annotations

import math
import re
import time
from collections.abc import Callable

import requests

from nomnomcli import __version__
from nomnomcli.errors import NomnomError, ProviderUnavailableError
from nomnomcli.models import Food
from nomnomcli.providers import RetryPolicy, request_with_retry

OFF_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
OFF_PRODUCT_PROBE_URL = "https://api.openfoodfacts.org/api/v2/product/0"
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
        piece_grams_source="serving_size",
        piece_grams_source_value=(
            str(product["serving_size"]) if product.get("serving_size") else None
        ),
        source="openfoodfacts",
        fdc_id=None,
        barcode=barcode,
        brand=brand,
        categories=tuple(value for value in categories if value),
    )


class OpenFoodFactsClient:
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

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                f"nomnomcli/{__version__} "
                "(+https://github.com/maxjustships/nomnomcli)"
            )
        }

    def _get_payload(self, query: str, page_size: int) -> dict:
        details = {
            "food": query,
            "offline_escape": (
                "Pin the label values with nomnom add --name NAME --brand BRAND "
                "--kcal KCAL --protein P --fat F --carbs C"
            ),
        }
        response = request_with_retry(
            provider="openfoodfacts",
            code="openfoodfacts_unavailable",
            message="Open Food Facts full-text search is unavailable",
            request_get=self._request_get or requests.get,
            url=OFF_SEARCH_URL,
            request_kwargs={
                "params": {
                    "search_terms": query,
                    "search_simple": 1,
                    "action": "process",
                    "json": 1,
                    "fields": OFF_FIELDS,
                    "page_size": page_size,
                },
                "timeout": 10,
                "headers": self._headers(),
            },
            details=details,
            retry_policy=self.retry_policy,
            sleep=self.sleep,
        )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            status = getattr(response, "status_code", None)
            raise ProviderUnavailableError(
                "openfoodfacts",
                "openfoodfacts_unavailable",
                "Open Food Facts full-text search is unavailable",
                retryable=False,
                details={**details, "reason": "http_error", "status": status, "attempts": 1},
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
        return payload

    def probe(self) -> bool:
        self._get_payload("nomnom", 1)
        return True

    def probe_product(self) -> bool:
        request_with_retry(
            provider="openfoodfacts",
            code="openfoodfacts_unavailable",
            message="Open Food Facts product lookup is unavailable",
            request_get=self._request_get or requests.get,
            url=OFF_PRODUCT_PROBE_URL,
            request_kwargs={
                "params": {"fields": "code"},
                "timeout": 10,
                "headers": self._headers(),
            },
            details={"capability": "product_lookup"},
            retry_policy=self.retry_policy,
            sleep=self.sleep,
        )
        return True

    def search(self, query: str, page_size: int = 5) -> list[Food]:
        payload = self._get_payload(query, page_size)
        return [
            food
            for product in payload["products"]
            if isinstance(product, dict) and (food := _normalize_product(product)) is not None
        ]
