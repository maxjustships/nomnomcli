from __future__ import annotations

import re
from fractions import Fraction

from nomnomcli.errors import NomnomError
from nomnomcli.foods import FoodRepository
from nomnomcli.models import ResolvedItem, scale_food

NUMBER = r"(?:\d+(?:[.,]\d+)?|\d+\s+\d+/\d+|\d+/\d+)"
UNIT = (
    r"kg|кг|kilograms?|килограмм(?:а|ов)?|g|gr|grams?|гр|г|грамм(?:а|ов)?|"
    r"ml|мл|milliliters?|миллилитр(?:а|ов)?|"
    r"pieces?|pcs?|шт(?:ук[аи]?)?|куск(?:а|ов)?|кус(?:ок|ка|ков)|порци(?:я|и|й)"
)
TRAILING_QUANTITY = re.compile(
    rf"^(?P<food>.+?)\s+(?P<amount>{NUMBER})\s*(?P<unit>{UNIT})$", re.IGNORECASE
)
COMPACT_QUANTITY = re.compile(
    rf"^(?P<food>.+?)\s+(?P<amount>{NUMBER})\s*(?P<unit>кг|kg|g|gr|гр|г|ml|мл)$",
    re.IGNORECASE,
)
LEADING_QUANTITY = re.compile(
    rf"^(?P<amount>{NUMBER})\s*(?P<unit>{UNIT})\s+(?:of\s+)?(?P<food>.+)$", re.IGNORECASE
)


def parse_number(value: str) -> float:
    normalized = value.replace(",", ".").strip()
    try:
        if " " in normalized and "/" in normalized:
            whole, fraction = normalized.split(maxsplit=1)
            return float(whole) + float(Fraction(fraction))
        if "/" in normalized:
            return float(Fraction(normalized))
        return float(normalized)
    except (ValueError, ZeroDivisionError) as exc:
        raise NomnomError("invalid_quantity", f"Invalid quantity: {value}") from exc


def _quantity_to_grams(amount: float, unit: str, food) -> float:
    normalized = unit.casefold()
    kilogram_units = {
        "kg",
        "кг",
        "kilogram",
        "kilograms",
        "килограмм",
        "килограмма",
        "килограммов",
    }
    if normalized in kilogram_units:
        return amount * 1000
    if normalized.startswith(("ml", "мл", "milliliter", "миллилитр")):
        return amount * (food.density_g_ml or 1.0)
    if normalized.startswith(("piece", "pc", "шт", "куск", "кус", "порци")):
        if food.piece_grams is None:
            raise NomnomError(
                "piece_weight_unknown",
                f"No deterministic piece weight for {food.name}; provide grams",
                details={"food": food.name, "pieces": amount},
            )
        return amount * food.piece_grams
    return amount


def parse_item_phrase(phrase: str, repository: FoodRepository) -> ResolvedItem:
    cleaned = " ".join(phrase.strip().split())
    match = TRAILING_QUANTITY.match(cleaned) or COMPACT_QUANTITY.match(cleaned)
    if not match:
        raise NomnomError(
            "quantity_required",
            f"A quantity with unit is required: {cleaned}",
            details={"item": cleaned, "examples": ["rice 150 g", "хлеб 2 куска"]},
        )
    food, confidence = repository.resolve(match.group("food").strip(" -"))
    amount = parse_number(match.group("amount"))
    if amount <= 0:
        raise NomnomError("invalid_quantity", "Quantity must be greater than zero")
    grams = _quantity_to_grams(amount, match.group("unit"), food)
    return scale_food(food, grams, confidence)


def parse_free_text(text: str, repository: FoodRepository) -> list[ResolvedItem]:
    phrases = [part.strip() for part in re.split(r"[,;\n]+", text) if part.strip()]
    if not phrases:
        raise NomnomError("empty_input", "No food items were provided")
    items = []
    for index, phrase in enumerate(phrases):
        try:
            items.append(parse_item_phrase(phrase, repository))
        except NomnomError as exc:
            exc.details.setdefault("item_index", index)
            exc.details.setdefault("input", phrase)
            raise
    return items


def parse_recipe_ingredient(text: str, repository: FoodRepository) -> ResolvedItem:
    cleaned = " ".join(text.strip().split())
    match = LEADING_QUANTITY.match(cleaned)
    if match:
        reordered = f"{match.group('food')} {match.group('amount')} {match.group('unit')}"
        return parse_item_phrase(reordered, repository)
    return parse_item_phrase(cleaned, repository)
