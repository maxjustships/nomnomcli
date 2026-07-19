from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class Food:
    name: str
    kcal: float
    protein: float
    fat: float
    carbs: float
    piece_grams: float | None = None
    density_g_ml: float | None = None
    source: str = "unknown"
    fdc_id: int | None = None
    barcode: str | None = None
    brand: str | None = None
    categories: tuple[str, ...] = ()
    alternatives: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedItem:
    name: str
    grams: float
    kcal: float
    protein: float
    fat: float
    carbs: float
    match_confidence: float
    assumed: bool | None = None
    assumption: str | None = None
    source: str | None = None
    barcode: str | None = None
    brand: str | None = None
    alternatives: tuple[dict[str, str], ...] | None = None

    def to_dict(self) -> dict[str, str | float | bool]:
        return {key: value for key, value in asdict(self).items() if value is not None}


NUTRIENT_KEYS = ("kcal", "protein", "fat", "carbs")


def round_nutrition(value: float) -> float:
    return round(value + 1e-12, 2)


def scale_food(
    food: Food,
    grams: float,
    confidence: float,
    *,
    assumed: bool | None = None,
    assumption: str | None = None,
) -> ResolvedItem:
    factor = grams / 100.0
    is_branded = food.source in {"openfoodfacts", "user"}
    return ResolvedItem(
        name=food.name,
        grams=round_nutrition(grams),
        kcal=round_nutrition(food.kcal * factor),
        protein=round_nutrition(food.protein * factor),
        fat=round_nutrition(food.fat * factor),
        carbs=round_nutrition(food.carbs * factor),
        match_confidence=round(confidence, 2),
        assumed=assumed,
        assumption=assumption,
        source=food.source if is_branded else None,
        barcode=food.barcode,
        brand=food.brand,
        alternatives=food.alternatives or None,
    )


def total_items(items: list[ResolvedItem] | list[dict]) -> dict[str, float]:
    return {
        key: round_nutrition(
            sum(
                float(item[key] if isinstance(item, dict) else getattr(item, key)) for item in items
            )
        )
        for key in NUTRIENT_KEYS
    }
