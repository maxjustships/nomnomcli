from __future__ import annotations

import json
from dataclasses import replace

import pytest

from nomnomcli.cli import main
from nomnomcli.db import connect
from nomnomcli.errors import NomnomError
from nomnomcli.foods import FoodRepository
from nomnomcli.models import Food
from nomnomcli.semantic import parse_resolution_intent


def _intent(original: str, candidates: list[dict], *, brand_intent: bool = False) -> dict:
    return {
        "version": 1,
        "original": original,
        "brand_intent": brand_intent,
        "candidates": candidates,
    }


def _generic_food(
    name: str,
    *,
    source: str = "usda",
    source_id: str = "171477",
    confidence: float = 0.9,
    provider_type: str = "Foundation",
) -> tuple[Food, float]:
    return (
        Food(
            name=name,
            kcal=165,
            protein=31,
            fat=3.6,
            carbs=1,
            source=source,
            fdc_id=int(source_id) if source == "usda" else None,
            barcode=source_id if source == "openfoodfacts" else None,
            categories=("poultry products",),
            source_id=source_id,
            provenance=source,
            provider_data_type=provider_type if source == "usda" else None,
        ),
        confidence,
    )


def _counts(repository: FoodRepository) -> dict[str, int]:
    return {
        table: repository.user_connection.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0]
        for table in ("food_cache", "log_entries", "food_aliases", "recipes")
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"version": 2, "original": "x", "brand_intent": False, "candidates": []},
        {"version": 1, "original": "x", "brand_intent": 0, "candidates": []},
        _intent("x", [{"query": " ", "relation": "same_form"}]),
        _intent(
            "x",
            [
                {"query": "Chicken", "relation": "same_form"},
                {"query": " chicken ", "relation": "lexical_equivalent"},
            ],
        ),
        _intent("x", [{"query": "chicken", "relation": "closest"}]),
        _intent("x", [{"query": "chicken", "relation": "generic_fallback"}]),
        _intent(
            "x",
            [
                {"query": str(index), "relation": "same_form"}
                for index in range(4)
            ],
        ),
    ],
)
def test_intent_v1_rejects_unbounded_or_invalid_payloads(payload):
    with pytest.raises(NomnomError) as caught:
        parse_resolution_intent(json.dumps(payload), expected_original="x")

    assert caught.value.code == "invalid_resolution_intent"
    assert caught.value.details["would_write"] is False


def test_intent_v1_requires_exact_original_match():
    payload = _intent(" курица ", [])

    with pytest.raises(NomnomError) as caught:
        parse_resolution_intent(json.dumps(payload), expected_original="курица")

    assert caught.value.code == "resolution_intent_original_mismatch"
    assert caught.value.details["original"] == "курица"
    assert caught.value.details["intent_original"] == " курица "


def test_raw_original_safe_resolution_wins_without_trying_semantic_candidates(
    repository, monkeypatch
):
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                "chicken breast roasted",
                [
                    {
                        "query": "fallback chicken",
                        "relation": "generic_fallback",
                        "assumption": "Used a less specific chicken preparation.",
                    }
                ],
            )
        ),
        expected_original="chicken breast roasted",
    )
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")

    def resolve(query, api_key):
        assert query == "chicken breast roasted"
        return _generic_food("chicken breast roasted")

    monkeypatch.setattr(repository.usda_client, "resolve", resolve)
    before = _counts(repository)

    plan = repository.plan_resolution("chicken breast roasted", intent=intent)

    assert plan["retrieval_query"] == "chicken breast roasted"
    assert "candidate_index" not in plan
    assert plan["resolution_mode"] == "generic_proxy"
    assert plan["would_write"] is False
    assert _counts(repository) == before


def test_russian_smoked_chicken_uses_visible_roasted_generic_fallback(
    repository, monkeypatch
):
    original = "курица сырокопченая"
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [
                    {"query": "smoked chicken", "relation": "same_form"},
                    {
                        "query": "chicken breast roasted",
                        "relation": "generic_fallback",
                        "assumption": "Roasted chicken loses the smoked and cured preparation.",
                    },
                ],
            )
        ),
        expected_original=original,
    )
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [])

    def resolve(query, api_key):
        if query == "chicken breast roasted":
            return _generic_food("chicken breast roasted")
        if query == "smoked chicken":
            raise NomnomError(
                "usda_low_confidence",
                "Mixed-meat smoked sausage is below the safe threshold",
                details={"candidate": {"name": "chicken, beef and pork smoked sausage"}},
            )
        raise NomnomError("food_not_found", f"No safe food for {query}")

    monkeypatch.setattr(repository.usda_client, "resolve", resolve)
    before = _counts(repository)

    plan = repository.plan_resolution(original, intent=intent)

    assert plan == {
        "would_write": False,
        "original": original,
        "retrieval_query": "chicken breast roasted",
        "intent_version": 1,
        "candidate_index": 1,
        "relation": "generic_fallback",
        "assumption": "Roasted chicken loses the smoked and cured preparation.",
        "provider_assumption": (
            "Brand not specified; used USDA generic proxy: chicken breast roasted."
        ),
        "provider": "usda",
        "source": "usda",
        "source_id": "171477",
        "provider_type": "Foundation",
        "confidence": 0.9,
        "resolution_mode": "generic_proxy",
        "alternatives": [],
    }
    assert _counts(repository) == before


def test_chicken_pastrami_same_form_route_is_safe_off_proxy(repository, monkeypatch):
    original = "куриная пастрома"
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [{"query": "chicken pastrami", "relation": "same_form"}],
            )
        ),
        expected_original=original,
    )
    off_food, _ = _generic_food(
        "Chicken pastrami — Example Deli",
        source="openfoodfacts",
        source_id="10000003",
    )
    off_food = replace(
        off_food,
        brand="Example Deli",
        categories=("chicken pastrami",),
    )
    monkeypatch.delenv("NOMNOM_USDA_KEY", raising=False)
    monkeypatch.setattr(
        repository.off_client,
        "search",
        lambda query, page_size=5: [off_food] if query == "chicken pastrami" else [],
    )

    plan = repository.plan_resolution(original, intent=intent)

    assert plan["candidate_index"] == 0
    assert plan["relation"] == "same_form"
    assert plan["source"] == "openfoodfacts"
    assert plan["resolution_mode"] == "generic_proxy"


def test_relation_then_provider_quality_order_semantic_plans(repository, monkeypatch):
    original = "описание курицы"
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [
                    {"query": "chicken pastrami", "relation": "same_form"},
                    {"query": "chicken breast roasted", "relation": "same_form"},
                ],
            )
        ),
        expected_original=original,
    )
    off_food, _ = _generic_food(
        "Chicken pastrami",
        source="openfoodfacts",
        source_id="10000003",
    )
    off_food = replace(off_food, categories=("chicken pastrami",))
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setattr(
        repository.off_client,
        "search",
        lambda query, page_size=5: [off_food] if query == "chicken pastrami" else [],
    )

    def resolve(query, api_key):
        if query == "chicken breast roasted":
            return _generic_food("chicken breast roasted", confidence=0.81)
        raise NomnomError("food_not_found", f"No USDA food for {query}")

    monkeypatch.setattr(repository.usda_client, "resolve", resolve)

    plan = repository.plan_resolution(original, intent=intent)

    assert plan["candidate_index"] == 1
    assert plan["source"] == "usda"
    assert plan["confidence"] == 0.81


@pytest.mark.parametrize(
    ("original", "brand_intent"),
    [("0123456789012", False), ("chicken breast 12345", False), ("Acme mystery chicken", False)],
)
def test_original_barcode_sku_or_explicit_brand_cannot_be_bypassed(
    repository, monkeypatch, original, brand_intent
):
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [{"query": "chicken breast roasted", "relation": "same_form"}],
                brand_intent=brand_intent,
            )
        ),
        expected_original=original,
    )
    branded, _ = _generic_food(
        "Different chicken — Acme",
        source="openfoodfacts",
        source_id="10000009",
    )
    branded = replace(branded, brand="Acme", categories=("chicken",))
    monkeypatch.setattr(
        repository.off_client,
        "search",
        lambda query, page_size=5: [branded] if "Acme" in query else [],
    )
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setattr(
        repository.usda_client,
        "resolve",
        lambda query, api_key: _generic_food("chicken breast roasted"),
    )
    before = _counts(repository)

    with pytest.raises(NomnomError) as caught:
        repository.plan_resolution(original, intent=intent)

    assert caught.value.code == "exact_resolution_required"
    assert caught.value.details["would_write"] is False
    assert _counts(repository) == before


def test_all_unsafe_candidates_return_structured_failure_without_writes(
    repository, monkeypatch
):
    original = "курица сырокопченая"
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [{"query": "smoked chicken", "relation": "same_form"}],
            )
        ),
        expected_original=original,
    )
    unsafe, _ = _generic_food(
        "Beef sausage — Example Meat",
        source="openfoodfacts",
        source_id="999",
    )
    unsafe = replace(unsafe, brand="Example Meat", categories=("beef sausages",))
    monkeypatch.delenv("NOMNOM_USDA_KEY", raising=False)
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [unsafe])
    before = _counts(repository)

    with pytest.raises(NomnomError) as caught:
        repository.plan_resolution(original, intent=intent)

    assert caught.value.code == "semantic_resolution_not_found"
    assert caught.value.details["would_write"] is False
    assert caught.value.as_dict()["error"]["would_write"] is False
    assert caught.value.details["failures"][0]["candidate_index"] == 0
    assert _counts(repository) == before


def test_weak_mocked_usda_candidate_is_rejected_at_planning_boundary(
    repository, monkeypatch
):
    original = "курица сырокопченая"
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [{"query": "smoked chicken", "relation": "same_form"}],
            )
        ),
        expected_original=original,
    )
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.setattr(
        repository.usda_client,
        "resolve",
        lambda query, api_key: _generic_food(
            "chicken beef pork smoked sausage", confidence=0.77
        ),
    )

    with pytest.raises(NomnomError) as caught:
        repository.plan_resolution(original, intent=intent)

    assert caught.value.code == "semantic_resolution_not_found"
    assert caught.value.details["failures"][0]["error"]["code"] == (
        "provider_low_confidence"
    )


def test_brand_intent_rejects_raw_generic_resolution(repository, monkeypatch):
    original = "special chicken"
    intent = parse_resolution_intent(
        json.dumps(_intent(original, [], brand_intent=True)),
        expected_original=original,
    )
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.setattr(
        repository.usda_client,
        "resolve",
        lambda query, api_key: _generic_food("special chicken"),
    )

    with pytest.raises(NomnomError) as caught:
        repository.plan_resolution(original, intent=intent)

    assert caught.value.code == "exact_resolution_required"


def test_cli_resolve_outputs_plan_and_never_changes_database(
    user_db, monkeypatch, capsys
):
    original = "курица сырокопченая"
    payload = _intent(
        original,
        [
            {
                "query": "chicken breast roasted",
                "relation": "generic_fallback",
                "assumption": "Roasted chicken loses the smoked preparation.",
            }
        ],
    )
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setattr("nomnomcli.off.OpenFoodFactsClient.search", lambda *args, **kwargs: [])

    def resolve(client, query, api_key):
        if query == "chicken breast roasted":
            return _generic_food("chicken breast roasted")
        raise NomnomError("food_not_found", f"No USDA food for {query}")

    monkeypatch.setattr("nomnomcli.usda.USDAClient.resolve", resolve)
    with connect(user_db) as connection:
        before = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("food_cache", "log_entries", "food_aliases", "recipes")
        }

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(payload),
            "--json",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert code == 0
    assert result["would_write"] is False
    assert result["original"] == original
    with connect(user_db) as connection:
        after = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("food_cache", "log_entries", "food_aliases", "recipes")
        }
    assert after == before
