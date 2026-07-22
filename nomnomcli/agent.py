from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, replace

from nomnomcli.config import ProviderConfig
from nomnomcli.errors import NomnomError
from nomnomcli.foods import _comparison_token, _query_has_sku
from nomnomcli.models import Food, scale_food, total_items
from nomnomcli.off import OpenFoodFactsClient
from nomnomcli.parser import (
    BARE_PIECE_COUNT,
    DESCRIPTOR_PIECE,
    FRACTION_PIECE,
    LEADING_PER_PIECE_QUANTITY,
    LEADING_QUANTITY,
    PER_PIECE_QUANTITY,
    TRAILING_QUANTITY,
)
from nomnomcli.portions import PortionEstimate, parse_portion_estimates
from nomnomcli.usda import USDAClient

AGENT_PLAN_VERSION = 1
PENDING_CAPTURE = {"status": "pending_capture", "action": "photo_or_barcode"}
AGENT_SELECTION_RELATION = "semantic_equivalent"
GENERIC_USDA_TYPES = frozenset({"foundation", "sr legacy"})
STATUS_ORDER = {
    "agent_selection_eligible": 0,
    "pending_capture_required": 1,
    "identity_rejected": 2,
}


@dataclass(frozen=True, slots=True)
class AgentSelection:
    source_ref: str
    relation: str
    assumption: str


@dataclass(frozen=True, slots=True)
class AgentPlanItem:
    input: str
    grams: float | None
    source_ref: str | None
    selection: AgentSelection | None
    pending_capture: bool
    portion_estimate: PortionEstimate | None


@dataclass(frozen=True, slots=True)
class AgentPlan:
    items: tuple[AgentPlanItem, ...]


def _invalid_plan(message: str, *, item_index: int | None = None) -> NomnomError:
    details = {
        "version": AGENT_PLAN_VERSION,
        "allowed_item_fields": [
            "grams",
            "input",
            "pending_capture",
            "selection",
            "source_ref",
        ],
        "selection_fields": ["assumption", "relation", "source_ref"],
        "prohibited": ["calories", "carbs", "fat", "kcal", "macros", "nutrition", "protein"],
    }
    if item_index is not None:
        details["item_index"] = item_index
    return NomnomError("agent_plan_invalid", message, details=details)


def _positive_number(value, *, item_index: int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid_plan("grams must be a finite positive number", item_index=item_index)
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise _invalid_plan("grams must be a finite positive number", item_index=item_index)
    return number


def _validate_source_ref(value, *, item_index: int) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise NomnomError(
            "agent_source_ref_invalid",
            "source_ref must be one canonical opaque provider reference",
            details={"item_index": item_index},
        )
    match = re.fullmatch(r"(usda|off):([^:]+)", value)
    if not match:
        raise NomnomError(
            "agent_source_ref_invalid",
            "source_ref must use usda:ID or off:BARCODE",
            details={"item_index": item_index, "source_ref": value},
        )
    provider, source_id = match.groups()
    if provider == "usda":
        if not source_id.isdigit() or int(source_id) <= 0 or str(int(source_id)) != source_id:
            raise NomnomError(
                "agent_source_ref_invalid",
                "USDA source references require a positive canonical FDC id",
                details={"item_index": item_index, "source_ref": value},
            )
    elif not source_id.isdigit() or len(source_id) not in {8, 12, 13, 14}:
        raise NomnomError(
            "agent_source_ref_invalid",
            "Open Food Facts source references require a valid barcode",
            details={"item_index": item_index, "source_ref": value},
        )
    return value


def _parse_selection(value, *, item_index: int) -> AgentSelection:
    required = {"source_ref", "relation", "assumption"}
    if not isinstance(value, dict) or set(value) != required:
        raise _invalid_plan(
            "selection must contain only source_ref, relation, and assumption",
            item_index=item_index,
        )
    source_ref = value["source_ref"]
    relation = value["relation"]
    assumption = value["assumption"]
    if not isinstance(source_ref, str) or not source_ref:
        raise _invalid_plan("selection source_ref must be a nonempty string", item_index=item_index)
    if not isinstance(relation, str) or relation != AGENT_SELECTION_RELATION:
        raise _invalid_plan(
            f"selection relation must be {AGENT_SELECTION_RELATION}", item_index=item_index
        )
    if (
        not isinstance(assumption, str)
        or not assumption.strip()
        or assumption != assumption.strip()
        or len(assumption) > 1000
    ):
        raise _invalid_plan(
            "selection assumption must be a nonempty trimmed human-readable string",
            item_index=item_index,
        )
    return AgentSelection(
        source_ref=_validate_source_ref(source_ref, item_index=item_index),
        relation=relation,
        assumption=assumption,
    )


def parse_agent_plan(value: str) -> AgentPlan:
    try:
        payload = json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise _invalid_plan("--plan must be valid inline JSON") from exc
    if not isinstance(payload, dict):
        raise _invalid_plan("Agent plan must be one JSON object")
    allowed_top = {"version", "items", "portion_estimates"}
    if set(payload) - allowed_top or not {"version", "items"} <= set(payload):
        raise _invalid_plan("Agent plan contains missing or unknown top-level fields")
    if isinstance(payload["version"], bool) or payload["version"] != AGENT_PLAN_VERSION:
        raise _invalid_plan(f"Agent plan version must be {AGENT_PLAN_VERSION}")
    entries = payload["items"]
    if not isinstance(entries, list) or not entries:
        raise _invalid_plan("Agent plan items must be a nonempty array")
    if len(entries) > 100:
        raise _invalid_plan("Agent plan supports at most 100 items")

    estimates = None
    if "portion_estimates" in payload:
        estimates = parse_portion_estimates(
            json.dumps(payload["portion_estimates"], ensure_ascii=False)
        )

    parsed = []
    seen_refs: set[str] = set()
    allowed_item = {"input", "grams", "source_ref", "selection", "pending_capture"}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) - allowed_item or "input" not in entry:
            raise _invalid_plan(
                "Each agent item must contain only documented fields", item_index=index
            )
        input_phrase = entry["input"]
        if (
            not isinstance(input_phrase, str)
            or not input_phrase.strip()
            or input_phrase != input_phrase.strip()
            or len(input_phrase) > 1000
        ):
            raise _invalid_plan(
                "input must be a nonempty trimmed user-visible string", item_index=index
            )
        has_ref = "source_ref" in entry
        has_selection = "selection" in entry
        has_pending = "pending_capture" in entry
        if sum((has_ref, has_selection, has_pending)) != 1:
            raise _invalid_plan(
                "Each item requires exactly one source_ref, selection, or pending_capture state",
                item_index=index,
            )
        if has_pending and entry["pending_capture"] != PENDING_CAPTURE:
            raise _invalid_plan(
                "pending_capture must request the documented photo_or_barcode action",
                item_index=index,
            )

        selection = (
            _parse_selection(entry["selection"], item_index=index) if has_selection else None
        )
        source_ref = (
            _validate_source_ref(entry["source_ref"], item_index=index) if has_ref else None
        )
        selected_ref = selection.source_ref if selection is not None else source_ref
        if selected_ref is not None:
            if selected_ref in seen_refs:
                raise NomnomError(
                    "agent_source_ref_duplicate",
                    "A source reference may appear only once in an intake plan",
                    details={"item_index": index, "source_ref": selected_ref},
                )
            seen_refs.add(selected_ref)

        grams = _positive_number(entry["grams"], item_index=index) if "grams" in entry else None
        portion_estimate = estimates.entry_for(index, input_phrase) if estimates else None
        if grams is not None and portion_estimate is not None:
            raise _invalid_plan(
                "A measured grams value cannot also have a portion estimate", item_index=index
            )
        if grams is None and portion_estimate is not None:
            estimates.mark_used(index)
        if (has_ref or has_selection) and grams is None and portion_estimate is None:
            raise _invalid_plan(
                "A resolved source item requires grams or an external portion estimate",
                item_index=index,
            )
        parsed.append(
            AgentPlanItem(
                input=input_phrase,
                grams=grams,
                source_ref=source_ref,
                selection=selection,
                pending_capture=has_pending,
                portion_estimate=portion_estimate,
            )
        )
    if estimates is not None:
        estimates.ensure_all_used()
    return AgentPlan(tuple(parsed))


def _identity_query(input_phrase: str) -> str:
    cleaned = " ".join(input_phrase.strip().split())
    for pattern in (
        PER_PIECE_QUANTITY,
        LEADING_PER_PIECE_QUANTITY,
        TRAILING_QUANTITY,
        LEADING_QUANTITY,
        DESCRIPTOR_PIECE,
        FRACTION_PIECE,
        BARE_PIECE_COUNT,
    ):
        match = pattern.match(cleaned)
        if match and match.groupdict().get("food"):
            return " ".join(match.group("food").strip(" -").split())
    return cleaned


def _ordered_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        _comparison_token(token)
        for token in re.findall(r"\w+(?:['’]\w+)*", value.casefold().replace("ё", "е"))
    )


def _source_name(food: Food) -> str:
    return food.name.split(" — ", 1)[0] if food.source == "openfoodfacts" else food.name


def _generic_identity_is_safe(query: str, food: Food) -> bool:
    query_tokens = _ordered_tokens(query)
    candidate_tokens = _ordered_tokens(_source_name(food))
    return bool(query_tokens) and candidate_tokens == query_tokens


def _source_supports_agent_generic(food: Food) -> bool:
    if food.brand:
        return False
    if food.source == "usda":
        return (
            food.fdc_id is not None
            and food.source_id == str(food.fdc_id)
            and (food.provider_data_type or "").casefold() in GENERIC_USDA_TYPES
        )
    if food.source == "openfoodfacts":
        return bool(food.barcode and food.source_id == food.barcode)
    return False


def _candidate_status(query: str, food: Food) -> str:
    if food.brand or _query_has_sku(query):
        return "pending_capture_required"
    return (
        "agent_selection_eligible" if _source_supports_agent_generic(food) else "identity_rejected"
    )


def _direct_source_ref_status(query: str, food: Food) -> str:
    source_status = _candidate_status(query, food)
    if source_status != "agent_selection_eligible":
        return source_status
    return (
        "generic_proxy_eligible" if _generic_identity_is_safe(query, food) else "identity_rejected"
    )


def _candidate_dict(query: str, food: Food) -> dict:
    source_id = food.source_id or (str(food.fdc_id) if food.fdc_id is not None else None)
    candidate_status = _candidate_status(query, food)
    return {
        "source_ref": f"{'off' if food.source == 'openfoodfacts' else food.source}:{source_id}",
        "provider": food.source,
        "source_id": source_id,
        "canonical_name": food.name,
        "type": food.provider_data_type,
        "category": food.categories[0] if food.categories else None,
        "brand": food.brand,
        "candidate_status": candidate_status,
        "direct_source_ref_eligible": (
            candidate_status == "agent_selection_eligible"
            and _direct_source_ref_status(query, food) == "generic_proxy_eligible"
        ),
    }


def _provider_error(error: NomnomError) -> dict:
    return {"code": error.code, "message": error.message, "details": error.details}


def discover_candidates(
    input_phrase: str,
    *,
    provider_config: ProviderConfig | None = None,
    off_client: OpenFoodFactsClient | None = None,
    usda_client: USDAClient | None = None,
) -> dict:
    if not isinstance(input_phrase, str) or not input_phrase.strip():
        raise NomnomError("agent_input_invalid", "Candidate input must not be empty")
    query = _identity_query(input_phrase)
    config = provider_config or ProviderConfig()
    errors = {}
    foods: list[Food] = []
    offline = os.getenv("NOMNOM_OFFLINE", "").strip() == "1"

    if offline or os.getenv("NOMNOM_DISABLE_OFF", "").strip() == "1":
        errors["openfoodfacts"] = {
            "code": "provider_disabled",
            "message": "Open Food Facts discovery is disabled",
            "details": {},
        }
    else:
        try:
            foods.extend((off_client or OpenFoodFactsClient()).search(query, page_size=10))
        except NomnomError as exc:
            errors["openfoodfacts"] = _provider_error(exc)

    credential = None if offline else config.usda_credential()
    if credential is None:
        errors["usda"] = {
            "code": "usda_not_configured",
            "message": "USDA discovery is not configured",
            "details": {"optional": True},
        }
    else:
        try:
            foods.extend(
                food
                for food, _ in (usda_client or USDAClient()).candidates(query, credential.value)
            )
        except NomnomError as exc:
            errors["usda"] = _provider_error(exc)

    candidates = [_candidate_dict(query, food) for food in foods if food.source_id]
    candidates.sort(
        key=lambda item: (
            STATUS_ORDER[item["candidate_status"]],
            0 if item["provider"] == "usda" else 1,
            item["canonical_name"].casefold(),
            item["source_ref"],
        )
    )
    result = {
        "version": AGENT_PLAN_VERSION,
        "input": input_phrase,
        "query": query,
        "candidates": candidates,
    }
    if errors:
        result["provider_errors"] = errors
    return result


def _generic_proxy(food: Food, selection: AgentSelection | None = None) -> Food:
    source_id = food.source_id or (str(food.fdc_id) if food.fdc_id is not None else "unknown")
    assumption = (
        selection.assumption
        if selection is not None
        else (
            f"Source-backed {food.source} generic proxy {food.name} ({source_id}) "
            "matched the raw input literally."
        )
    )
    return replace(
        food,
        resolution_mode="generic_proxy",
        assumption=assumption,
        provenance="agent_selected" if selection is not None else food.provenance,
    )


def _apply_generic_policy(food: Food, config: ProviderConfig) -> None:
    policy = config.generic_proxy_policy()
    if policy == "allow_for_unbranded":
        return
    candidate = _candidate_dict(food.name, food)
    if policy == "ask":
        raise NomnomError(
            "generic_proxy_confirmation_required",
            f"Confirm the generic proxy for: {food.name}",
            details={"candidate": candidate, "policy": policy},
        )
    raise NomnomError(
        "exact_resolution_required",
        f"Exact product resolution is required for: {food.name}",
        details={"candidate": candidate, "policy": policy, "action": "photo_or_barcode"},
    )


def _refetch_source(
    item: AgentPlanItem,
    *,
    config: ProviderConfig,
    off_client: OpenFoodFactsClient,
    usda_client: USDAClient,
) -> Food:
    source_ref = item.selection.source_ref if item.selection is not None else item.source_ref
    assert source_ref is not None
    provider, source_id = source_ref.split(":", 1)
    offline = os.getenv("NOMNOM_OFFLINE", "").strip() == "1"
    off_disabled = os.getenv("NOMNOM_DISABLE_OFF", "").strip() == "1"
    if offline or provider == "off" and off_disabled:
        provider_name = "Open Food Facts" if provider == "off" else "USDA"
        setting = "NOMNOM_OFFLINE" if offline else "NOMNOM_DISABLE_OFF"
        raise NomnomError(
            "provider_disabled",
            f"{provider_name} source re-fetch is disabled",
            details={
                "provider": "openfoodfacts" if provider == "off" else "usda",
                "source_ref": source_ref,
                "action": f"Unset {setting} to allow {provider_name} source re-fetch",
            },
        )
    try:
        if provider == "off":
            food = off_client.product_by_barcode(source_id)
        else:
            credential = config.usda_credential()
            if credential is None:
                raise NomnomError(
                    "usda_not_configured",
                    "USDA is required to re-fetch this source reference",
                    details={"source_ref": source_ref},
                )
            food = usda_client.food_by_fdc_id(int(source_id), credential.value)
    except NomnomError as exc:
        if exc.code in {
            "barcode_not_found",
            "barcode_product_mismatch",
            "usda_food_not_found",
            "usda_food_mismatch",
        }:
            raise NomnomError(
                "agent_source_ref_mismatch",
                "The selected source reference no longer identifies the discovered record",
                details={"source_ref": source_ref, "provider_error": exc.as_dict()["error"]},
            ) from exc
        raise
    returned_id = food.source_id or (str(food.fdc_id) if food.fdc_id is not None else None)
    if returned_id != source_id:
        raise NomnomError(
            "agent_source_ref_mismatch",
            "Provider result identity does not match source_ref",
            details={"source_ref": source_ref, "returned_source_id": returned_id},
        )
    expected_source = "openfoodfacts" if provider == "off" else "usda"
    nutrients = (food.kcal, food.protein, food.fat, food.carbs)
    if food.source != expected_source or any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
        for value in nutrients
    ):
        raise NomnomError(
            "agent_source_integrity_rejected",
            "The selected source returned inconsistent identity or incomplete nutrition",
            details={
                "source_ref": source_ref,
                "expected_provider": expected_source,
                "returned_provider": food.source,
            },
        )
    query = _identity_query(item.input)
    status = (
        _candidate_status(query, food)
        if item.selection is not None
        else _direct_source_ref_status(query, food)
    )
    required_status = (
        "agent_selection_eligible" if item.selection is not None else "generic_proxy_eligible"
    )
    if status != required_status:
        raise NomnomError(
            "agent_source_identity_rejected",
            "The selected source changes food type or lacks exact identity evidence",
            details={
                "source_ref": source_ref,
                "candidate_status": status,
                "raw_input": item.input,
                "returned_name": food.name,
                "action": "photo_or_barcode"
                if status == "pending_capture_required"
                else "select_safe_candidate_or_pending",
            },
        )
    _apply_generic_policy(food, config)
    return _generic_proxy(food, item.selection)


def resolve_agent_plan(
    plan: AgentPlan,
    *,
    provider_config: ProviderConfig | None = None,
    off_client: OpenFoodFactsClient | None = None,
    usda_client: USDAClient | None = None,
) -> dict:
    config = provider_config or ProviderConfig()
    off = off_client or OpenFoodFactsClient()
    usda = usda_client or USDAClient()
    items = []
    for index, planned in enumerate(plan.items):
        if planned.pending_capture:
            pending_item = {
                "item_index": index,
                "input": planned.input,
                "status": "pending_capture",
                "capture": dict(PENDING_CAPTURE),
            }
            if planned.grams is not None:
                pending_item["grams"] = planned.grams
            if planned.portion_estimate is not None:
                pending_item.update(
                    {
                        "grams": planned.portion_estimate.grams,
                        "approximate": True,
                        "portion_provenance": planned.portion_estimate.method,
                        "portion_estimate": planned.portion_estimate.portion_dict(),
                    }
                )
            items.append(pending_item)
            continue

        food = _refetch_source(
            planned,
            config=config,
            off_client=off,
            usda_client=usda,
        )
        grams = planned.grams
        assert grams is not None or planned.portion_estimate is not None
        if planned.portion_estimate is not None:
            resolved = scale_food(
                food,
                planned.portion_estimate.grams,
                1.0,
                assumed=True,
                assumption=planned.portion_estimate.assumption,
                portion_estimate=planned.portion_estimate.portion_dict(),
            )
        else:
            resolved = scale_food(food, grams, 1.0)
        resolved_item = resolved.to_dict()
        resolved_item.update({"item_index": index, "input": planned.input, "status": "resolved"})
        if planned.selection is not None:
            resolved_item.update(
                {
                    "selection_mode": "agent_generic",
                    "selection_relation": planned.selection.relation,
                    "selection_assumption": planned.selection.assumption,
                    "selected_source_ref": planned.selection.source_ref,
                    "source_canonical_name": food.name,
                }
            )
        items.append(resolved_item)

    resolved_items = [item for item in items if item["status"] == "resolved"]
    pending_count = len(items) - len(resolved_items)
    totals = total_items(resolved_items)
    if pending_count:
        totals["complete"] = False
    return {
        "items": items,
        "totals": totals,
        "complete": pending_count == 0,
        "nutrition_status": "incomplete" if pending_count else "complete",
        "pending_count": pending_count,
        "approximate": any(item.get("approximate") is True for item in items),
    }
