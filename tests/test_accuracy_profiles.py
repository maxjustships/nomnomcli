from __future__ import annotations

import json

import pytest

from nomnomcli.agent import discover_candidates, parse_agent_plan, resolve_agent_plan
from nomnomcli.config import ProviderConfig
from nomnomcli.errors import NomnomError
from nomnomcli.models import Food


def generic_food(name: str = "sandwich bread", source_id: str = "7001") -> Food:
    return Food(
        name=name,
        kcal=250,
        protein=9,
        fat=4,
        carbs=45,
        source="usda",
        fdc_id=int(source_id),
        source_id=source_id,
        provenance="usda",
        provider_data_type="Foundation",
        categories=("synthetic",),
    )


class EmptyOFF:
    def search(self, query, page_size=10):
        return []


class UnavailableOFF:
    def search(self, query, page_size=10):
        raise NomnomError("openfoodfacts_unavailable", "Synthetic text outage")


class ReplayOFF:
    def __init__(self):
        self.food = Food(
            name="sandwich bread — Harris",
            kcal=250,
            protein=9,
            fat=4,
            carbs=45,
            source="openfoodfacts",
            barcode="0200000012001",
            source_id="0200000012001",
            provenance="openfoodfacts",
            brand="Harris",
            categories=("bread",),
        )

    def search(self, query, page_size=10):
        return [self.food]

    def product_by_barcode(self, barcode):
        return self.food


class EmptyUSDA:
    def candidates(self, query, api_key):
        return []


class ReplayUSDA:
    def __init__(self, food=None):
        self.food = food or generic_food()
        self.searches = []
        self.refetches = []

    def candidates(self, query, api_key):
        self.searches.append(query)
        return [(self.food, 0.9)]

    def food_by_fdc_id(self, fdc_id, api_key):
        self.refetches.append(fdc_id)
        return self.food


def profile_config(tmp_path, profile):
    return ProviderConfig(
        environ={
            "NOMNOM_ACCURACY_PROFILE": profile,
            "NOMNOM_USDA_KEY": "synthetic-placeholder",
        },
        config_path=tmp_path / "config.toml",
    )


def branded_plan(profile, receipt, *, risk=False, source_ref="usda:7001"):
    selection = {
        "source_ref": source_ref,
        "relation": "branded_same_type_generic",
        "assumption": (
            "Harris brand/SKU was not exact; used source-backed generic sandwich bread "
            "after provider text discovery."
        ),
        "discovery_receipt": receipt,
    }
    if risk:
        selection["risk_disposition"] = "material_risk_accepted"
    return {
        "version": 2,
        "accuracy_profile": profile,
        "items": [
            {
                "input": "Harris sandwich bread two slices",
                "grams": 56,
                "selection": selection,
            }
        ],
    }


def test_practical_plan_schema_accepts_search_first_branded_same_type_fallback():
    payload = branded_plan("practical", "0" * 64)

    parsed = parse_agent_plan(json.dumps(payload))

    assert parsed.accuracy_profile == "practical"
    assert parsed.items[0].selection is not None
    assert parsed.items[0].selection.relation == "branded_same_type_generic"


def test_practical_branded_fallback_revalidates_search_and_persists_evidence(tmp_path):
    config = profile_config(tmp_path, "practical")
    usda = ReplayUSDA()
    discovery = discover_candidates(
        "Harris sandwich bread two slices",
        provider_config=config,
        off_client=EmptyOFF(),
        usda_client=usda,
    )
    parsed = parse_agent_plan(
        json.dumps(branded_plan("practical", discovery["discovery_receipt"]))
    )

    result = resolve_agent_plan(
        parsed,
        provider_config=config,
        off_client=EmptyOFF(),
        usda_client=usda,
    )

    item = result["items"][0]
    assert result["complete"] is True
    assert item["selection_mode"] == "agent_branded_generic_fallback"
    assert item["selection_relation"] == "branded_same_type_generic"
    assert item["resolution_mode"] == "generic_proxy"
    assert item["provenance"] == "agent_selected"
    assert item["accuracy_profile"] == "practical"
    assert item["text_search"]["brand_match_status"] == "no_usable_brand_match"
    assert item["discovery_receipt"] == discovery["discovery_receipt"]
    assert usda.searches == [
        "Harris sandwich bread two slices",
        "Harris sandwich bread two slices",
    ]
    assert usda.refetches == [7001]


def test_branded_fallback_rejects_forged_or_stale_discovery_receipt(tmp_path):
    config = profile_config(tmp_path, "practical")
    usda = ReplayUSDA()
    parsed = parse_agent_plan(json.dumps(branded_plan("practical", "0" * 64)))

    with pytest.raises(NomnomError) as caught:
        resolve_agent_plan(
            parsed,
            provider_config=config,
            off_client=EmptyOFF(),
            usda_client=usda,
        )

    assert caught.value.code == "agent_discovery_evidence_mismatch"
    assert usda.refetches == []


def test_practical_branded_fallback_records_partial_provider_outage(tmp_path):
    config = profile_config(tmp_path, "practical")
    usda = ReplayUSDA()
    discovery = discover_candidates(
        "Harris sandwich bread 80 g",
        provider_config=config,
        off_client=UnavailableOFF(),
        usda_client=usda,
    )
    parsed = parse_agent_plan(
        json.dumps(
            {
                **branded_plan("practical", discovery["discovery_receipt"]),
                "items": [
                    {
                        **branded_plan(
                            "practical", discovery["discovery_receipt"]
                        )["items"][0],
                        "input": "Harris sandwich bread 80 g",
                    }
                ],
            }
        )
    )

    result = resolve_agent_plan(
        parsed,
        provider_config=config,
        off_client=UnavailableOFF(),
        usda_client=usda,
    )

    search = result["items"][0]["text_search"]
    assert search["status"] == "partial"
    assert search["providers"]["openfoodfacts"]["status"] == "unavailable"
    assert search["brand_match_status"] == "no_usable_brand_match"


def test_provider_text_brand_match_remains_probable_not_exact(tmp_path):
    config = profile_config(tmp_path, "practical")
    off = ReplayOFF()
    usda = EmptyUSDA()
    raw = "Harris sandwich bread 80 g"
    discovery = discover_candidates(
        raw,
        provider_config=config,
        off_client=off,
        usda_client=usda,
    )
    payload = {
        "version": 2,
        "accuracy_profile": "practical",
        "items": [
            {
                "input": raw,
                "grams": 80,
                "selection": {
                    "source_ref": "off:0200000012001",
                    "relation": "probable_brand_match",
                    "assumption": (
                        "Provider text match is probable only; barcode was not supplied."
                    ),
                    "discovery_receipt": discovery["discovery_receipt"],
                },
            }
        ],
    }

    result = resolve_agent_plan(
        parse_agent_plan(json.dumps(payload)),
        provider_config=config,
        off_client=off,
        usda_client=usda,
    )

    item = result["items"][0]
    assert item["resolution_mode"] == "probable_product"
    assert item["selection_mode"] == "agent_probable_brand_match"
    assert item["resolution_mode"] != "exact_product"


def test_balanced_requires_material_risk_and_exact_forbids_branded_fallback(tmp_path):
    balanced = profile_config(tmp_path, "balanced")
    usda = ReplayUSDA()
    discovery = discover_candidates(
        "Harris sandwich bread two slices",
        provider_config=balanced,
        off_client=EmptyOFF(),
        usda_client=usda,
    )
    with pytest.raises(NomnomError) as missing:
        parse_agent_plan(
            json.dumps(branded_plan("balanced", discovery["discovery_receipt"]))
        )
    assert missing.value.code == "agent_plan_invalid"

    accepted = parse_agent_plan(
        json.dumps(
            branded_plan("balanced", discovery["discovery_receipt"], risk=True)
        )
    )
    assert resolve_agent_plan(
        accepted,
        provider_config=balanced,
        off_client=EmptyOFF(),
        usda_client=usda,
    )["complete"]

    exact = profile_config(tmp_path, "exact")
    exact_discovery = discover_candidates(
        "Harris sandwich bread two slices",
        provider_config=exact,
        off_client=EmptyOFF(),
        usda_client=usda,
    )
    exact_plan = parse_agent_plan(
        json.dumps(branded_plan("exact", exact_discovery["discovery_receipt"]))
    )
    searches_before_exact_intake = list(usda.searches)
    refetches_before_exact_intake = list(usda.refetches)
    with pytest.raises(NomnomError) as forbidden:
        resolve_agent_plan(
            exact_plan,
            provider_config=exact,
            off_client=EmptyOFF(),
            usda_client=usda,
        )
    assert forbidden.value.code == "accuracy_profile_exact_required"
    assert usda.searches == searches_before_exact_intake
    assert usda.refetches == refetches_before_exact_intake


def test_semantic_type_floor_rejects_egg_to_cheese_before_nutrition(tmp_path):
    config = profile_config(tmp_path, "practical")
    cheese = ReplayUSDA(generic_food("cheese", "7002"))
    legacy_plan = {
        "version": 1,
        "items": [
            {
                "input": "egg 50 g",
                "grams": 50,
                "selection": {
                    "source_ref": "usda:7002",
                    "relation": "semantic_equivalent",
                    "assumption": "Incorrect external semantic proposal.",
                },
            }
        ],
    }

    with pytest.raises(NomnomError) as caught:
        resolve_agent_plan(
            parse_agent_plan(json.dumps(legacy_plan)),
            provider_config=config,
            off_client=EmptyOFF(),
            usda_client=cheese,
        )

    assert caught.value.code == "agent_semantic_type_mismatch"


def test_profile_defaults_preserve_legacy_upgrade_seams(tmp_path):
    missing = ProviderConfig(environ={}, config_path=tmp_path / "missing.toml")
    assert missing.accuracy_profile() == "balanced"
    assert missing.portion_policy() == "strict"
    assert missing.generic_proxy_policy() == "allow_for_unbranded"

    practical = profile_config(tmp_path, "practical")
    assert practical.portion_policy() == "estimate"
    exact = profile_config(tmp_path, "exact")
    assert exact.portion_policy() == "strict"
    assert exact.generic_proxy_policy() == "allow_for_unbranded"


def test_stored_profile_is_owner_config_and_preserves_legacy_policy_and_key(tmp_path):
    path = tmp_path / "config.toml"
    config = ProviderConfig(environ={}, config_path=path)
    config.store_usda_key("synthetic-placeholder")
    path.write_text(
        path.read_text(encoding="utf-8")
        + '\n[resolution]\ngeneric_proxy_policy = "ask"\nportion_policy = "strict"\n',
        encoding="utf-8",
    )

    config.store_accuracy_profile("practical")

    assert config.accuracy_profile() == "practical"
    assert config.generic_proxy_policy() == "ask"
    assert config.portion_policy() == "strict"
    assert config.usda_credential().value == "synthetic-placeholder"


def test_malformed_profile_is_a_structured_error(tmp_path):
    config = ProviderConfig(
        environ={"NOMNOM_ACCURACY_PROFILE": "seven"},
        config_path=tmp_path / "config.toml",
    )

    with pytest.raises(NomnomError) as caught:
        config.accuracy_profile()

    assert caught.value.code == "accuracy_profile_invalid"
    assert caught.value.details["allowed"] == ["practical", "balanced", "exact"]


def test_exact_profile_rejects_fuzzy_portion_plan():
    payload = {
        "version": 2,
        "accuracy_profile": "exact",
        "items": [{"input": "one egg", "source_ref": "usda:7003"}],
        "portion_estimates": {
            "items": [
                {
                    "item_index": 0,
                    "input": "one egg",
                    "grams": 50,
                    "lower_grams": 40,
                    "upper_grams": 60,
                    "confidence": 0.7,
                    "method": "agent_estimate",
                    "assumption": "External estimate.",
                }
            ]
        },
    }

    with pytest.raises(NomnomError) as caught:
        parse_agent_plan(json.dumps(payload))

    assert caught.value.code == "agent_plan_invalid"
