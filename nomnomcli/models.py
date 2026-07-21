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
    piece_grams_source: str | None = None
    piece_grams_source_value: str | None = None
    density_g_ml: float | None = None
    source: str = "unknown"
    fdc_id: int | None = None
    barcode: str | None = None
    brand: str | None = None
    categories: tuple[str, ...] = ()
    alternatives: tuple[dict[str, str], ...] = ()
    resolution_mode: str = "legacy"
    source_id: str | None = None
    source_note: str | None = None
    provenance: str | None = None
    assumption: str | None = None
    provider_data_type: str | None = None


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
    fdc_id: int | None = None
    barcode: str | None = None
    brand: str | None = None
    alternatives: tuple[dict[str, str], ...] | None = None
    resolution_mode: str | None = None
    source_id: str | None = None
    source_note: str | None = None
    provenance: str | None = None
    approximate: bool | None = None
    portion_provenance: str | None = None
    portion_estimate: dict | None = None

    def to_dict(self) -> dict:
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
    portion_estimate: dict | None = None,
) -> ResolvedItem:
    factor = grams / 100.0
    assumptions = [value for value in (food.assumption, assumption) if value]
    return ResolvedItem(
        name=food.name,
        grams=round_nutrition(grams),
        kcal=round_nutrition(food.kcal * factor),
        protein=round_nutrition(food.protein * factor),
        fat=round_nutrition(food.fat * factor),
        carbs=round_nutrition(food.carbs * factor),
        match_confidence=round(confidence, 2),
        assumed=assumed if assumed is not None else (True if food.assumption else None),
        assumption="; ".join(assumptions) if assumptions else None,
        source=food.source if food.source != "unknown" else None,
        fdc_id=food.fdc_id,
        barcode=food.barcode,
        brand=food.brand,
        alternatives=food.alternatives or None,
        resolution_mode=food.resolution_mode,
        source_id=food.source_id,
        source_note=food.source_note,
        provenance=food.provenance,
        approximate=True if portion_estimate is not None else None,
        portion_provenance=(
            str(portion_estimate["method"]) if portion_estimate is not None else None
        ),
        portion_estimate=portion_estimate,
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
