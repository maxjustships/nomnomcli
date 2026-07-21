from __future__ import annotations

import re
from fractions import Fraction

from nomnomcli.errors import NomnomError
from nomnomcli.foods import FoodRepository
from nomnomcli.models import ResolvedItem, scale_food
from nomnomcli.portions import (
    PortionEstimate,
    PortionEstimateSet,
    estimate_required_error,
)

NUMBER = r"(?:\d+(?:[.,]\d+)?|\d+\s+\d+/\d+|\d+/\d+)"


def _alias_pattern(values) -> str:
    ordered = sorted(values, key=lambda value: (-len(value), value))
    return "|".join(re.escape(value) for value in ordered)


UNIT_ALIASES = {
    "kilogram": ("kg", "кг", "kilogram", "kilograms", "килограмм", "килограмма", "килограммов"),
    "gram": ("g", "gr", "gram", "grams", "гр", "г", "грамм", "грамма", "граммов"),
    "milliliter": (
        "ml",
        "milliliter",
        "milliliters",
        "мл",
        "миллилитр",
        "миллилитра",
        "миллилитров",
    ),
    "piece": (
        "piece",
        "pieces",
        "pc",
        "pcs",
        "штука",
        "штуки",
        "штук",
        "кусок",
        "куска",
        "кусков",
        "порция",
        "порции",
        "порций",
    ),
}
UNIT_BY_ALIAS = {
    alias.casefold().replace("ё", "е"): unit
    for unit, aliases in UNIT_ALIASES.items()
    for alias in aliases
}
UNIT = _alias_pattern(UNIT_BY_ALIAS)
MASS_UNIT = _alias_pattern(UNIT_ALIASES["gram"])
PIECE_UNIT = _alias_pattern(UNIT_ALIASES["piece"])
EACH_MARKERS = ("at", "each", "по")
LEADING_CONNECTORS = ("of",)
TRAILING_QUANTITY = re.compile(
    rf"^(?P<food>.+?)\s+(?P<amount>{NUMBER})\s*(?P<unit>{UNIT})$", re.IGNORECASE
)
LEADING_QUANTITY = re.compile(
    rf"^(?P<amount>{NUMBER})\s*(?P<unit>{UNIT})\s+"
    rf"(?:(?:{_alias_pattern(LEADING_CONNECTORS)})\s+)?(?P<food>.+)$",
    re.IGNORECASE,
)
PER_PIECE_QUANTITY = re.compile(
    rf"^(?P<food>.+?)\s+(?P<amount>{NUMBER})\s*"
    rf"(?P<unit>{PIECE_UNIT})\s+"
    rf"(?:{_alias_pattern(EACH_MARKERS)})\s+(?P<each>{NUMBER})\s*"
    rf"(?P<mass_unit>{MASS_UNIT})$",
    re.IGNORECASE,
)
LEADING_PER_PIECE_QUANTITY = re.compile(
    rf"^(?P<amount>{NUMBER})\s*(?P<unit>{PIECE_UNIT})\s+"
    rf"(?P<food>.+?)\s+(?:{_alias_pattern(EACH_MARKERS)})\s+"
    rf"(?P<each>{NUMBER})\s*(?P<mass_unit>{MASS_UNIT})$",
    re.IGNORECASE,
)
BARE_PIECE_COUNT = re.compile(
    rf"^(?P<amount>{NUMBER})\s+(?P<food>.+)$", re.IGNORECASE
)

SIZE_ALIASES = {
    "small": {
        "небольшой",
        "небольшая",
        "небольшое",
        "небольшого",
        "небольших",
        "маленький",
        "маленькая",
        "маленькое",
        "маленького",
        "маленьких",
        "small",
    },
    "medium": {
        "средний",
        "средняя",
        "среднее",
        "среднего",
        "средней",
        "средних",
        "medium",
    },
    "large": {
        "крупный",
        "крупная",
        "крупное",
        "крупного",
        "крупной",
        "крупных",
        "large",
    },
}
SIZE_BY_ALIAS = {alias: size for size, aliases in SIZE_ALIASES.items() for alias in aliases}
FRACTION_ALIASES = {
    "половина": 0.5,
    "половины": 0.5,
    "half": 0.5,
    "1/2": 0.5,
    "четверть": 0.25,
    "quarter": 0.25,
}
FRACTION_PATTERN = _alias_pattern(FRACTION_ALIASES)
DESCRIPTOR_PIECE = re.compile(
    rf"^(?:(?P<amount>{NUMBER}|{FRACTION_PATTERN})\s+)?"
    rf"(?P<size>{'|'.join(sorted(SIZE_BY_ALIAS, key=lambda value: (-len(value), value)))})\s+"
    r"(?P<food>.+)$",
    re.IGNORECASE,
)
FRACTION_PIECE = re.compile(
    rf"^(?P<amount>{FRACTION_PATTERN})\s+(?P<food>.+)$",
    re.IGNORECASE,
)
DISH_PREFIX_ALIASES = ("яичница из", "омлет из", "салат из", "каша из")
DISH_CONJUNCTION_ALIASES = ("and", "и")
DISH_PREFIX = re.compile(rf"^(?:{_alias_pattern(DISH_PREFIX_ALIASES)})\s+", re.IGNORECASE)

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
    unit_kind = UNIT_BY_ALIAS[unit.casefold().replace("ё", "е")]
    if unit_kind == "kilogram":
        return amount * 1000
    if unit_kind == "milliliter":
        return amount * (food.density_g_ml or 1.0)
    if unit_kind == "piece":
        if food.piece_grams is None:
            raise NomnomError(
                "piece_weight_unknown",
                f"No deterministic piece weight for {food.name}; provide grams",
                details={
                    "food": food.name,
                    "pieces": amount,
                    "provider": food.source,
                    "source_fields_checked": ["serving_size", "servingSize", "foodMeasures"],
                    "action": "Provide exact grams",
                },
            )
        return amount * food.piece_grams
    return amount


def _format_amount(value: float) -> str:
    if value == 0.5:
        return "1/2"
    if value == 0.25:
        return "1/4"
    return str(int(value)) if value.is_integer() else str(value)


def _format_grams(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(round(value, 2))


def _estimate_item(food, confidence: float, estimate: PortionEstimate) -> ResolvedItem:
    return scale_food(
        food,
        estimate.grams,
        confidence,
        assumed=True,
        assumption=estimate.assumption,
        portion_estimate=estimate.portion_dict(),
    )


def _parse_descriptor_piece(
    cleaned: str,
    repository: FoodRepository,
    *,
    portion_policy: str,
    portion_estimate: PortionEstimate | None,
    item_index: int,
    input_phrase: str,
) -> ResolvedItem | None:
    match = DESCRIPTOR_PIECE.match(cleaned)
    size = None
    if not match:
        match = FRACTION_PIECE.match(cleaned)
        if not match:
            return None
        size = "medium"
    else:
        size = SIZE_BY_ALIAS[match.group("size").casefold().replace("ё", "е")]

    amount_text = match.group("amount")
    amount = FRACTION_ALIASES.get(amount_text.casefold()) if amount_text else 1.0
    if amount is None:
        amount = parse_number(amount_text)
    if amount <= 0:
        raise NomnomError("invalid_quantity", "Quantity must be greater than zero")

    food_query = " ".join(match.group("food").split())
    food, confidence = repository.resolve(food_query)
    if portion_estimate is not None:
        return _estimate_item(food, confidence, portion_estimate)
    if food.piece_grams is not None and (
        not food.piece_grams_source or not food.piece_grams_source_value
    ):
        if portion_policy != "strict":
            raise estimate_required_error(portion_policy, item_index, input_phrase)
        raise NomnomError(
            "piece_weight_unknown",
            f"Serving-weight provenance is missing for {food.name}; provide grams",
            details={
                "food": food.name,
                "pieces": amount,
                "provider": food.source,
                "reason": "serving_weight_provenance_missing",
                "action": "Provide exact grams",
            },
        )
    if food.piece_grams is None and portion_policy != "strict":
        raise estimate_required_error(portion_policy, item_index, input_phrase)
    grams = _quantity_to_grams(amount, "pieces", food)
    assumption = (
        f"{_format_amount(amount)} {size} {food_query} = {_format_grams(grams)}g "
        f"(source: {food.source}.{food.piece_grams_source}="
        f"{food.piece_grams_source_value})"
    )
    return scale_food(
        food,
        grams,
        confidence,
        assumed=True,
        assumption=assumption,
    )


def parse_item_phrase(
    phrase: str,
    repository: FoodRepository,
    *,
    portion_policy: str = "strict",
    portion_estimate: PortionEstimate | None = None,
    item_index: int = 0,
    input_phrase: str | None = None,
) -> ResolvedItem:
    cleaned = " ".join(phrase.strip().split())
    exact_input = phrase.strip() if input_phrase is None else input_phrase
    descriptor_item = _parse_descriptor_piece(
        cleaned,
        repository,
        portion_policy=portion_policy,
        portion_estimate=portion_estimate,
        item_index=item_index,
        input_phrase=exact_input,
    )
    if descriptor_item:
        return descriptor_item
    per_piece = PER_PIECE_QUANTITY.match(cleaned) or LEADING_PER_PIECE_QUANTITY.match(
        cleaned
    )
    if per_piece:
        food, confidence = repository.resolve(per_piece.group("food").strip(" -"))
        amount = parse_number(per_piece.group("amount"))
        each = parse_number(per_piece.group("each"))
        if amount <= 0 or each <= 0:
            raise NomnomError("invalid_quantity", "Quantity must be greater than zero")
        return scale_food(food, amount * each, confidence)
    match = TRAILING_QUANTITY.match(cleaned)
    if not match:
        bare_count = BARE_PIECE_COUNT.match(cleaned)
        if bare_count:
            amount = parse_number(bare_count.group("amount"))
            if amount <= 0:
                raise NomnomError("invalid_quantity", "Quantity must be greater than zero")
            food, confidence = repository.resolve(bare_count.group("food").strip(" -"))
            if portion_estimate is not None:
                return _estimate_item(food, confidence, portion_estimate)
            if food.piece_grams is None and portion_policy != "strict":
                raise estimate_required_error(portion_policy, item_index, exact_input)
            grams = _quantity_to_grams(amount, "pieces", food)
            return scale_food(food, grams, confidence)
        raise NomnomError(
            "quantity_required",
            f"A quantity with unit is required: {cleaned}",
            details={"item": cleaned, "examples": ["rice 150 g", "хлеб 2 куска"]},
        )
    food, confidence = repository.resolve(match.group("food").strip(" -"))
    amount = parse_number(match.group("amount"))
    if amount <= 0:
        raise NomnomError("invalid_quantity", "Quantity must be greater than zero")
    unit_kind = UNIT_BY_ALIAS[match.group("unit").casefold().replace("ё", "е")]
    if portion_estimate is not None and unit_kind == "piece":
        return _estimate_item(food, confidence, portion_estimate)
    if unit_kind == "piece" and food.piece_grams is None and portion_policy != "strict":
        raise estimate_required_error(portion_policy, item_index, exact_input)
    grams = _quantity_to_grams(amount, match.group("unit"), food)
    return scale_food(food, grams, confidence)


def parse_free_text(
    text: str,
    repository: FoodRepository,
    *,
    portion_policy: str = "strict",
    portion_estimates: PortionEstimateSet | None = None,
) -> list[ResolvedItem]:
    cleaned_text = text.strip()
    dish = DISH_PREFIX.match(cleaned_text)
    if dish:
        cleaned_text = cleaned_text[dish.end() :]
        separator = rf"[,;\n]+|\s+(?:{_alias_pattern(DISH_CONJUNCTION_ALIASES)})\s+"
    else:
        separator = r"[,;\n]+"
    phrases = [part.strip() for part in re.split(separator, cleaned_text) if part.strip()]
    if not phrases:
        raise NomnomError("empty_input", "No food items were provided")
    items = []
    for index, phrase in enumerate(phrases):
        try:
            estimate = (
                portion_estimates.entry_for(index, phrase)
                if portion_estimates is not None
                else None
            )
            item = parse_item_phrase(
                phrase,
                repository,
                portion_policy=portion_policy,
                portion_estimate=estimate,
                item_index=index,
                input_phrase=phrase,
            )
            items.append(item)
            if estimate is not None and item.portion_provenance is not None:
                portion_estimates.mark_used(index)
        except NomnomError as exc:
            exc.details.setdefault("item_index", index)
            exc.details.setdefault("input", phrase)
            raise
    if portion_estimates is not None:
        portion_estimates.ensure_all_used()
    return items


def parse_recipe_ingredient(text: str, repository: FoodRepository) -> ResolvedItem:
    cleaned = " ".join(text.strip().split())
    match = LEADING_QUANTITY.match(cleaned)
    if match:
        reordered = f"{match.group('food')} {match.group('amount')} {match.group('unit')}"
        return parse_item_phrase(reordered, repository)
    return parse_item_phrase(cleaned, repository)
