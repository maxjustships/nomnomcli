from __future__ import annotations

import pytest
import requests

from nomnomcli.errors import NomnomError
from nomnomcli.usda import USDA_SEARCH_URL, USDAClient


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self.payload


def nutrients(*, kcal=180, protein=9, fat=4, carbs=28):
    return [
        {
            "nutrient": {"id": 1008, "name": "Energy", "unitName": "KCAL"},
            "amount": kcal,
        },
        {"nutrientId": 1003, "nutrientName": "Protein", "unitName": "G", "value": protein},
        {
            "nutrientNumber": "204",
            "description": "Total lipid (fat)",
            "unitName": "g",
            "value": fat,
        },
        {
            "nutrientName": "Carbohydrate, by difference",
            "unitName": "grams",
            "value": carbs,
        },
    ]


def record(
    description="Sample legumes, cooked",
    *,
    fdc_id=100,
    data_type="Foundation",
    category="Legumes and legume products",
    food_nutrients=None,
    serving=True,
):
    result = {
        "fdcId": fdc_id,
        "description": description,
        "dataType": data_type,
        "foodCategory": category,
        "foodNutrients": nutrients() if food_nutrients is None else food_nutrients,
    }
    if serving:
        result.update({"servingSize": 45, "servingSizeUnit": "g"})
    return result


def test_usda_uses_official_endpoint_and_parses_actual_nutrient_schema():
    captured = {}

    def get(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return Response({"foods": [record()]})

    food, confidence = USDAClient(request_get=get).resolve(
        "sample legumes cooked", "placeholder"
    )

    assert captured["url"] == USDA_SEARCH_URL
    assert captured["params"] == {
        "api_key": "placeholder",
        "query": "sample legumes cooked",
        "pageSize": 10,
        "dataType": ["Foundation", "SR Legacy"],
    }
    assert (food.kcal, food.protein, food.fat, food.carbs) == (180, 9, 4, 28)
    assert food.fdc_id == 100
    assert food.source == "usda"
    assert confidence >= 0.8


def test_usda_probe_is_minimal_and_invalid_key_is_structured():
    calls = []

    def valid_get(url, **kwargs):
        calls.append((url, kwargs))
        return Response({"foods": []})

    assert USDAClient(request_get=valid_get).probe("placeholder") is True
    assert calls == [
        (
            USDA_SEARCH_URL,
            {
                "params": {"api_key": "placeholder", "query": "a", "pageSize": 1},
                "timeout": 15,
            },
        )
    ]

    invalid = USDAClient(
        request_get=lambda *args, **kwargs: Response({}, status_code=403)
    )
    with pytest.raises(NomnomError) as caught:
        invalid.probe("invalid-placeholder")
    assert caught.value.code == "usda_key_invalid"


@pytest.mark.parametrize("missing_key", ["kcal", "protein", "fat", "carbs"])
def test_usda_rejects_each_zero_or_missing_core_nutrient(missing_key):
    values = {"kcal": 180, "protein": 9, "fat": 4, "carbs": 28}
    values[missing_key] = 0
    candidate = record(
        food_nutrients=nutrients(
            kcal=values["kcal"],
            protein=values["protein"],
            fat=values["fat"],
            carbs=values["carbs"],
        )
    )
    client = USDAClient(request_get=lambda *args, **kwargs: Response({"foods": [candidate]}))

    with pytest.raises(NomnomError) as caught:
        client.resolve("sample legumes cooked", "placeholder")

    assert caught.value.code == "usda_invalid_nutrition"
    assert missing_key in caught.value.details["rejected_candidates"][0][
        "missing_or_nonpositive_core"
    ]


def test_usda_rejects_wrong_energy_unit():
    candidate = record()
    candidate["foodNutrients"][0]["nutrient"]["unitName"] = "KJ"
    client = USDAClient(request_get=lambda *args, **kwargs: Response({"foods": [candidate]}))

    with pytest.raises(NomnomError) as caught:
        client.resolve("sample legumes cooked", "placeholder")

    assert caught.value.code == "usda_invalid_nutrition"
    assert "kcal" in caught.value.details["rejected_candidates"][0][
        "missing_or_nonpositive_core"
    ]


def test_usda_rejects_known_289_kcal_processed_onion_near_match():
    processed = record(
        "Onions, dehydrated flakes",
        data_type="SR Legacy",
        category="Vegetables and vegetable products",
        food_nutrients=nutrients(kcal=289, protein=10.9, fat=1, carbs=70),
    )
    client = USDAClient(request_get=lambda *args, **kwargs: Response({"foods": [processed]}))

    with pytest.raises(NomnomError) as caught:
        client.resolve("onion", "placeholder")

    assert caught.value.code == "usda_low_confidence"
    assert caught.value.details["candidate"]["confidence"] < caught.value.details["threshold"]


def test_usda_prefers_foundation_over_branded_candidate():
    branded = record("Sample meal", fdc_id=1, data_type="Branded", category="Sample")
    foundation = record("Sample meal", fdc_id=2, data_type="Foundation", category="Sample")
    client = USDAClient(
        request_get=lambda *args, **kwargs: Response({"foods": [branded, foundation]})
    )

    food, confidence = client.resolve("sample meal", "placeholder")

    assert food.fdc_id == 2
    assert confidence > food.alternatives[0]["confidence"]
    assert food.alternatives[0]["fdc_id"] == 1


def test_usda_generic_provenance_outranks_more_exact_branded_fdc_candidate():
    branded = record(
        "Peanuts", fdc_id=9001, data_type="Branded", category="Peanuts"
    )
    branded["brandOwner"] = "Example Foods"
    foundation = record(
        "Peanuts, raw", fdc_id=2346380, data_type="Foundation", category="Peanuts"
    )
    captured = {}

    def get(url, **kwargs):
        captured.update(kwargs)
        return Response({"foods": [branded, foundation]})

    food, confidence = USDAClient(request_get=get).resolve("peanuts", "placeholder")

    assert captured["params"]["dataType"] == ["Foundation", "SR Legacy"]
    assert food.fdc_id == 2346380
    assert food.provider_data_type == "Foundation"
    assert food.brand is None
    assert food.source_id == "2346380"
    assert food.provenance == "usda"
    assert confidence >= 0.8


def test_usda_serving_weight_provenance_comes_only_from_returned_fields():
    client = USDAClient(
        request_get=lambda *args, **kwargs: Response({"foods": [record(serving=True)]})
    )
    food, _ = client.resolve("sample legumes cooked", "placeholder")
    assert food.piece_grams == 45
    assert food.piece_grams_source == "servingSize"
    assert food.piece_grams_source_value == "45 g"

    without_serving = USDAClient(
        request_get=lambda *args, **kwargs: Response({"foods": [record(serving=False)]})
    )
    food_without_serving, _ = without_serving.resolve(
        "sample legumes cooked", "placeholder"
    )
    assert food_without_serving.piece_grams is None
    assert food_without_serving.piece_grams_source is None
