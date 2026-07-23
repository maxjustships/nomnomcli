from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def nutrients(seed: int) -> list[dict]:
    return [
        {
            "nutrientId": 1008,
            "nutrientName": "Energy",
            "unitName": "KCAL",
            "value": 80 + seed % 240,
        },
        {
            "nutrientId": 1003,
            "nutrientName": "Protein",
            "unitName": "G",
            "value": 2 + seed % 18,
        },
        {
            "nutrientId": 1004,
            "nutrientName": "Total lipid (fat)",
            "unitName": "G",
            "value": 1 + seed % 12,
        },
        {
            "nutrientId": 1005,
            "nutrientName": "Carbohydrate, by difference",
            "unitName": "G",
            "value": 5 + seed % 55,
        },
    ]


def usda_record(identity: str, source_id: int, *, brand: str | None = None) -> dict:
    record = {
        "fdcId": source_id,
        "description": identity,
        "dataType": "Foundation",
        "foodCategory": "Synthetic eval food",
        "foodNutrients": nutrients(source_id),
    }
    if brand is not None:
        record["brandOwner"] = brand
    return record


def off_record(identity: str, barcode: str, brand: str) -> dict:
    seed = int(barcode[-4:])
    return {
        "product_name": identity,
        "brands": brand,
        "code": barcode,
        "categories": "Synthetic eval food",
        "categories_tags": ["en:synthetic-eval-food"],
        "nutriments": {
            "energy-kcal_100g": 100 + seed % 220,
            "proteins_100g": 2 + seed % 16,
            "fat_100g": 1 + seed % 10,
            "carbohydrates_100g": 8 + seed % 50,
        },
    }


def expected(
    outcome: str,
    *,
    max_followups: int,
    text_search: bool,
) -> dict:
    return {
        "outcome": outcome,
        "max_followups": max_followups,
        "text_search_must_be_attempted": text_search,
    }


def make_case(
    *,
    case_id: str,
    category: str,
    profile: str,
    raw_input: str,
    item_inputs: list[str],
    usda_records: list[dict],
    off_records: list[dict] | None = None,
    allowed_refs: list[str],
    allowed_identities: list[str],
    allowed_modes: list[str],
    forbidden_identities: list[str] | None = None,
    forbidden_tokens: list[str] | None = None,
    envelopes: list[list[float] | None] | None = None,
    outcome: str = "complete",
    max_followups: int = 0,
    text_search: bool = True,
    off_status: int = 200,
    usda_status: int = 200,
    refetch_overrides: dict[str, dict] | None = None,
    steps: list[dict] | None = None,
) -> dict:
    return {
        "id": case_id,
        "category": category,
        "profile": profile,
        "raw_input": raw_input,
        "items": [{"input": value} for value in item_inputs],
        "synthetic_providers": {
            "candidates": {
                "openfoodfacts": off_records or [],
                "usda": usda_records,
            },
            "responses": {
                "openfoodfacts_search_status": off_status,
                "usda_search_status": usda_status,
                "refetch_overrides": refetch_overrides or {},
            },
        },
        "allowed_semantic_identities": allowed_identities,
        "allowed_source_refs": allowed_refs,
        "allowed_resolution_modes": allowed_modes,
        "forbidden_identities": forbidden_identities or [],
        "forbidden_tokens": forbidden_tokens or [],
        "gram_envelopes": envelopes or [None for _ in item_inputs],
        "expected": expected(
            outcome,
            max_followups=max_followups,
            text_search=text_search,
        ),
        "steps": steps or [],
    }


def measured_cases(start: int) -> list[dict]:
    names = [
        "apple",
        "banana",
        "plain yogurt",
        "rolled oats",
        "cooked lentils",
        "white rice",
        "tofu",
        "salmon fillet",
        "whole milk",
        "boiled potato",
        "cucumber",
        "carrot",
        "chickpeas",
        "olive oil",
        "cottage cheese",
        "rye bread",
        "ground turkey",
        "green beans",
        "avocado",
        "orange",
    ]
    cases = []
    for index, name in enumerate(names):
        source_id = start + index
        grams = 40 + index * 7
        profile = ("practical", "balanced", "exact")[index % 3]
        item = f"{grams} g {name}"
        cases.append(
            make_case(
                case_id=f"measured-{index + 1:02d}",
                category="measured_generic",
                profile=profile,
                raw_input=item,
                item_inputs=[item],
                usda_records=[usda_record(name, source_id)],
                allowed_refs=[f"usda:{source_id}"],
                allowed_identities=[name],
                allowed_modes=["generic_proxy"],
                forbidden_tokens=["powder", "candy"],
                envelopes=[[grams, grams]],
            )
        )
    return cases


def fuzzy_cases(start: int) -> list[dict]:
    portions = [
        ("a handful of almonds", "almonds"),
        ("half a bowl of porridge", "porridge"),
        ("two slices of sourdough", "sourdough"),
        ("three quarters cup of beans", "beans"),
        ("a small scoop of hummus", "hummus"),
        ("one fist of pasta", "pasta"),
        ("a few walnuts", "walnuts"),
        ("one ladle of soup", "soup"),
        ("a palm of chicken", "chicken"),
        ("half an avocado", "avocado"),
        ("two bites of cheesecake", "cheesecake"),
        ("one glass of kefir", "kefir"),
        ("a thin slice of cheese", "cheese"),
        ("one bowl of cereal", "cereal"),
        ("a spoonful of peanut butter", "peanut butter"),
        ("one mug of cocoa", "cocoa"),
        ("a small handful of raisins", "raisins"),
        ("half a wrap", "wrap"),
        ("one piece of cornbread", "cornbread"),
        ("a large serving of couscous", "couscous"),
    ]
    envelopes = [
        [20, 45],
        [100, 300],
        [40, 120],
        [100, 220],
        None,
        [80, 220],
        [10, 50],
        [100, 350],
        [70, 180],
        None,
        [15, 70],
        [150, 350],
        [10, 40],
        [25, 120],
        None,
        [150, 400],
        [15, 70],
        [30, 220],
        [30, 160],
        None,
    ]
    cases = []
    for index, (item, identity) in enumerate(portions):
        source_id = start + index
        profile = "exact" if index in {4, 9, 14, 19} else ("practical" if index % 2 else "balanced")
        pending = profile == "exact"
        cases.append(
            make_case(
                case_id=f"fuzzy-{index + 1:02d}",
                category="fuzzy_portion",
                profile=profile,
                raw_input=item,
                item_inputs=[item],
                usda_records=[usda_record(identity, source_id)],
                allowed_refs=[] if pending else [f"usda:{source_id}"],
                allowed_identities=[] if pending else [identity],
                allowed_modes=["pending_capture"] if pending else ["generic_proxy"],
                forbidden_tokens=["powder", "cracker"],
                envelopes=[envelopes[index]],
                outcome="pending" if pending else "complete",
                max_followups=1 if pending else 0,
            )
        )
    return cases


def branded_cases(start: int) -> list[dict]:
    specs = [
        ("Harris sandwich bread", "sandwich bread", "Harris"),
        ("North Farm yogurt", "yogurt", "North Farm"),
        ("Blue Peak granola", "granola", "Blue Peak"),
        ("River oat milk", "oat milk", "River"),
        ("Sun Field tofu", "tofu", "Sun Field"),
        ("Acme tomato sauce", "tomato sauce", "Acme"),
        ("Pioneer rye bread", "rye bread", "Pioneer"),
        ("Meadow kefir", "kefir", "Meadow"),
        ("Atlas hummus", "hummus", "Atlas"),
        ("Harbor tuna", "tuna", "Harbor"),
        ("Cedar peanut butter", "peanut butter", "Cedar"),
        ("Orchard apple juice", "apple juice", "Orchard"),
        ("Valley cottage cheese", "cottage cheese", "Valley"),
        ("Morning cornflakes", "cornflakes", "Morning"),
        ("Forest berry yogurt", "berry yogurt", "Forest"),
        ("Golden sandwich bread", "sandwich bread", "Golden"),
        ("Alpine milk", "milk", "Alpine"),
        ("Terra crackers", "crackers", "Terra"),
        ("Coast salmon", "salmon", "Coast"),
        ("Garden pesto", "pesto", "Garden"),
    ]
    cases = []
    for index, (raw_name, identity, brand) in enumerate(specs):
        source_id = start + index
        item = f"{raw_name} 80 g"
        if index == 0:
            barcode = f"02000000{source_id:05d}"[-13:]
            off = [off_record("cheese", barcode, brand)]
            usda = [usda_record(identity, source_id)]
            refs = [f"usda:{source_id}"]
            modes = ["generic_proxy"]
            profile = "practical"
            off_status = 200
        elif index < 5:
            barcode = f"02000000{source_id:05d}"[-13:]
            off = [off_record(identity, barcode, brand)]
            usda = []
            refs = [f"off:{barcode}"]
            modes = ["probable_product"]
            profile = "practical" if index < 4 else "balanced"
            off_status = 200
        else:
            off = []
            usda = [usda_record(identity, source_id)]
            refs = [f"usda:{source_id}"]
            modes = ["generic_proxy"]
            profile = "practical" if index < 19 else "balanced"
            off_status = 503 if 5 <= index < 10 else 200
        cases.append(
            make_case(
                case_id=f"branded-{index + 1:02d}",
                category="branded",
                profile=profile,
                raw_input=item,
                item_inputs=[item],
                usda_records=usda,
                off_records=off,
                allowed_refs=refs,
                allowed_identities=[identity],
                allowed_modes=modes,
                forbidden_identities=["cheese substitute", "milk crackers"],
                forbidden_tokens=["powder", "banana"],
                envelopes=[[80, 80]],
                off_status=off_status,
            )
        )
    return cases


def mixed_cases(start: int) -> list[dict]:
    pairs = [
        ("rice", "beans"),
        ("egg", "toast"),
        ("chicken", "potato"),
        ("tofu", "noodles"),
        ("yogurt", "berries"),
        ("lentils", "carrots"),
        ("salmon", "rice"),
        ("pasta", "tomato sauce"),
        ("oats", "milk"),
        ("hummus", "flatbread"),
        ("turkey", "couscous"),
        ("chickpeas", "cucumber"),
        ("kefir", "banana"),
        ("soup", "rye bread"),
        ("avocado", "boiled egg"),
    ]
    cases = []
    for index, (first, second) in enumerate(pairs):
        first_id = start + index * 2
        second_id = first_id + 1
        first_item = f"voice note uh {90 + index} g {first}"
        second_item = f"then {45 + index} g {second} please"
        cases.append(
            make_case(
                case_id=f"mixed-{index + 1:02d}",
                category="mixed_voice",
                profile="practical" if index % 3 else "balanced",
                raw_input=f"{first_item}; {second_item}",
                item_inputs=[first_item, second_item],
                usda_records=[
                    usda_record(first, first_id),
                    usda_record(second, second_id),
                ],
                allowed_refs=[f"usda:{first_id}", f"usda:{second_id}"],
                allowed_identities=[first, second],
                allowed_modes=["generic_proxy"],
                forbidden_tokens=["powder", "candy"],
                envelopes=[
                    [90 + index, 90 + index],
                    [45 + index, 45 + index],
                ],
            )
        )
    return cases


def cooking_cases(start: int) -> list[dict]:
    names = [
        "roasted chicken edible portion",
        "bone in lamb edible meat",
        "fried fish drained",
        "braised beef without drippings",
        "baked potato flesh and skin",
        "steamed mussel meat",
        "grilled chicken without bone",
        "roast turkey meat with drippings",
        "cooked shrimp peeled",
        "stewed pork edible portion",
    ]
    cases = []
    for index, identity in enumerate(names):
        source_id = start + index
        grams = 110 + index * 5
        item = f"{grams} g {identity}"
        cases.append(
            make_case(
                case_id=f"cooking-{index + 1:02d}",
                category="cooking_yield",
                profile="practical" if index % 2 else "balanced",
                raw_input=item,
                item_inputs=[item],
                usda_records=[usda_record(identity, source_id)],
                allowed_refs=[f"usda:{source_id}"],
                allowed_identities=[identity],
                allowed_modes=["generic_proxy"],
                forbidden_tokens=["raw", "whole carcass"],
                envelopes=[[grams, grams]],
            )
        )
    return cases


def ambiguity_cases(start: int) -> list[dict]:
    cases = []
    specs = [
        ("cooked egg", "50 g cooked egg", ["cooked cheese"]),
        ("milk", "60 g milk", ["chocolate milk", "condensed milk"]),
        ("tomato", "60 g tomato", ["tomato powder"]),
        ("bread", "60 g bread", ["bread crumbs", "bread crackers"]),
        ("yogurt", "60 g yogurt", ["yogurt powder"]),
        ("tofu", "60 g tofu", ["tofu cake"]),
    ]
    for index, (identity, item, adversaries) in enumerate(specs):
        source_id = start + index * 10
        records = [
            *[
                usda_record(adversary, source_id + offset + 1)
                for offset, adversary in enumerate(adversaries)
            ],
            usda_record(identity, source_id),
        ]
        cases.append(
            make_case(
                case_id=f"ambiguity-{index + 1:02d}",
                category="ambiguity_failure",
                profile="practical",
                raw_input=item,
                item_inputs=[item],
                usda_records=records,
                allowed_refs=[f"usda:{source_id}"],
                allowed_identities=[identity],
                allowed_modes=["generic_proxy"],
                forbidden_identities=adversaries,
                forbidden_tokens=adversaries,
                envelopes=[[50, 50]] if index == 0 else [[60, 60]],
            )
        )
    for index in range(6, 8):
        source_id = start + index * 10
        identity = ("egg", "milk")[index - 6]
        adversary = ("cheese", "crackers")[index - 6]
        item = f"one uncertain {identity}"
        cases.append(
            make_case(
                case_id=f"ambiguity-{index + 1:02d}",
                category="ambiguity_failure",
                profile="practical" if index == 6 else "exact",
                raw_input=item,
                item_inputs=[item],
                usda_records=[usda_record(adversary, source_id)],
                allowed_refs=[],
                allowed_identities=[],
                allowed_modes=["pending_capture"],
                forbidden_identities=[adversary],
                forbidden_tokens=[adversary],
                envelopes=[None],
                outcome="pending",
                max_followups=1,
            )
        )
    for index in range(8, 10):
        source_id = start + index * 10
        identity = ("lentils", "rice")[index - 8]
        item = f"70 g {identity}"
        search_record = usda_record(identity, source_id)
        wrong_refetch = usda_record(f"{identity} mismatched source", source_id + 1)
        cases.append(
            make_case(
                case_id=f"ambiguity-{index + 1:02d}",
                category="ambiguity_failure",
                profile="balanced",
                raw_input=item,
                item_inputs=[item],
                usda_records=[search_record],
                allowed_refs=[],
                allowed_identities=[],
                allowed_modes=[],
                forbidden_tokens=["mismatched"],
                envelopes=[None],
                outcome="error",
                max_followups=0,
                refetch_overrides={str(source_id): wrong_refetch},
            )
        )
    return cases


def stateful_cases(start: int) -> list[dict]:
    labels = [
        ("cache poisoning retry", "apple"),
        ("correction retry", "banana"),
        ("provider retry", "oats"),
        ("same source repeat", "lentils"),
        ("pending then resolved", "tofu"),
    ]
    cases = []
    for index, (label, identity) in enumerate(labels):
        source_id = start + index
        first = f"50 g {identity}"
        second = f"75 g {identity}"
        if index == 2:
            first = f"50 g {identity} provider-outage"
        if index == 4:
            first = "one mystery package"
        steps = [
            {"raw_input": first, "expected_outcome": "complete"},
            {"raw_input": second, "expected_outcome": "complete"},
        ]
        if index == 0:
            steps[0]["action_before"] = "seed_poisoned_cache"
        if index == 1:
            steps[0]["action_after"] = "remove_logged_event"
        if index in {2, 4}:
            steps[0]["expected_outcome"] = "pending"
        case = make_case(
                case_id=f"stateful-{index + 1:02d}",
                category="stateful",
                profile="practical",
                raw_input=f"{label}: {first}; retry: {second}",
                item_inputs=[first, second],
                usda_records=[usda_record(identity, source_id)],
                allowed_refs=[f"usda:{source_id}"],
                allowed_identities=[identity],
                allowed_modes=["generic_proxy", "pending_capture"],
                forbidden_tokens=["poisoned", "invented"],
                envelopes=[None if index in {2, 4} else [50, 50], [75, 75]],
                outcome="pending" if index in {2, 4} else "complete",
                max_followups=1 if index in {2, 4} else 0,
                steps=steps,
        )
        if index == 2:
            case["synthetic_providers"]["responses"]["usda_search_status_by_term"] = {
                "provider-outage": 503
            }
        cases.append(case)
    return cases


def build_corpus() -> dict:
    cases = [
        *measured_cases(10001),
        *fuzzy_cases(11001),
        *branded_cases(12001),
        *mixed_cases(13001),
        *cooking_cases(14001),
        *ambiguity_cases(15001),
        *stateful_cases(16001),
    ]
    expected_counts = {
        "measured_generic": 20,
        "fuzzy_portion": 20,
        "branded": 20,
        "mixed_voice": 15,
        "cooking_yield": 10,
        "ambiguity_failure": 10,
        "stateful": 5,
    }
    counts = {
        category: sum(case["category"] == category for case in cases)
        for category in expected_counts
    }
    assert len(cases) == 100
    assert counts == expected_counts
    assert len({case["id"] for case in cases}) == 100
    return {
        "schema_version": 1,
        "description": (
            "Synthetic eval-only benchmark oracle. Never load from production code or package."
        ),
        "category_counts": expected_counts,
        "cases": cases,
    }


def main() -> None:
    destination = ROOT / "corpus.json"
    destination.write_text(
        json.dumps(build_corpus(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
