from __future__ import annotations

import json
from copy import deepcopy

import pytest
import requests

from nomnomcli.agent import _identity_query
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
RIPE_TOMATO = {
    "fdcId": 105,
    "description": "Tomatoes, red, ripe, raw, year round average",
    "dataType": "Foundation",
    "foodCategory": "Vegetables",
    "foodNutrients": nutrients(kcal=19, protein=1, fat=0.2, carbs=4.1),
}
TOMATO_POWDER = {
    "fdcId": 102,
    "description": "Tomato powder",
    "dataType": "SR Legacy",
    "foodCategory": "Vegetable products",
    "foodNutrients": nutrients(kcal=302, protein=13, fat=3, carbs=59),
}
UNUSABLE_TOMATO_SNACK = {
    "fdcId": 106,
    "description": "Tomato banana snack",
    "dataType": "Survey (FNDDS)",
    "foodCategory": "Mixed foods",
    "foodNutrients": nutrients(kcal=90, protein=1, fat=1, carbs=20),
}
GENERIC_MILK = {
    "fdcId": 201,
    "description": "Milk",
    "dataType": "Foundation",
    "foodCategory": "Dairy",
    "foodNutrients": nutrients(kcal=61, protein=3.2, fat=3.3, carbs=4.8),
}
FLUID_MILK = {
    "fdcId": 205,
    "description": "Milk, whole, fluid, 3.25% milkfat",
    "dataType": "Foundation",
    "foodCategory": "Dairy",
    "foodNutrients": nutrients(kcal=62, protein=3.2, fat=3.4, carbs=4.7),
}
BRANDED_MILK = {
    "fdcId": 206,
    "description": "Whole milk",
    "dataType": "Foundation",
    "brandOwner": "Synthetic Dairy",
    "foodCategory": "Dairy",
    "foodNutrients": nutrients(kcal=64, protein=3.1, fat=3.5, carbs=4.8),
}
INCOMPLETE_MILK = {
    "fdcId": 207,
    "description": "Milk, fluid",
    "dataType": "Foundation",
    "foodCategory": "Dairy",
    "foodNutrients": nutrients(kcal=61, protein=3.2, fat=3.3, carbs=float("nan")),
}
CHOCOLATE_MILK = {
    "fdcId": 203,
    "description": "Chocolate milk",
    "dataType": "Foundation",
    "foodCategory": "Dairy",
    "foodNutrients": nutrients(kcal=83, protein=3.2, fat=3.4, carbs=10.3),
}
CONDENSED_MILK = {
    "fdcId": 204,
    "description": "Condensed milk",
    "dataType": "SR Legacy",
    "foodCategory": "Dairy",
    "foodNutrients": nutrients(kcal=321, protein=7.9, fat=8.7, carbs=54.4),
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
            return Response(
                {"foods": [UNUSABLE_TOMATO_SNACK, TOMATO_POWDER, RIPE_TOMATO, RAW_TOMATO]}
            )
        if "milk" in query:
            return Response(
                {
                    "foods": [
                        CHOCOLATE_MILK,
                        CONDENSED_MILK,
                        MILK_CRACKERS,
                        BRANDED_MILK,
                        FLUID_MILK,
                        GENERIC_MILK,
                    ]
                }
            )
        return Response({"foods": []})
    if url == USDA_FOOD_URL.format(fdc_id=101):
        return Response(RAW_TOMATO)
    if url == USDA_FOOD_URL.format(fdc_id=102):
        return Response(TOMATO_POWDER)
    if url == USDA_FOOD_URL.format(fdc_id=105):
        return Response(RIPE_TOMATO)
    if url == USDA_FOOD_URL.format(fdc_id=106):
        return Response(UNUSABLE_TOMATO_SNACK)
    if url == USDA_FOOD_URL.format(fdc_id=201):
        return Response(GENERIC_MILK)
    if url == USDA_FOOD_URL.format(fdc_id=202):
        return Response(MILK_CRACKERS)
    if url == USDA_FOOD_URL.format(fdc_id=203):
        return Response(CHOCOLATE_MILK)
    if url == USDA_FOOD_URL.format(fdc_id=204):
        return Response(CONDENSED_MILK)
    if url == USDA_FOOD_URL.format(fdc_id=205):
        return Response(FLUID_MILK)
    if url == USDA_FOOD_URL.format(fdc_id=206):
        return Response(BRANDED_MILK)
    if url == USDA_FOOD_URL.format(fdc_id=207):
        return Response(INCOMPLETE_MILK)
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


SELECTED_IDENTITIES = {
    "usda:105": "tomatoes, red, ripe, raw, year round average",
    "usda:205": "milk, whole, fluid, 3.25% milkfat",
    "usda:206": "whole milk",
    "usda:207": "milk, fluid",
    "off:0123456789012": "sandwich bread",
}


def selected(input_phrase, source_ref, assumption, *, grams=None):
    relation = "semantic_equivalent"
    item = {
        "input": input_phrase,
        "selection": {
            "source_ref": source_ref,
            "relation": relation,
            "assumption": assumption,
            "semantic_attestation": {
                "version": 1,
                "relation": relation,
                "raw_identity": _identity_query(input_phrase),
                "selected_identity": SELECTED_IDENTITIES[source_ref],
                "same_food_type": True,
                "rationale": "Synthetic actor selected the same food type.",
                "confidence": 0.9,
            },
        },
    }
    if grams is not None:
        item["grams"] = grams
    return item


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
        "candidate_status": "agent_selection_eligible",
        "direct_source_ref_eligible": True,
        "provider": "usda",
        "semantic_identity": "raw tomato",
        "source_id": "101",
        "source_ref": "usda:101",
        "type": "Foundation",
    }
    assert by_ref["usda:105"]["candidate_status"] == "agent_selection_eligible"
    assert by_ref["usda:105"]["direct_source_ref_eligible"] is False
    assert by_ref["usda:102"]["candidate_status"] == "agent_selection_eligible"
    assert by_ref["usda:106"]["candidate_status"] == "identity_rejected"
    assert [candidate["source_ref"] for candidate in first["candidates"]] == [
        "usda:101",
        "usda:102",
        "usda:105",
        "usda:106",
    ]
    assert all("kcal" not in json.dumps(candidate) for candidate in first["candidates"])


def test_agent_candidates_distinguish_generic_pending_and_unusable_sources(
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
        "usda:201": "agent_selection_eligible",
        "usda:202": "agent_selection_eligible",
        "usda:203": "agent_selection_eligible",
        "usda:204": "agent_selection_eligible",
        "usda:205": "agent_selection_eligible",
        "usda:206": "pending_capture_required",
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


@pytest.mark.parametrize(
    "selection",
    [
        None,
        {},
        {"source_ref": "usda:105", "relation": "semantic_equivalent"},
        {
            "source_ref": "usda:105",
            "relation": "semantic_equivalent",
            "assumption": "",
        },
        {
            "source_ref": 105,
            "relation": "semantic_equivalent",
            "assumption": "Synthetic semantic selection.",
        },
        {
            "source_ref": "usda:105",
            "relation": "",
            "assumption": "Synthetic semantic selection.",
        },
        {
            "source_ref": "usda:105",
            "relation": "semantic_equivalent",
            "assumption": "Synthetic semantic selection.",
            "kcal": 999,
        },
    ],
    ids=(
        "non-object",
        "missing-fields",
        "missing-assumption",
        "empty-assumption",
        "non-string-ref",
        "empty-relation",
        "nutrition-injection",
    ),
)
def test_agent_intake_rejects_malformed_selection_without_write(
    selection, user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    payload = plan({"input": "raw tomato", "grams": 60, "selection": selection})

    code, result, captured = invoke_json(["agent", "intake", "--plan", payload], capsys)

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


def test_agent_intake_accepts_explicit_semantic_tomato_and_milk_selection(
    user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    payload = plan(
        selected(
            "raw tomato 60 g",
            "usda:105",
            "Interpreted raw tomato as the source's ripe raw tomato record.",
            grams=60,
        ),
        selected(
            "raw milk 200 g",
            "usda:205",
            "Interpreted raw milk as the source's whole fluid milk record.",
            grams=200,
        ),
    )

    code, result, _ = invoke_json(["agent", "intake", "--plan", payload], capsys)

    assert code == 0
    assert [item["name"] for item in result["items"]] == [
        "tomatoes, red, ripe, raw, year round average",
        "milk, whole, fluid, 3.25% milkfat",
    ]
    for item, ref in zip(result["items"], ("usda:105", "usda:205"), strict=True):
        assert item["status"] == "resolved"
        assert item["selection_mode"] == "agent_generic"
        assert item["selection_relation"] == "semantic_equivalent"
        assert item["selected_source_ref"] == ref
        assert item["source"] == "usda"
        assert item["provenance"] == "agent_selected"
        assert item["resolution_mode"] == "generic_proxy"
        assert item["assumption"]
    serialized = json.dumps(result).casefold()
    assert "powder" not in serialized
    assert "banana" not in serialized
    assert "cracker" not in serialized
    assert "chocolate" not in serialized
    assert "condensed" not in serialized
    with connect(user_db) as connection:
        stored = json.loads(connection.execute("SELECT items_json FROM log_entries").fetchone()[0])
        assert [item["input"] for item in stored] == ["raw tomato 60 g", "raw milk 200 g"]
        assert [item["selected_source_ref"] for item in stored] == ["usda:105", "usda:205"]
        assert connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 0


@pytest.mark.parametrize("source_ref", ["usda:203", "usda:204"])
def test_agent_intake_rejects_type_changing_leading_milk_modifiers_without_write(
    source_ref, user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))

    code, error, _ = invoke_json(
        [
            "agent",
            "intake",
            "--plan",
            plan({"input": "milk 200 g", "grams": 200, "source_ref": source_ref}),
        ],
        capsys,
    )

    assert code == 2
    assert error["error"]["code"] == "agent_source_identity_rejected"
    assert not user_db.exists()


@pytest.mark.parametrize(
    ("source_ref", "provider"),
    [("off:0123456789012", "openfoodfacts"), ("usda:201", "usda")],
)
def test_agent_intake_offline_blocks_source_refetch_without_calls_or_write(
    source_ref, provider, user_db, monkeypatch, synthetic_providers, capsys
):
    calls = []
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    monkeypatch.setattr(requests, "get", lambda url, **kwargs: calls.append(url))

    code, error, _ = invoke_json(
        [
            "agent",
            "intake",
            "--plan",
            plan({"input": "milk 200 g", "grams": 200, "source_ref": source_ref}),
        ],
        capsys,
    )

    assert code == 2
    assert error["error"]["code"] == "provider_disabled"
    assert error["error"]["details"]["provider"] == provider
    assert "NOMNOM_OFFLINE" in error["error"]["details"]["action"]
    assert calls == []
    assert not user_db.exists()


def test_agent_intake_disable_off_blocks_only_off_without_call_or_write(
    user_db, monkeypatch, synthetic_providers, capsys
):
    calls = []
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.setattr(requests, "get", lambda url, **kwargs: calls.append(url))

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
    assert error["error"]["code"] == "provider_disabled"
    assert error["error"]["details"]["provider"] == "openfoodfacts"
    assert "NOMNOM_DISABLE_OFF" in error["error"]["details"]["action"]
    assert calls == []
    assert not user_db.exists()


def test_agent_intake_disable_off_still_allows_configured_usda_refetch(
    user_db, monkeypatch, synthetic_providers, capsys
):
    calls = []
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")

    def tracked_get(url, **kwargs):
        calls.append(url)
        return provider_get(url, **kwargs)

    monkeypatch.setattr(requests, "get", tracked_get)

    code, result, _ = invoke_json(
        [
            "agent",
            "intake",
            "--plan",
            plan({"input": "milk 200 g", "grams": 200, "source_ref": "usda:201"}),
        ],
        capsys,
    )

    assert code == 0
    assert result["items"][0]["name"] == "milk"
    assert calls == [USDA_FOOD_URL.format(fdc_id=201)]


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


def test_agent_intake_rejects_agent_selected_text_discovered_brand_without_write(
    user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))

    discovery_code, discovery, _ = invoke_json(
        ["agent", "candidates", "--input", "Harry's sandwich bread 80 g"],
        capsys,
    )
    assert discovery_code == 0
    assert discovery["candidates"][0]["source_ref"] == "off:0123456789012"
    assert (
        discovery["candidates"][0]["candidate_status"]
        == "brand_candidate_requires_semantic_assessment"
    )
    assert not user_db.exists()

    code, error, _ = invoke_json(
        [
            "agent",
            "intake",
            "--plan",
            plan(
                selected(
                    "Harry's sandwich bread 80 g",
                    "off:0123456789012",
                    "The text-ranked candidate appears related to the branded request.",
                    grams=80,
                )
            ),
        ],
        capsys,
    )

    assert code == 2
    assert error["error"]["code"] == "agent_source_identity_rejected"
    assert error["error"]["details"]["action"] == "select_safe_candidate_or_pending"
    with connect(user_db) as connection:
        assert connection.execute("SELECT count(*) FROM log_entries").fetchone()[0] == 0


def test_exact_profile_rejects_probable_brand_plan_without_write(
    user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_ACCURACY_PROFILE", "exact")
    raw = "Harry's sandwich bread 80 g"
    discovery_code, discovery, _ = invoke_json(
        ["agent", "candidates", "--input", raw],
        capsys,
    )
    assert discovery_code == 0
    relation = "probable_brand_match"
    payload = {
        "version": 2,
        "accuracy_profile": "exact",
        "items": [
            {
                "input": raw,
                "grams": 80,
                "selection": {
                    "source_ref": "off:0123456789012",
                    "relation": relation,
                    "assumption": "Text-only brand candidate is not exact.",
                    "semantic_attestation": {
                        "version": 1,
                        "relation": relation,
                        "raw_identity": "Harry's sandwich bread",
                        "selected_identity": "sandwich bread",
                        "same_food_type": True,
                        "rationale": "Synthetic same-food-type assessment.",
                        "confidence": 0.9,
                    },
                    "discovery_receipt": discovery["discovery_receipt"],
                },
            }
        ],
    }

    code, error, _ = invoke_json(
        ["agent", "intake", "--plan", json.dumps(payload)],
        capsys,
    )

    assert code == 2
    assert error["error"]["code"] == "agent_plan_invalid"
    assert not user_db.exists()


def test_exact_profile_rejects_legacy_estimate_without_write(
    user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_ACCURACY_PROFILE", "exact")
    payload = plan(
        {"input": "one tomato", "source_ref": "usda:101"},
        portion_estimates=[estimate(0, "one tomato", 60)],
    )

    code, error, _ = invoke_json(
        ["agent", "intake", "--plan", payload],
        capsys,
    )

    assert code == 2
    assert error["error"]["code"] == "accuracy_profile_exact_required"
    assert not user_db.exists()


@pytest.mark.parametrize("mutation", ["missing", "unknown_field"])
def test_semantic_attestation_schema_errors_write_nothing(
    mutation, user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    item = selected(
        "raw tomato 60 g",
        "usda:105",
        "Synthetic semantic selection.",
        grams=60,
    )
    if mutation == "missing":
        item["selection"].pop("semantic_attestation")
    else:
        item["selection"]["semantic_attestation"]["nutrition"] = {"kcal": 1}

    code, error, _ = invoke_json(
        ["agent", "intake", "--plan", plan(item)],
        capsys,
    )

    assert code == 2
    assert error["error"]["code"] == "agent_plan_invalid"
    assert not user_db.exists()


def test_missing_brand_dismissal_field_writes_nothing(
    user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    raw = "Harry's sandwich bread 80 g"
    discovery_code, discovery, _ = invoke_json(
        ["agent", "candidates", "--input", raw],
        capsys,
    )
    assert discovery_code == 0
    assert any(
        candidate["candidate_status"]
        == "brand_candidate_requires_semantic_assessment"
        for candidate in discovery["candidates"]
    )
    relation = "branded_same_type_generic"
    payload = {
        "version": 2,
        "accuracy_profile": "balanced",
        "items": [
            {
                "input": raw,
                "grams": 80,
                "selection": {
                    "source_ref": "usda:301",
                    "relation": relation,
                    "assumption": "Harry's brand/SKU was not exact; used generic bread.",
                    "semantic_attestation": {
                        "version": 1,
                        "relation": relation,
                        "raw_identity": "Harry's sandwich bread",
                        "selected_identity": "sandwich bread",
                        "same_food_type": True,
                        "rationale": "Synthetic same-food-type assessment.",
                        "confidence": 0.9,
                    },
                    "discovery_receipt": discovery["discovery_receipt"],
                    "risk_disposition": "material_risk_accepted",
                },
            }
        ],
    }

    code, error, _ = invoke_json(
        ["agent", "intake", "--plan", json.dumps(payload)],
        capsys,
    )

    assert code == 2
    assert error["error"]["code"] == "agent_plan_invalid"
    assert not user_db.exists()


def test_agent_intake_rejects_agent_selected_branded_usda_source_without_write(
    user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))

    code, error, _ = invoke_json(
        [
            "agent",
            "intake",
            "--plan",
            plan(
                selected(
                    "raw milk 200 g",
                    "usda:206",
                    "The candidate text appears related to milk.",
                    grams=200,
                )
            ),
        ],
        capsys,
    )

    assert code == 2
    assert error["error"]["code"] in {
        "agent_source_identity_rejected",
        "exact_resolution_required",
    }
    assert error["error"]["details"]["action"] == "photo_or_barcode"
    assert not user_db.exists()


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


def test_agent_intake_rejects_incomplete_refetched_nutrition_without_write(
    user_db, monkeypatch, synthetic_providers, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))

    code, error, _ = invoke_json(
        [
            "agent",
            "intake",
            "--plan",
            plan(
                selected(
                    "raw milk 200 g",
                    "usda:207",
                    "Interpreted raw milk as the returned generic milk source.",
                    grams=200,
                )
            ),
        ],
        capsys,
    )

    assert code == 2
    assert error["error"]["code"] == "usda_invalid_nutrition"
    assert not user_db.exists()


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
            (
                "tomatoes, red, ripe, raw, year round average",
                999,
                99,
                99,
                99,
                "poison",
                "raw tomato",
                "legacy",
                "105",
            ),
        )

    code, result, _ = invoke_json(
        [
            "agent",
            "intake",
            "--plan",
            plan(
                selected(
                    "raw tomato 60 g",
                    "usda:105",
                    "Interpreted raw tomato as the source's ripe raw tomato record.",
                    grams=60,
                )
            ),
        ],
        capsys,
    )

    assert code == 0
    assert result["items"][0]["kcal"] == 11.4
    assert result["items"][0]["source"] == "usda"


def tomato_selection(input_phrase, *, grams=None):
    return selected(
        input_phrase,
        "usda:105",
        "Interpreted the tomato phrase as the source's ripe raw tomato record.",
        grams=grams,
    )


def milk_selection(input_phrase, *, grams=None):
    return selected(
        input_phrase,
        "usda:205",
        "Interpreted the milk phrase as the source's whole fluid milk record.",
        grams=grams,
    )


AGENT_ACCEPTANCE_CASES = [
    (
        "tomato sixty grams",
        [tomato_selection("raw tomato 60 g", grams=60)],
        None,
        None,
        None,
    ),
    (
        "half a tomato",
        [tomato_selection("half raw tomato")],
        [(0, "half raw tomato", 60)],
        None,
        None,
    ),
    (
        "quarter tomato",
        [tomato_selection("quarter raw tomato")],
        [(0, "quarter raw tomato", 30)],
        None,
        None,
    ),
    (
        "one tomato",
        [tomato_selection("1 raw tomato")],
        [(0, "1 raw tomato", 120)],
        None,
        None,
    ),
    (
        "large tomato",
        [tomato_selection("large raw tomato")],
        [(0, "large raw tomato", 180)],
        None,
        None,
    ),
    (
        "medium tomato",
        [tomato_selection("medium raw tomato")],
        [(0, "medium raw tomato", 120)],
        None,
        None,
    ),
    (
        "milk two hundred grams",
        [milk_selection("raw milk 200 g", grams=200)],
        None,
        None,
        None,
    ),
    (
        "half glass milk",
        [milk_selection("half raw milk")],
        [(0, "half raw milk", 120)],
        None,
        None,
    ),
    (
        "quarter glass milk",
        [milk_selection("quarter raw milk")],
        [(0, "quarter raw milk", 60)],
        None,
        None,
    ),
    (
        "tomato and milk",
        [
            tomato_selection("raw tomato 80 g", grams=80),
            milk_selection("raw milk 150 g", grams=150),
        ],
        None,
        None,
        None,
    ),
    (
        "small tomato, milk",
        [
            tomato_selection("small raw tomato"),
            milk_selection("raw milk 100 g", grams=100),
        ],
        [(0, "small raw tomato", 75)],
        None,
        None,
    ),
    (
        "a tomato and a branded bread",
        [
            tomato_selection("raw tomato 60 g", grams=60),
            pending("Harry's bread"),
        ],
        None,
        None,
        None,
    ),
    ("doctor johnson milk", [pending("Dr Johnson milk")], None, None, None),
    ("harrys bread", [pending("Harry's bread")], None, None, None),
    ("unknown exact carton", [pending("Example carton SKU 778899")], None, None, None),
    ("photo missing brand bar", [pending("Brand bar from unclear photo")], None, None, None),
    (
        "tomato plus unknown bottle",
        [
            tomato_selection("raw tomato 100 g", grams=100),
            pending("Unknown bottle"),
        ],
        None,
        None,
        None,
    ),
    (
        "milk plus exact crackers",
        [milk_selection("raw milk 100 g", grams=100), pending("Acme crackers")],
        None,
        None,
        None,
    ),
    (
        "two fuzzy items",
        [
            tomato_selection("small raw tomato"),
            milk_selection("half raw milk"),
        ],
        [(0, "small raw tomato", 75), (1, "half raw milk", 120)],
        None,
        None,
    ),
    (
        "pending meal",
        [pending("Harry's sandwich"), pending("Dr Johnson drink")],
        None,
        None,
        None,
    ),
    (
        "poisoned cache is ignored",
        [tomato_selection("raw tomato 60 g", grams=60)],
        None,
        "poisoned_cache",
        None,
    ),
    (
        "malformed semantic selection",
        [
            {
                "input": "raw tomato 60 g",
                "grams": 60,
                "selection": {"source_ref": "usda:105", "relation": "semantic_equivalent"},
            }
        ],
        None,
        None,
        "agent_plan_invalid",
    ),
    (
        "disabled USDA provider",
        [tomato_selection("raw tomato 60 g", grams=60)],
        None,
        "offline",
        "provider_disabled",
    ),
    (
        "disabled OFF provider",
        [
            selected(
                "unbranded bread 80 g",
                "off:0123456789012",
                "Interpreted the bread phrase as the source record.",
                grams=80,
            )
        ],
        None,
        "disable_off",
        "provider_disabled",
    ),
]


@pytest.mark.parametrize(
    ("voice", "items", "estimates", "setup", "expected_error"),
    AGENT_ACCEPTANCE_CASES,
    ids=[case[0] for case in AGENT_ACCEPTANCE_CASES],
)
def test_agent_intake_synthetic_end_to_end_acceptance_matrix(
    voice,
    items,
    estimates,
    setup,
    expected_error,
    user_db,
    monkeypatch,
    synthetic_providers,
    capsys,
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    if setup == "offline":
        monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    elif setup == "disable_off":
        monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    elif setup == "poisoned_cache":
        with connect(user_db) as connection:
            connection.execute(
                """INSERT INTO food_cache
                (name, kcal, protein, fat, carbs, source, lookup_query, resolution_mode, source_id)
                VALUES (?, ?, 99, 99, 99, 'poison', 'raw tomato', 'legacy', '105')""",
                ("tomatoes, red, ripe, raw, year round average", 999),
            )
    portion_estimates = (
        [estimate(index, input_phrase, grams) for index, input_phrase, grams in estimates]
        if estimates
        else None
    )

    code, result, _ = invoke_json(
        ["agent", "intake", "--plan", plan(*items, portion_estimates=portion_estimates)],
        capsys,
    )

    if expected_error:
        assert code == 2, voice
        assert result["error"]["code"] == expected_error
        if user_db.exists():
            with connect(user_db) as connection:
                assert connection.execute("SELECT count(*) FROM log_entries").fetchone()[0] == 0
        return

    assert code == 0, voice
    assert all(item["status"] in {"resolved", "pending_capture"} for item in result["items"])
    resolved = [item for item in result["items"] if item["status"] == "resolved"]
    resolved_names = {item["name"] for item in resolved}
    assert resolved_names <= {
        "tomatoes, red, ripe, raw, year round average",
        "milk, whole, fluid, 3.25% milkfat",
    }
    assert not any(
        forbidden in name
        for name in resolved_names
        for forbidden in ("banana", "powder", "cracker", "chocolate", "condensed")
    )
    assert all(
        item["selection_mode"] == "agent_generic"
        and item["resolution_mode"] == "generic_proxy"
        and item["provenance"] == "agent_selected"
        and item["source"] == "usda"
        and item["assumption"]
        for item in resolved
    )
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
