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
    source: str = "bundled"
    fdc_id: int | None = None


@dataclass(frozen=True, slots=True)
class ResolvedItem:
    name: str
    grams: float
    kcal: float
    protein: float
    fat: float
    carbs: float
    match_confidence: float

    def to_dict(self) -> dict[str, str | float]:
        return asdict(self)


NUTRIENT_KEYS = ("kcal", "protein", "fat", "carbs")


def round_nutrition(value: float) -> float:
    return round(value + 1e-12, 2)


def scale_food(food: Food, grams: float, confidence: float) -> ResolvedItem:
    factor = grams / 100.0
    return ResolvedItem(
        name=food.name,
        grams=round_nutrition(grams),
        kcal=round_nutrition(food.kcal * factor),
        protein=round_nutrition(food.protein * factor),
        fat=round_nutrition(food.fat * factor),
        carbs=round_nutrition(food.carbs * factor),
        match_confidence=round(confidence, 2),
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
