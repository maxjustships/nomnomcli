from __future__ import annotations

import json
from copy import deepcopy

import pytest
import requests

from nomnomcli.cli import main
from nomnomcli.db import connect
from nomnomcli.off import OFF_PRODUCT_URL, OFF_SEARCH_URL
from nomnomcli.usda import USDA_SEARCH_URL

USDA_FOOD_URL = "https://api.nal.usda.gov/fdc/v1/food/{fdc_id}"


class Response:
    def __init__(self, payload, *, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return deepcopy(self.payload)


def nutrients(*, kcal, protein, fat, carbs):
    return [
        {"nutrientId": 1008, "nutrientName": "Energy", "unitName": "KCAL", "value": kcal},
        {"nutrientId": 1003, "nutrientName": "Protein", "unitName": "G", "value": protein},
        {"nutrientId": 1004, "nutrientName": "Total lipid (fat)", "unitName": "G", "value": fat},
        {
            "nutrientId": 1005,
            "nutrientName": "Carbohydrate, by difference",
            "unitName": "G",
            "value": carbs,
        },
    ]


RAW_TOMATO = {
    "fdcId": 101,
    "description": "Raw tomato",
    "dataType": "Foundation",
    "foodCategory": "Vegetables",
    "foodNutrients": nutrients(kcal=18, protein=0.9, fat=0.2, carbs=3.9),
}
TOMATO_POWDER = {
    "fdcId": 102,
    "description": "Tomato powder",
    "dataType": "SR Legacy",
    "foodCategory": "Vegetable products",
    "foodNutrients": nutrients(kcal=302, protein=13, fat=3, carbs=59),
}
GENERIC_MILK = {
    "fdcId": 201,
    "description": "Milk",
    "dataType": "Foundation",
    "foodCategory": "Dairy",
    "foodNutrients": nutrients(kcal=61, protein=3.2, fat=3.3, carbs=4.8),
}
MILK_CRACKERS = {
    "fdcId": 202,
    "description": "Milk crackers",
    "dataType": "SR Legacy",
    "foodCategory": "Baked products",
    "foodNutrients": nutrients(kcal=430, protein=8, fat=13, carbs=70),
}
OFF_BRANDED = {
    "product_name": "Sandwich bread",
    "brands": "Harry's",
    "code": "0123456789012",
    "categories": "Breads",
    "categories_tags": ["en:breads"],
    "nutriments": {
        "energy-kcal_100g": 250,
        "proteins_100g": 9,
        "fat_100g": 4,
        "carbohydrates_100g": 45,
    },
}


def provider_get(url, **kwargs):
    if url == USDA_SEARCH_URL:
        query = kwargs["params"]["query"].casefold()
        if "tomato" in query:
            return Response({"foods": [TOMATO_POWDER, RAW_TOMATO]})
        if "milk" in query:
            return Response({"foods": [MILK_CRACKERS, GENERIC_MILK]})
        return Response({"foods": []})
    if url == USDA_FOOD_URL.format(fdc_id=101):
        return Response(RAW_TOMATO)
    if url == USDA_FOOD_URL.format(fdc_id=102):
        return Response(TOMATO_POWDER)
    if url == USDA_FOOD_URL.format(fdc_id=201):
        return Response(GENERIC_MILK)
    if url == USDA_FOOD_URL.format(fdc_id=202):
        return Response(MILK_CRACKERS)
    if url.startswith("https://api.nal.usda.gov/fdc/v1/food/"):
        return Response({}, status_code=404)
    if url == OFF_SEARCH_URL:
        query = kwargs["params"]["search_terms"].casefold()
        return Response({"products": [OFF_BRANDED] if "harry" in query else []})
    if url == OFF_PRODUCT_URL.format(barcode=OFF_BRANDED["code"]):
        return Response({"status": 1, "product": OFF_BRANDED})
    raise AssertionError(f"unexpected provider request: {url}")


@pytest.fixture
def synthetic_providers(monkeypatch):
    monkeypatch.setenv("NOMNOM_USDA_KEY", "synthetic-placeholder")
    monkeypatch.setattr(requests, "get", provider_get)


def invoke_json(arguments, capsys):
    code = main([*arguments, "--json"])
    captured = capsys.readouterr()
    stream = captured.out if code == 0 else captured.err
    return code, json.loads(stream), captured


def plan(*items, portion_estimates=None):
    payload = {"version": 1, "items": list(items)}
    if portion_estimates is not None:
        payload["portion_estimates"] = {"items": portion_estimates}
    return json.dumps(payload)


def estimate(index, input_phrase, grams):
    return {
        "item_index": index,
        "input": input_phrase,
        "grams": grams,
        "lower_grams": grams * 0.8,
        "upper_grams": grams * 1.2,
        "confidence": 0.7,
        "method": "agent_estimate",
        "assumption": "Synthetic voice portion estimate.",
    }


def pending(input_phrase):
    return {
        "input": input_phrase,
        "pending_capture": {
            "status": "pending_capture",
            "action": "photo_or_barcode",
        },
    }


def test_agent_candidates_are_read_only_deterministic_and_type_safe(
    tmp_path, monkeypatch, synthetic_providers, capsys
):
    untouched = tmp_path / "real-user-override-must-not-open.sqlite3"
    monkeypatch.setenv("NOMNOM_DB_PATH", str(untouched))

    first_code, first, _ = invoke_json(
        ["agent", "candidates", "--input", "raw tomato 60 g"], capsys
    )
    second_code, second, _ = invoke_json(
        ["agent", "candidates", "--input", "raw tomato 60 g"], capsys
    )

    assert first_code == second_code == 0
    assert first == second
    assert not untouched.exists()
    by_ref = {candidate["source_ref"]: candidate for candidate in first["candidates"]}
    assert by_ref["usda:101"] == {
        "brand": None,
        "canonical_name": "raw tomato",
        "category": "Vegetables",
        "candidate_status": "generic_proxy_eligible",
        "provider": "usda",
        "source_id": "101",
        "source_ref": "usda:101",
        "type": "Foundation",
    }
    assert by_ref["usda:102"]["candidate_status"] == "identity_rejected"
    assert all("kcal" not in json.dumps(candidate) for candidate in first["candidates"])


def test_agent_candidates_expose_milk_not_crackers(
    tmp_path, monkeypatch, synthetic_providers, capsys
):
    untouched = tmp_path / "discovery.sqlite3"
    monkeypatch.setenv("NOMNOM_DB_PATH", str(untouched))

    code, result, _ = invoke_json(["agent", "candidates", "--input", "milk 200 g"], capsys)

    assert code == 0
    statuses = {
        candidate["source_ref"]: candidate["candidate_status"] for candidate in result["candidates"]
    }
    assert statuses == {
        "usda:201": "generic_proxy_eligible",
        "usda:202": "identity_rejected",
    }
    assert not untouched.exists()


def test_agent_candidates_report_partial_provider_unavailability_without_write(
    tmp_path, monkeypatch, capsys
):
    untouched = tmp_path / "discovery.sqlite3"
    monkeypatch.setenv("NOMNOM_DB_PATH", str(untouched))
    monkeypatch.setenv("NOMNOM_USDA_KEY", "synthetic-placeholder")

    def unavailable(url, **kwargs):
        if url == OFF_SEARCH_URL:
            raise requests.ConnectionError("synthetic outage")
        return provider_get(url, **kwargs)

    monkeypatch.setattr(requests, "get", unavailable)
    code, result, _ = invoke_json(["agent", "candidates", "--input", "raw tomato 60 g"], capsys)

    assert code == 0
    assert result["candidates"][0]["source_ref"] == "usda:101"
    assert result["provider_errors"]["openfoodfacts"]["code"] == "openfoodfacts_unavailable"
    assert not untouched.exists()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"version": 2, "items": []},
        {"version": 1, "items": [], "nutrition": {}},
        {"version": 1, "items": [{"input": "tomato", "grams": 60}]},
        {
            "version": 1,
            "items": [
                {
                    "input": "tomato",
                    "grams": 60,
                    "source_ref": "usda:101",
                    "kcal": 999,
                }
            ],
        },
        {
            "version": 1,
            "items": [
                {
                    "input": "tomato",
                    "grams": 60,
                    "source_ref": "usda:101",
                    "pending_capture": {
                        "status": "pending_capture",
                        "action": "photo_or_barcode",
                    },
                }
            ],
        },
        {
            "version": 1,
            "items": [{"input": "tomato", "grams": float("inf"), "source_ref": "usda:101"}],
        },
    ],
    ids=(
        "missing-fields",
        "unknown-version",
        "agent-nutrition-top-level",
        "missing-state",
        "agent-nutrition-item",
        "both-state-forms",
        "nonfinite-grams",
    ),
)
def test_agent_intake_rejects_malformed_or_nutrient_bearing_plan_without_write(
    payload, user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))

    code, result, captured = invoke_json(["agent", "intake", "--plan", json.dumps(payload)], capsys)

    assert code == 2
    assert captured.out == ""
    assert result["error"]["code"] == "agent_plan_invalid"
    assert not user_db.exists()


def test_agent_intake_refetches_literal_tomato_and_milk_and_writes_one_event(
    user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    payload = plan(
        {"input": "raw tomato 60 g", "grams": 60, "source_ref": "usda:101"},
        {"input": "milk 200 g", "grams": 200, "source_ref": "usda:201"},
    )

    code, result, _ = invoke_json(["agent", "intake", "--plan", payload], capsys)

    assert code == 0
    assert result["complete"] is True
    assert result["nutrition_status"] == "complete"
    assert [item["name"] for item in result["items"]] == ["raw tomato", "milk"]
    assert all(item["status"] == "resolved" for item in result["items"])
    assert result["totals"] == {"carbs": 11.94, "fat": 6.72, "kcal": 132.8, "protein": 6.94}
    assert "powder" not in json.dumps(result).casefold()
    assert "cracker" not in json.dumps(result).casefold()
    with connect(user_db) as connection:
        rows = connection.execute("SELECT kind, items_json FROM log_entries").fetchall()
        assert len(rows) == 1
        assert rows[0]["kind"] == "agent_intake"
        assert connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 0


def test_agent_intake_pending_exact_brand_is_preserved_and_stats_are_incomplete(
    user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    payload = plan(
        {"input": "raw tomato 60 g", "grams": 60, "source_ref": "usda:101"},
        pending("Harry's bread two slices"),
        pending("Dr Johnson milk one bottle"),
    )

    code, result, _ = invoke_json(["agent", "intake", "--plan", payload], capsys)

    assert code == 0
    assert result["complete"] is False
    assert result["nutrition_status"] == "incomplete"
    assert result["totals"]["complete"] is False
    assert result["pending_count"] == 2
    assert [item["input"] for item in result["items"][1:]] == [
        "Harry's bread two slices",
        "Dr Johnson milk one bottle",
    ]
    assert all(item["status"] == "pending_capture" for item in result["items"][1:])
    assert all("kcal" not in item for item in result["items"][1:])
    assert result["pending_items"] == [
        {
            "event_id": result["log_id"],
            "item_id": f"{result['log_id']}:1",
            "input": "Harry's bread two slices",
            "action": "photo_or_barcode",
        },
        {
            "event_id": result["log_id"],
            "item_id": f"{result['log_id']}:2",
            "input": "Dr Johnson milk one bottle",
            "action": "photo_or_barcode",
        },
    ]

    stats_code, stats, _ = invoke_json(["stats", "today"], capsys)
    assert stats_code == 0
    assert stats["complete"] is False
    assert stats["nutrition_status"] == "incomplete"
    assert stats["pending_count"] == 2
    assert stats["totals"]["complete"] is False
    assert stats["meals"][0]["pending_count"] == 2


def test_agent_intake_rejects_text_discovered_brand_as_exact_without_write(
    user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))

    discovery_code, discovery, _ = invoke_json(
        ["agent", "candidates", "--input", "Harry's sandwich bread 80 g"],
        capsys,
    )
    assert discovery_code == 0
    assert discovery["candidates"][0]["source_ref"] == "off:0123456789012"
    assert discovery["candidates"][0]["candidate_status"] == "pending_capture_required"
    assert not user_db.exists()

    code, error, _ = invoke_json(
        [
            "agent",
            "intake",
            "--plan",
            plan(
                {
                    "input": "Harry's sandwich bread 80 g",
                    "grams": 80,
                    "source_ref": "off:0123456789012",
                }
            ),
        ],
        capsys,
    )

    assert code == 2
    assert error["error"]["code"] == "agent_source_identity_rejected"
    assert error["error"]["details"]["action"] == "photo_or_barcode"
    with connect(user_db) as connection:
        assert connection.execute("SELECT count(*) FROM log_entries").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("source_ref", "expected_code"),
    [
        ("usda:999", "agent_source_ref_mismatch"),
        ("usda:102", "agent_source_identity_rejected"),
        ("usda:202", "agent_source_identity_rejected"),
        ("off:not-a-barcode", "agent_source_ref_invalid"),
    ],
)
def test_agent_intake_rejects_tampered_or_wrong_type_ref_atomically(
    source_ref, expected_code, user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    raw = "milk 200 g" if source_ref.endswith("202") else "raw tomato 60 g"

    code, error, _ = invoke_json(
        ["agent", "intake", "--plan", plan({"input": raw, "grams": 60, "source_ref": source_ref})],
        capsys,
    )

    assert code == 2
    assert error["error"]["code"] == expected_code
    with connect(user_db) as connection:
        assert connection.execute("SELECT count(*) FROM log_entries").fetchone()[0] == 0


def test_agent_intake_rejects_duplicate_refs_without_write(
    user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    item = {"input": "raw tomato 60 g", "grams": 60, "source_ref": "usda:101"}

    code, error, _ = invoke_json(["agent", "intake", "--plan", plan(item, item)], capsys)

    assert code == 2
    assert error["error"]["code"] == "agent_source_ref_duplicate"
    assert not user_db.exists()


def test_agent_intake_ignores_poisoned_cache_and_refetches_source(
    user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    with connect(user_db) as connection:
        connection.execute(
            """INSERT INTO food_cache
            (name, kcal, protein, fat, carbs, source, lookup_query, resolution_mode, source_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("raw tomato", 999, 99, 99, 99, "poison", "raw tomato", "legacy", "101"),
        )

    code, result, _ = invoke_json(
        [
            "agent",
            "intake",
            "--plan",
            plan({"input": "raw tomato 60 g", "grams": 60, "source_ref": "usda:101"}),
        ],
        capsys,
    )

    assert code == 0
    assert result["items"][0]["kcal"] == 10.8
    assert result["items"][0]["source"] == "usda"


VOICE_PLAN_CASES = [
    (
        "tomato sixty grams",
        [{"input": "raw tomato 60 g", "grams": 60, "source_ref": "usda:101"}],
        None,
    ),
    (
        "half a tomato",
        [{"input": "half raw tomato", "source_ref": "usda:101"}],
        [(0, "half raw tomato", 60)],
    ),
    (
        "quarter tomato",
        [{"input": "quarter raw tomato", "source_ref": "usda:101"}],
        [(0, "quarter raw tomato", 30)],
    ),
    (
        "one tomato",
        [{"input": "1 raw tomato", "source_ref": "usda:101"}],
        [(0, "1 raw tomato", 120)],
    ),
    (
        "milk two hundred grams",
        [{"input": "milk 200 g", "grams": 200, "source_ref": "usda:201"}],
        None,
    ),
    (
        "half glass milk",
        [{"input": "half milk", "source_ref": "usda:201"}],
        [(0, "half milk", 120)],
    ),
    (
        "quarter glass milk",
        [{"input": "quarter milk", "source_ref": "usda:201"}],
        [(0, "quarter milk", 60)],
    ),
    (
        "tomato and milk",
        [
            {"input": "raw tomato 80 g", "grams": 80, "source_ref": "usda:101"},
            {"input": "milk 150 g", "grams": 150, "source_ref": "usda:201"},
        ],
        None,
    ),
    (
        "small tomato, milk",
        [
            {"input": "small raw tomato", "source_ref": "usda:101"},
            {"input": "milk 100 g", "grams": 100, "source_ref": "usda:201"},
        ],
        [(0, "small raw tomato", 75)],
    ),
    (
        "large tomato",
        [{"input": "large raw tomato", "source_ref": "usda:101"}],
        [(0, "large raw tomato", 180)],
    ),
    (
        "medium tomato",
        [{"input": "medium raw tomato", "source_ref": "usda:101"}],
        [(0, "medium raw tomato", 120)],
    ),
    (
        "a tomato and a branded bread",
        [
            {"input": "raw tomato 60 g", "grams": 60, "source_ref": "usda:101"},
            pending("Harry's bread"),
        ],
        None,
    ),
    ("doctor johnson milk", [pending("Dr Johnson milk")], None),
    ("harrys bread", [pending("Harry's bread")], None),
    ("unknown exact carton", [pending("Example carton SKU 778899")], None),
    ("photo missing brand bar", [pending("Brand bar from unclear photo")], None),
    (
        "tomato plus unknown bottle",
        [
            {"input": "raw tomato 100 g", "grams": 100, "source_ref": "usda:101"},
            pending("Unknown bottle"),
        ],
        None,
    ),
    (
        "milk plus exact crackers",
        [{"input": "milk 100 g", "grams": 100, "source_ref": "usda:201"}, pending("Acme crackers")],
        None,
    ),
    (
        "two fuzzy items",
        [
            {"input": "small raw tomato", "source_ref": "usda:101"},
            {"input": "half milk", "source_ref": "usda:201"},
        ],
        [(0, "small raw tomato", 75), (1, "half milk", 120)],
    ),
    ("pending meal", [pending("Harry's sandwich"), pending("Dr Johnson drink")], None),
]


@pytest.mark.parametrize(
    ("voice", "items", "estimates"), VOICE_PLAN_CASES, ids=[case[0] for case in VOICE_PLAN_CASES]
)
def test_synthetic_voice_plan_fuzz_harness_has_no_false_substitutions(
    voice, items, estimates, user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    portion_estimates = (
        [estimate(index, input_phrase, grams) for index, input_phrase, grams in estimates]
        if estimates
        else None
    )

    code, result, _ = invoke_json(
        ["agent", "intake", "--plan", plan(*items, portion_estimates=portion_estimates)],
        capsys,
    )

    assert code == 0, voice
    assert all(item["status"] in {"resolved", "pending_capture"} for item in result["items"])
    resolved_names = {item["name"] for item in result["items"] if item["status"] == "resolved"}
    assert resolved_names <= {"raw tomato", "milk"}
    assert not any("powder" in name or "cracker" in name for name in resolved_names)
    assert all(
        "kcal" not in item for item in result["items"] if item["status"] == "pending_capture"
    )
    if result["pending_count"]:
        assert result["complete"] is False
        assert result["totals"]["complete"] is False


def test_agent_intake_keeps_existing_explicit_removal_correction_flow(
    user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    code, logged, _ = invoke_json(
        ["agent", "intake", "--plan", plan(pending("Harry's bread"))], capsys
    )
    assert code == 0

    remove_code, removed, _ = invoke_json(
        ["log", "remove", str(logged["log_id"]), "--confirm"], capsys
    )

    assert remove_code == 0
    assert removed["removed"] is True
    assert removed["log_id"] == logged["log_id"]
    with connect(user_db) as connection:
        assert connection.execute("SELECT count(*) FROM log_entries").fetchone()[0] == 0
