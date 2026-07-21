from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from nomnomcli.cli import main
from nomnomcli.db import connect
from nomnomcli.errors import NomnomError
from nomnomcli.foods import FoodRepository
from nomnomcli.models import Food
from nomnomcli.semantic import SemanticCandidate, SemanticIntent

BENCHMARK_PATH = Path(__file__).parent / "fixtures" / "semantic_resolution_cases.json"


def _generic_usda(name: str, source_id: int, *, data_type: str = "Foundation") -> Food:
    return Food(
        name=name,
        kcal=165,
        protein=31,
        fat=3.6,
        carbs=0,
        source="usda",
        fdc_id=source_id,
        source_id=str(source_id),
        provenance="usda",
        provider_data_type=data_type,
        categories=("Poultry Products",),
    )


def _off_food(
    name: str,
    source_id: str | None,
    *,
    brand: str | None = None,
    categories: tuple[str, ...] = ("Chicken products",),
) -> Food:
    return Food(
        name=name,
        kcal=180,
        protein=25,
        fat=8,
        carbs=1,
        source="openfoodfacts",
        source_id=source_id,
        barcode=source_id,
        brand=brand,
        categories=categories,
        provenance="openfoodfacts",
        resolution_mode="exact_product",
    )


class MockOFF:
    def __init__(self, results: dict[str, list[Food] | NomnomError] | None = None):
        self.results = results or {}
        self.calls: list[str] = []

    def search(self, query: str, page_size: int = 5) -> list[Food]:
        self.calls.append(query)
        result = self.results.get(query, [])
        if isinstance(result, NomnomError):
            raise result
        return result


class MockUSDA:
    def __init__(
        self,
        results: dict[str, tuple[Food, float] | NomnomError] | None = None,
    ):
        self.results = results or {}
        self.calls: list[str] = []

    def resolve(self, query: str, api_key: str) -> tuple[Food, float]:
        self.calls.append(query)
        result = self.results.get(
            query,
            NomnomError("food_not_found", f"No mocked USDA result for: {query}"),
        )
        if isinstance(result, NomnomError):
            raise result
        return result


def _repository(connection, monkeypatch, *, off=None, usda=None) -> FoodRepository:
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-only-key")
    return FoodRepository(
        connection,
        off_client=off or MockOFF(),
        usda_client=usda or MockUSDA(),
    )


def _counts(connection) -> dict[str, int]:
    return {
        table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("food_cache", "log_entries", "food_aliases", "recipes")
    }


@pytest.mark.parametrize(
    "case",
    json.loads(BENCHMARK_PATH.read_text(encoding="utf-8")),
    ids=lambda case: case["id"],
)
def test_mocked_semantic_benchmark_returns_transparent_no_write_plan(
    user_db, monkeypatch, case
):
    roasted = _generic_usda("Chicken breast, roasted", 171077)
    mixed_meat = _generic_usda(
        "Sausage, smoked, chicken, beef and pork", 777001, data_type="SR Legacy"
    )
    weak = NomnomError(
        "usda_low_confidence",
        "Weak candidate",
        details={"candidate": {"name": "Chicken roll", "confidence": 0.42}},
    )
    usda = MockUSDA(
        {
            "smoked chicken": (mixed_meat, 0.91),
            "chicken pastrami": weak,
            "chicken breast roasted": (roasted, 0.92),
        }
    )
    with connect(user_db) as connection:
        repository = _repository(connection, monkeypatch, usda=usda)
        before = _counts(connection)

        plan = repository.plan_resolution(case["original"], intent=case["intent"])

        assert plan == {
            "status": "resolution_plan",
            "would_write": False,
            "original": case["original"],
            "retrieval_query": case["expected_query"],
            "intent_version": 1,
            "resolution_origin": "semantic_candidate",
            "candidate_index": case["expected_candidate_index"],
            "relation": case["expected_relation"],
            "semantic_assumption": case["intent"]["candidates"][-1]["assumption"],
            "requires_confirmation": True,
            "name": "Chicken breast, roasted",
            "source": "usda",
            "source_id": "171077",
            "data_type": "Foundation",
            "confidence": 0.92,
            "resolution_mode": "generic_proxy",
            "provider_assumption": (
                "Brand not specified; used USDA generic proxy: Chicken breast, roasted."
            ),
        }
        assert _counts(connection) == before


def test_raw_query_is_first_and_safe_raw_result_skips_semantic_candidates(
    user_db, monkeypatch
):
    usda = MockUSDA(
        {"chicken breast roasted": (_generic_usda("Chicken breast, roasted", 171077), 0.93)}
    )
    intent = {
        "version": 1,
        "original": "chicken breast roasted",
        "brand_intent": False,
        "candidates": [
            {
                "query": "unreachable fallback",
                "relation": "generic_fallback",
                "assumption": "Not needed when raw succeeds.",
            }
        ],
    }
    with connect(user_db) as connection:
        repository = _repository(connection, monkeypatch, usda=usda)
        before = _counts(connection)
        plan = repository.plan_resolution("chicken breast roasted", intent=intent)

        assert plan["resolution_origin"] == "raw"
        assert plan["retrieval_query"] == "chicken breast roasted"
        assert plan["resolution_mode"] == "generic_proxy"
        assert plan["requires_confirmation"] is False
        assert "candidate_index" not in plan
        assert usda.calls == ["chicken breast roasted"]
        assert _counts(connection) == before


def test_relation_then_provider_quality_then_confidence_then_query_selects_deterministically(
    user_db, monkeypatch
):
    off = MockOFF(
        {
            "alpha chicken": [_off_food("Alpha chicken", "10000001")],
            "zeta chicken": [_off_food("Zeta chicken", "10000002")],
        }
    )
    usda = MockUSDA(
        {
            "beta chicken": (_generic_usda("Beta chicken", 2001), 0.81),
            "gamma chicken": (_generic_usda("Gamma chicken", 2002), 0.81),
        }
    )
    intent = {
        "version": 1,
        "original": "неизвестная курица",
        "brand_intent": False,
        "candidates": [
            {"query": "zeta chicken", "relation": "same_form"},
            {"query": "gamma chicken", "relation": "same_form"},
            {"query": "beta chicken", "relation": "same_form"},
        ],
    }
    with connect(user_db) as connection:
        repository = _repository(connection, monkeypatch, off=off, usda=usda)
        plan = repository.plan_resolution(intent["original"], intent=intent)

    assert plan["retrieval_query"] == "beta chicken"
    assert plan["source"] == "usda"
    assert plan["candidate_index"] == 2


def test_lexical_relation_priority_beats_provider_quality(user_db, monkeypatch):
    off = MockOFF({"literal chicken": [_off_food("Literal chicken", "10000001")]})
    usda = MockUSDA(
        {"fallback chicken": (_generic_usda("Fallback chicken", 2001), 0.99)}
    )
    intent = {
        "version": 1,
        "original": "сырая фраза",
        "brand_intent": False,
        "candidates": [
            {"query": "fallback chicken", "relation": "same_form"},
            {"query": "literal chicken", "relation": "lexical_equivalent"},
        ],
    }
    with connect(user_db) as connection:
        plan = _repository(connection, monkeypatch, off=off, usda=usda).plan_resolution(
            intent["original"], intent=intent
        )

    assert plan["retrieval_query"] == "literal chicken"
    assert plan["relation"] == "lexical_equivalent"


def test_higher_provider_confidence_wins_after_relation_and_quality(user_db, monkeypatch):
    usda = MockUSDA(
        {
            "lower chicken": (_generic_usda("Lower chicken", 2001), 0.81),
            "higher chicken": (_generic_usda("Higher chicken", 2002), 0.94),
        }
    )
    intent = {
        "version": 1,
        "original": "сырая фраза",
        "brand_intent": False,
        "candidates": [
            {"query": "lower chicken", "relation": "same_form"},
            {"query": "higher chicken", "relation": "same_form"},
        ],
    }
    with connect(user_db) as connection:
        plan = _repository(connection, monkeypatch, usda=usda).plan_resolution(
            intent["original"], intent=intent
        )

    assert plan["retrieval_query"] == "higher chicken"
    assert plan["confidence"] == 0.94


def test_safe_off_selection_does_not_depend_on_provider_result_order(user_db, monkeypatch):
    off = MockOFF(
        {
            "chicken slices": [
                _off_food("Zeta chicken slices", "10000002"),
                _off_food("Alpha chicken slices", "10000001"),
            ]
        }
    )
    intent = {
        "version": 1,
        "original": "куриные ломтики",
        "brand_intent": False,
        "candidates": [{"query": "chicken slices", "relation": "same_form"}],
    }
    with connect(user_db) as connection:
        plan = _repository(connection, monkeypatch, off=off).plan_resolution(
            intent["original"], intent=intent
        )

    assert plan["name"] == "Alpha chicken slices"
    assert plan["source_id"] == "10000001"


def test_raw_plan_exposes_provider_alternatives(user_db, monkeypatch):
    food = replace(
        _generic_usda("Chicken breast, roasted", 171077),
        alternatives=(
            {
                "name": "Chicken breast, baked",
                "fdc_id": 171078,
                "data_type": "SR Legacy",
                "confidence": 0.84,
            },
        ),
    )
    intent = {
        "version": 1,
        "original": "chicken breast roasted",
        "brand_intent": False,
        "candidates": [],
    }
    with connect(user_db) as connection:
        plan = _repository(
            connection,
            monkeypatch,
            usda=MockUSDA({intent["original"]: (food, 0.92)}),
        ).plan_resolution(intent["original"], intent=intent)

    assert plan["provider_alternatives"] == list(food.alternatives)


@pytest.mark.parametrize(
    ("original", "brand_intent"),
    [("0123456789012", False), ("Acme chicken 12345", False), ("Acme chicken", True)],
)
def test_original_exact_identity_cannot_be_bypassed_by_semantic_candidates(
    user_db, monkeypatch, original, brand_intent
):
    intent = {
        "version": 1,
        "original": original,
        "brand_intent": brand_intent,
        "candidates": [
            {
                "query": "chicken breast roasted",
                "relation": "generic_fallback",
                "assumption": "Unsafe attempted bypass.",
            }
        ],
    }
    usda = MockUSDA(
        {"chicken breast roasted": (_generic_usda("Chicken breast, roasted", 171077), 0.93)}
    )
    with connect(user_db) as connection:
        repository = _repository(connection, monkeypatch, usda=usda)
        before = _counts(connection)
        with pytest.raises(NomnomError) as raised:
            repository.plan_resolution(original, intent=intent)

        assert raised.value.code == "semantic_exact_capture_required"
        assert raised.value.details["would_write"] is False
        assert raised.value.details["original"] == original
        assert raised.value.details["intent_version"] == 1
        assert "chicken breast roasted" not in usda.calls
        assert _counts(connection) == before


def test_provider_detected_brand_cannot_be_bypassed_when_brand_intent_is_false(
    user_db, monkeypatch
):
    original = "Acme chicken"
    off = MockOFF({original: [_off_food("Chicken — Acme", None, brand="Acme")]})
    intent = {
        "version": 1,
        "original": original,
        "brand_intent": False,
        "candidates": [
            {
                "query": "chicken breast roasted",
                "relation": "generic_fallback",
                "assumption": "Must not erase the detected brand.",
            }
        ],
    }
    with connect(user_db) as connection:
        repository = _repository(connection, monkeypatch, off=off)
        with pytest.raises(NomnomError) as raised:
            repository.plan_resolution(original, intent=intent)

    assert raised.value.code == "semantic_exact_capture_required"
    assert off.calls == [original]


def test_semantic_candidate_can_never_return_exact_product(user_db, monkeypatch):
    off = MockOFF({"acme chicken": [_off_food("Chicken — Acme", "12345678", brand="Acme")]})
    intent = {
        "version": 1,
        "original": "курица",
        "brand_intent": False,
        "candidates": [{"query": "Acme chicken", "relation": "same_form"}],
    }
    with connect(user_db) as connection:
        repository = _repository(connection, monkeypatch, off=off)
        before = _counts(connection)
        with pytest.raises(NomnomError) as raised:
            repository.plan_resolution(intent["original"], intent=intent)

        assert raised.value.code == "semantic_resolution_refused"
        assert raised.value.details["would_write"] is False
        assert raised.value.details["rejected_candidates"][0]["reason"] == (
            "semantic_exact_product_forbidden"
        )
        assert _counts(connection) == before


def test_phase_a_explicitly_rejects_persistent_planning(user_db, monkeypatch):
    intent = {
        "version": 1,
        "original": "raw",
        "brand_intent": False,
        "candidates": [],
    }
    with connect(user_db) as connection:
        repository = _repository(connection, monkeypatch)
        before = _counts(connection)
        with pytest.raises(NomnomError) as raised:
            repository.plan_resolution("raw", intent=intent, persist=True)

        assert raised.value.code == "semantic_persistence_forbidden"
        assert _counts(connection) == before


def test_literal_smoked_chicken_rejects_mixed_meat_raw_result(user_db, monkeypatch):
    original = "smoked chicken"
    mixed_meat = _generic_usda(
        "Sausage, smoked, chicken, beef and pork", 777001, data_type="SR Legacy"
    )
    intent = {
        "version": 1,
        "original": original,
        "brand_intent": False,
        "candidates": [],
    }
    with connect(user_db) as connection:
        repository = _repository(
            connection,
            monkeypatch,
            usda=MockUSDA({original: (mixed_meat, 0.91)}),
        )
        before = _counts(connection)
        with pytest.raises(NomnomError) as raised:
            repository.plan_resolution(original, intent=intent)

        assert raised.value.code == "semantic_resolution_refused"
        assert raised.value.details["raw_error"]["details"]["reason"] == (
            "conflicting_species"
        )
        assert _counts(connection) == before


def test_unsafe_off_and_weak_usda_candidates_are_rejected_without_writes(
    user_db, monkeypatch
):
    original = "неизвестная курица"
    off = MockOFF(
        {
            "weak chicken": [
                _off_food(
                    "Chicken-flavored cheese",
                    "10000001",
                    categories=("Cheeses",),
                )
            ]
        }
    )
    usda = MockUSDA(
        {
            "weak chicken": NomnomError("usda_low_confidence", "Weak USDA candidate"),
        }
    )
    intent = {
        "version": 1,
        "original": original,
        "brand_intent": False,
        "candidates": [{"query": "weak chicken", "relation": "same_form"}],
    }
    with connect(user_db) as connection:
        repository = _repository(connection, monkeypatch, off=off, usda=usda)
        before = _counts(connection)
        with pytest.raises(NomnomError) as raised:
            repository.plan_resolution(original, intent=intent)

        assert raised.value.code == "semantic_resolution_refused"
        rejection = raised.value.details["rejected_candidates"][0]
        assert rejection["reason"] == "provider_rejected"
        assert rejection["provider_error"]["code"] == "usda_low_confidence"
        assert _counts(connection) == before


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda value: value.update(version=2), "unsupported_semantic_version"),
        (lambda value: value.update(original="changed"), "semantic_original_mismatch"),
        (lambda value: value.update(brand_intent="false"), "semantic_intent_malformed"),
        (
            lambda value: value.update(
                candidates=[
                    {"query": "a", "relation": "same_form"},
                    {"query": "b", "relation": "same_form"},
                    {"query": "c", "relation": "same_form"},
                    {"query": "d", "relation": "same_form"},
                ]
            ),
            "semantic_candidates_invalid",
        ),
        (
            lambda value: value.update(
                candidates=[
                    {"query": " Chicken  Breast ", "relation": "same_form"},
                    {"query": "chicken breast", "relation": "same_form"},
                ]
            ),
            "semantic_candidate_invalid",
        ),
        (
            lambda value: value.update(
                candidates=[{"query": "chicken", "relation": "closest"}]
            ),
            "semantic_candidate_invalid",
        ),
        (
            lambda value: value.update(
                candidates=[{"query": "chicken", "relation": "generic_fallback"}]
            ),
            "semantic_candidate_invalid",
        ),
    ],
)
def test_semantic_v1_contract_is_strict_and_structured(
    user_db, monkeypatch, mutate, code
):
    intent = {
        "version": 1,
        "original": "raw input",
        "brand_intent": False,
        "candidates": [],
    }
    mutate(intent)
    with connect(user_db) as connection:
        repository = _repository(connection, monkeypatch)
        before = _counts(connection)
        with pytest.raises(NomnomError) as raised:
            repository.plan_resolution("raw input", intent=intent)

        assert raised.value.code == code
        assert raised.value.details["would_write"] is False
        assert _counts(connection) == before


def test_cli_resolve_json_uses_missing_db_without_creating_it(
    user_db, monkeypatch, capsys
):
    plan = {
        "status": "resolution_plan",
        "would_write": False,
        "original": "raw",
        "retrieval_query": "raw",
        "intent_version": 1,
        "resolution_origin": "raw",
        "requires_confirmation": False,
        "name": "Raw",
        "source": "usda",
        "source_id": "1",
        "data_type": "Foundation",
        "confidence": 0.9,
        "resolution_mode": "generic_proxy",
    }
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setattr(
        FoodRepository,
        "plan_resolution",
        lambda self, original, intent, allow_remote=True, persist=False: plan,
        raising=False,
    )
    payload = json.dumps(
        {"version": 1, "original": "raw", "brand_intent": False, "candidates": []}
    )

    code = main(["resolve", "--food", "raw", "--intent-json", payload, "--json"])

    assert code == 0
    assert json.loads(capsys.readouterr().out) == plan
    assert not user_db.exists()


def test_cli_resolve_rejects_malformed_json_without_creating_db(user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))

    code = main(["resolve", "--food", "raw", "--intent-json", "{", "--json"])
    output = capsys.readouterr()

    assert code == 2
    assert output.out == ""
    error = json.loads(output.err)["error"]
    assert error["code"] == "semantic_intent_malformed"
    assert error["would_write"] is False
    assert error["original"] == "raw"
    assert not user_db.exists()


def test_brand_intent_rejects_raw_generic_proxy(user_db, monkeypatch):
    original = "Acme chicken"
    intent = {
        "version": 1,
        "original": original,
        "brand_intent": True,
        "candidates": [],
    }
    with connect(user_db) as connection:
        repository = _repository(connection, monkeypatch)
        repository._cache_food(_generic_usda(original, 171077), lookup_query=original)
        with pytest.raises(NomnomError) as raised:
            repository.plan_resolution(original, intent=intent)

    assert raised.value.code == "semantic_exact_capture_required"


def test_hyphenated_mixed_species_candidate_is_refused(user_db, monkeypatch):
    intent = {
        "version": 1,
        "original": "unknown sausage",
        "brand_intent": False,
        "candidates": [{"query": "chicken sausage", "relation": "same_form"}],
    }
    usda = MockUSDA(
        {"chicken sausage": (_generic_usda("Chicken-beef sausage", 171077), 0.92)}
    )
    with connect(user_db) as connection:
        repository = _repository(connection, monkeypatch, usda=usda)
        with pytest.raises(NomnomError) as raised:
            repository.plan_resolution(intent["original"], intent=intent)

    assert raised.value.code == "semantic_resolution_refused"
    assert raised.value.details["rejected_candidates"][0]["reason"] == "conflicting_species"


def test_preconstructed_intent_is_revalidated(user_db, monkeypatch):
    intent = SemanticIntent(
        version=2,
        original="raw input",
        brand_intent=False,
        candidates=(SemanticCandidate(0, "chicken", "same_form"),),
    )
    with connect(user_db) as connection:
        repository = _repository(connection, monkeypatch)
        with pytest.raises(NomnomError) as raised:
            repository.plan_resolution("raw input", intent=intent)

    assert raised.value.code == "unsupported_semantic_version"
