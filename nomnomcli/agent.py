from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, replace

from nomnomcli.accuracy import ACCURACY_PROFILES
from nomnomcli.config import ProviderConfig
from nomnomcli.errors import NomnomError
from nomnomcli.foods import _brand_matches_query, _comparison_token, _query_has_sku
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

AGENT_PLAN_VERSION = 2
LEGACY_AGENT_PLAN_VERSION = 1
PENDING_CAPTURE = {"status": "pending_capture", "action": "photo_or_barcode"}
AGENT_SELECTION_RELATION = "semantic_equivalent"
BRANDED_GENERIC_RELATION = "branded_same_type_generic"
PROBABLE_BRAND_RELATION = "probable_brand_match"
SELECTION_RELATIONS = (
    AGENT_SELECTION_RELATION,
    BRANDED_GENERIC_RELATION,
    PROBABLE_BRAND_RELATION,
)
MATERIAL_RISK_ACCEPTED = "material_risk_accepted"
GENERIC_USDA_TYPES = frozenset({"foundation", "sr legacy"})
STATUS_ORDER = {
    "agent_selection_eligible": 0,
    "brand_candidate_requires_semantic_assessment": 1,
    "pending_capture_required": 2,
    "identity_rejected": 3,
}
SEMANTIC_ATTESTATION_VERSION = 1
BRAND_DISMISSAL_REASONS = frozenset(
    {"different_food_type", "incompatible_variant", "incomplete_facts"}
)


@dataclass(frozen=True, slots=True)
class SemanticAttestation:
    version: int
    relation: str
    raw_identity: str
    selected_identity: str
    same_food_type: bool
    rationale: str
    confidence: float

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "relation": self.relation,
            "raw_identity": self.raw_identity,
            "selected_identity": self.selected_identity,
            "same_food_type": self.same_food_type,
            "rationale": self.rationale,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class BrandCandidateDismissal:
    source_ref: str
    reason: str

    def as_dict(self) -> dict:
        return {"source_ref": self.source_ref, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class AgentSelection:
    source_ref: str
    relation: str
    assumption: str
    semantic_attestation: SemanticAttestation
    discovery_receipt: str | None
    risk_disposition: str | None
    dismissed_brand_candidates: tuple[BrandCandidateDismissal, ...]


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
    version: int
    accuracy_profile: str | None


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
        "selection_fields": [
            "assumption",
            "dismissed_brand_candidates",
            "discovery_receipt",
            "relation",
            "risk_disposition",
            "semantic_attestation",
            "source_ref",
        ],
        "semantic_attestation_fields": [
            "confidence",
            "rationale",
            "raw_identity",
            "relation",
            "same_food_type",
            "selected_identity",
            "version",
        ],
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


def _parse_semantic_attestation(
    value,
    *,
    item_index: int,
    input_phrase: str,
    relation: str,
) -> SemanticAttestation:
    fields = {
        "version",
        "relation",
        "raw_identity",
        "selected_identity",
        "same_food_type",
        "rationale",
        "confidence",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise _invalid_plan(
            "semantic_attestation contains missing or unknown fields",
            item_index=item_index,
        )
    if (
        isinstance(value["version"], bool)
        or value["version"] != SEMANTIC_ATTESTATION_VERSION
    ):
        raise _invalid_plan(
            f"semantic_attestation version must be {SEMANTIC_ATTESTATION_VERSION}",
            item_index=item_index,
        )
    if value["relation"] != relation:
        raise _invalid_plan(
            "semantic_attestation relation must match selection relation",
            item_index=item_index,
        )
    raw_identity = value["raw_identity"]
    selected_identity = value["selected_identity"]
    for field_name, identity in (
        ("raw_identity", raw_identity),
        ("selected_identity", selected_identity),
    ):
        if (
            not isinstance(identity, str)
            or not identity.strip()
            or identity != identity.strip()
            or len(identity) > 500
        ):
            raise _invalid_plan(
                f"semantic_attestation {field_name} must be a nonempty trimmed string",
                item_index=item_index,
            )
    expected_raw_identity = _identity_query(input_phrase)
    if raw_identity != expected_raw_identity:
        raise _invalid_plan(
            "semantic_attestation raw_identity must match the parsed raw input identity",
            item_index=item_index,
        )
    if value["same_food_type"] is not True:
        raise _invalid_plan(
            "semantic_attestation must explicitly assert same_food_type true",
            item_index=item_index,
        )
    rationale = value["rationale"]
    if (
        not isinstance(rationale, str)
        or not rationale.strip()
        or rationale != rationale.strip()
        or len(rationale) > 500
    ):
        raise _invalid_plan(
            "semantic_attestation rationale must be a concise trimmed string",
            item_index=item_index,
        )
    confidence = value["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise _invalid_plan(
            "semantic_attestation confidence must be a finite number from 0 to 1",
            item_index=item_index,
        )
    confidence = float(confidence)
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise _invalid_plan(
            "semantic_attestation confidence must be a finite number from 0 to 1",
            item_index=item_index,
        )
    return SemanticAttestation(
        version=SEMANTIC_ATTESTATION_VERSION,
        relation=relation,
        raw_identity=raw_identity,
        selected_identity=selected_identity,
        same_food_type=True,
        rationale=rationale,
        confidence=confidence,
    )


def _parse_brand_dismissals(value, *, item_index: int) -> tuple[BrandCandidateDismissal, ...]:
    if not isinstance(value, list):
        raise _invalid_plan(
            "dismissed_brand_candidates must be an array",
            item_index=item_index,
        )
    if len(value) > 100:
        raise _invalid_plan(
            "dismissed_brand_candidates supports at most 100 entries",
            item_index=item_index,
        )
    parsed = []
    seen: set[str] = set()
    for dismissal in value:
        if not isinstance(dismissal, dict) or set(dismissal) != {"source_ref", "reason"}:
            raise _invalid_plan(
                "Each brand dismissal requires only source_ref and reason",
                item_index=item_index,
            )
        source_ref = _validate_source_ref(dismissal["source_ref"], item_index=item_index)
        reason = dismissal["reason"]
        if not isinstance(reason, str) or reason not in BRAND_DISMISSAL_REASONS:
            raise _invalid_plan(
                "Brand dismissal reason is not supported",
                item_index=item_index,
            )
        if source_ref in seen:
            raise _invalid_plan(
                "A brand candidate may be dismissed only once",
                item_index=item_index,
            )
        seen.add(source_ref)
        parsed.append(BrandCandidateDismissal(source_ref=source_ref, reason=reason))
    return tuple(parsed)


def _parse_selection(
    value,
    *,
    item_index: int,
    input_phrase: str,
    version: int,
    accuracy_profile: str | None,
) -> AgentSelection:
    base = {"source_ref", "relation", "assumption", "semantic_attestation"}
    if not isinstance(value, dict) or not base <= set(value):
        raise _invalid_plan(
            "selection is missing required source_ref, relation, or assumption",
            item_index=item_index,
        )
    source_ref = value["source_ref"]
    relation = value["relation"]
    assumption = value["assumption"]
    if not isinstance(source_ref, str) or not source_ref:
        raise _invalid_plan("selection source_ref must be a nonempty string", item_index=item_index)
    if not isinstance(relation, str) or relation not in SELECTION_RELATIONS:
        raise _invalid_plan(
            f"selection relation must be one of {', '.join(SELECTION_RELATIONS)}",
            item_index=item_index,
        )
    if version == LEGACY_AGENT_PLAN_VERSION and relation != AGENT_SELECTION_RELATION:
        raise _invalid_plan(
            "Version 1 selections support only the semantic_equivalent relation",
            item_index=item_index,
        )
    allowed = set(base)
    if relation in {BRANDED_GENERIC_RELATION, PROBABLE_BRAND_RELATION}:
        allowed.add("discovery_receipt")
        if relation == BRANDED_GENERIC_RELATION:
            allowed.add("dismissed_brand_candidates")
        if accuracy_profile == "balanced" and relation == BRANDED_GENERIC_RELATION:
            allowed.add("risk_disposition")
    if set(value) != allowed:
        raise _invalid_plan(
            "selection contains missing or unknown relation-specific fields",
            item_index=item_index,
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
    receipt = value.get("discovery_receipt")
    if receipt is not None and (
        not isinstance(receipt, str) or re.fullmatch(r"[0-9a-f]{64}", receipt) is None
    ):
        raise _invalid_plan(
            "discovery_receipt must be one lowercase SHA-256 digest",
            item_index=item_index,
        )
    risk_disposition = value.get("risk_disposition")
    if risk_disposition is not None and risk_disposition != MATERIAL_RISK_ACCEPTED:
        raise _invalid_plan(
            f"risk_disposition must be {MATERIAL_RISK_ACCEPTED}",
            item_index=item_index,
        )
    if relation == BRANDED_GENERIC_RELATION and "not exact" not in assumption.casefold():
        raise _invalid_plan(
            "branded generic fallback assumption must explicitly say the brand/SKU was not exact",
            item_index=item_index,
        )
    semantic_attestation = _parse_semantic_attestation(
        value["semantic_attestation"],
        item_index=item_index,
        input_phrase=input_phrase,
        relation=relation,
    )
    dismissals = (
        _parse_brand_dismissals(value["dismissed_brand_candidates"], item_index=item_index)
        if relation == BRANDED_GENERIC_RELATION
        else ()
    )
    if accuracy_profile == "exact" and relation in {
        BRANDED_GENERIC_RELATION,
        PROBABLE_BRAND_RELATION,
    }:
        raise _invalid_plan(
            "Exact profile accepts only exact identity evidence for branded input",
            item_index=item_index,
        )
    return AgentSelection(
        source_ref=_validate_source_ref(source_ref, item_index=item_index),
        relation=relation,
        assumption=assumption,
        semantic_attestation=semantic_attestation,
        discovery_receipt=receipt,
        risk_disposition=risk_disposition,
        dismissed_brand_candidates=dismissals,
    )


def parse_agent_plan(value: str) -> AgentPlan:
    try:
        payload = json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise _invalid_plan("--plan must be valid inline JSON") from exc
    if not isinstance(payload, dict):
        raise _invalid_plan("Agent plan must be one JSON object")
    allowed_top = {"version", "items", "portion_estimates", "accuracy_profile"}
    if set(payload) - allowed_top or not {"version", "items"} <= set(payload):
        raise _invalid_plan("Agent plan contains missing or unknown top-level fields")
    version = payload["version"]
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version not in {LEGACY_AGENT_PLAN_VERSION, AGENT_PLAN_VERSION}
    ):
        raise _invalid_plan(
            f"Agent plan version must be {LEGACY_AGENT_PLAN_VERSION} or {AGENT_PLAN_VERSION}"
        )
    accuracy_profile = payload.get("accuracy_profile")
    if version == AGENT_PLAN_VERSION:
        if not isinstance(accuracy_profile, str) or accuracy_profile not in ACCURACY_PROFILES:
            raise _invalid_plan(
                "Version 2 requires accuracy_profile practical, balanced, or exact"
            )
    elif accuracy_profile is not None:
        raise _invalid_plan("Version 1 does not accept accuracy_profile")
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
            _parse_selection(
                entry["selection"],
                item_index=index,
                input_phrase=input_phrase,
                version=version,
                accuracy_profile=accuracy_profile,
            )
            if has_selection
            else None
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
        if accuracy_profile == "exact" and portion_estimate is not None:
            raise _invalid_plan(
                "Exact profile requires measured or explicit grams, not a fuzzy portion estimate",
                item_index=index,
            )
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
    return AgentPlan(tuple(parsed), version=version, accuracy_profile=accuracy_profile)


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
    tokens = []
    for token in re.findall(
        r"\w+(?:['’]\w+)*",
        value.casefold().replace("ё", "е"),
    ):
        normalized = (
            token[:-2]
            if re.fullmatch(r"[a-z]+", token) and len(token) > 4 and token.endswith("oes")
            else _comparison_token(token)
        )
        tokens.append(normalized)
    return tuple(tokens)


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
    if food.brand and _brand_matches_query(food, query):
        return "brand_candidate_requires_semantic_assessment"
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
        "semantic_identity": _source_name(food),
        "type": food.provider_data_type,
        "category": food.categories[0] if food.categories else None,
        "brand": food.brand,
        "candidate_status": candidate_status,
        "direct_source_ref_eligible": (
            candidate_status == "agent_selection_eligible"
            and _direct_source_ref_status(query, food) == "generic_proxy_eligible"
        ),
    }


def _semantic_compatibility_evidence(
    raw_identity: str,
    selected_candidate: dict,
    candidates: list[dict],
) -> dict | None:
    raw_tokens = _ordered_tokens(raw_identity)
    selected_tokens = _ordered_tokens(str(selected_candidate["semantic_identity"]))
    if not raw_tokens or not selected_tokens:
        return None
    raw_set = set(raw_tokens)
    selected_category = selected_candidate.get("category")
    for anchor in candidates:
        if anchor["candidate_status"] not in {
            "agent_selection_eligible",
            "brand_candidate_requires_semantic_assessment",
        }:
            continue
        anchor_tokens = _ordered_tokens(str(anchor["semantic_identity"]))
        if not anchor_tokens or not set(anchor_tokens) <= raw_set:
            continue
        anchor_category = anchor.get("category")
        anchor_type = anchor.get("type")
        metadata_matches = 0
        if anchor_category and selected_category:
            if _ordered_tokens(str(anchor_category)) != _ordered_tokens(
                str(selected_category)
            ):
                continue
            metadata_matches += 1
        if anchor_type and selected_candidate.get("type"):
            if str(anchor_type).casefold() != str(
                selected_candidate["type"]
            ).casefold():
                continue
            metadata_matches += 1
        selected_starts_with_anchor = (
            selected_tokens[: len(anchor_tokens)] == anchor_tokens
        )
        raw_contained_by_selected = (
            len(raw_tokens) > 1 and raw_set <= set(selected_tokens)
        )
        exact_anchor_identity = selected_tokens == anchor_tokens
        if exact_anchor_identity or (
            metadata_matches
            and (selected_starts_with_anchor or raw_contained_by_selected)
        ):
            return {
                "method": "revalidated_literal_candidate_anchor",
                "anchor_source_ref": anchor["source_ref"],
                "anchor_semantic_identity": anchor["semantic_identity"],
                "anchor_type": anchor_type,
                "anchor_category": anchor_category,
                "selected_type": selected_candidate.get("type"),
                "selected_category": selected_category,
            }
    return None


def _provider_error(error: NomnomError) -> dict:
    return {"code": error.code, "message": error.message, "details": error.details}


def _canonical_digest(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def discover_candidates(
    input_phrase: str,
    *,
    accuracy_profile: str | None = None,
    provider_config: ProviderConfig | None = None,
    off_client: OpenFoodFactsClient | None = None,
    usda_client: USDAClient | None = None,
) -> dict:
    if not isinstance(input_phrase, str) or not input_phrase.strip():
        raise NomnomError("agent_input_invalid", "Candidate input must not be empty")
    query = _identity_query(input_phrase)
    config = provider_config or ProviderConfig()
    profile = accuracy_profile or config.accuracy_profile()
    if profile not in ACCURACY_PROFILES:
        raise NomnomError(
            "accuracy_profile_invalid",
            f"Unsupported accuracy profile: {profile}",
            details={"allowed": list(ACCURACY_PROFILES)},
        )
    errors = {}
    foods: list[Food] = []
    provider_status = {}
    offline = os.getenv("NOMNOM_OFFLINE", "").strip() == "1"

    if offline or os.getenv("NOMNOM_DISABLE_OFF", "").strip() == "1":
        errors["openfoodfacts"] = {
            "code": "provider_disabled",
            "message": "Open Food Facts discovery is disabled",
            "details": {},
        }
        provider_status["openfoodfacts"] = {
            "status": "disabled",
            "candidate_count": 0,
        }
    else:
        try:
            found = (off_client or OpenFoodFactsClient()).search(query, page_size=10)
            foods.extend(found)
            provider_status["openfoodfacts"] = {
                "status": "ok",
                "candidate_count": len(found),
            }
        except NomnomError as exc:
            errors["openfoodfacts"] = _provider_error(exc)
            provider_status["openfoodfacts"] = {
                "status": "unavailable",
                "candidate_count": 0,
                "error_code": exc.code,
            }

    credential = None if offline else config.usda_credential()
    if credential is None:
        errors["usda"] = {
            "code": "usda_not_configured",
            "message": "USDA discovery is not configured",
            "details": {"optional": True},
        }
        provider_status["usda"] = {
            "status": "not_configured" if not offline else "disabled",
            "candidate_count": 0,
        }
    else:
        try:
            found = [
                food
                for food, _ in (usda_client or USDAClient()).candidates(
                    query, credential.value
                )
            ]
            foods.extend(found)
            provider_status["usda"] = {"status": "ok", "candidate_count": len(found)}
        except NomnomError as exc:
            errors["usda"] = _provider_error(exc)
            provider_status["usda"] = {
                "status": "unavailable",
                "candidate_count": 0,
                "error_code": exc.code,
            }

    candidates = [_candidate_dict(query, food) for food in foods if food.source_id]
    candidates.sort(
        key=lambda item: (
            STATUS_ORDER[item["candidate_status"]],
            0 if item["provider"] == "usda" else 1,
            item["canonical_name"].casefold(),
            item["source_ref"],
        )
    )
    ok_count = sum(status["status"] == "ok" for status in provider_status.values())
    search_status = (
        "complete"
        if ok_count == len(provider_status)
        else "partial"
        if ok_count
        else "unavailable"
    )
    brand_candidates = [
        candidate
        for candidate in candidates
        if candidate["candidate_status"] == "brand_candidate_requires_semantic_assessment"
    ]
    evidence = {
        "version": AGENT_PLAN_VERSION,
        "accuracy_profile": profile,
        "input": input_phrase,
        "query": query,
        "candidates": candidates,
        "text_search": {
            "status": search_status,
            "brand_match_status": (
                "brand_candidates_require_semantic_assessment"
                if brand_candidates
                else "search_unavailable"
                if search_status == "unavailable"
                else "no_brand_candidates"
            ),
            "providers": provider_status,
        },
    }
    result = {**evidence, "discovery_receipt": _canonical_digest(evidence)}
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
        resolution_mode=(
            "probable_product"
            if selection is not None and selection.relation == PROBABLE_BRAND_RELATION
            else "generic_proxy"
        ),
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
    accuracy_profile: str,
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
    status = _direct_source_ref_status(query, food)
    required_status = "generic_proxy_eligible"
    if item.selection is not None:
        if item.selection.relation in {
            AGENT_SELECTION_RELATION,
            BRANDED_GENERIC_RELATION,
        }:
            status = _candidate_status(query, food)
            required_status = "agent_selection_eligible"
        else:
            status = _candidate_status(query, food)
            required_status = "brand_candidate_requires_semantic_assessment"
    if status != required_status:
        raise NomnomError(
            "agent_source_identity_rejected",
            "The selected source is not structurally eligible for this relation "
            "or lacks exact identity evidence",
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
    if (
        item.selection is not None
        and item.selection.semantic_attestation.selected_identity != _source_name(food)
    ):
        raise NomnomError(
            "agent_semantic_attestation_mismatch",
            "The selected source identity does not match the semantic attestation",
            details={
                "source_ref": source_ref,
                "raw_input": item.input,
                "attested_identity": item.selection.semantic_attestation.selected_identity,
                "returned_name": food.name,
            },
        )
    if item.selection is not None and item.selection.relation == BRANDED_GENERIC_RELATION:
        if accuracy_profile == "exact":
            raise NomnomError(
                "accuracy_profile_exact_required",
                "Exact profile requires barcode, label, pin, or other exact brand evidence",
                details={
                    "accuracy_profile": accuracy_profile,
                    "source_ref": source_ref,
                    "action": "photo_or_barcode",
                },
            )
        if accuracy_profile == "balanced" and (
            item.selection.risk_disposition != MATERIAL_RISK_ACCEPTED
        ):
            raise NomnomError(
                "balanced_material_risk_required",
                "Balanced branded fallback requires explicit material-risk acceptance or pending",
                details={
                    "accuracy_profile": accuracy_profile,
                    "source_ref": source_ref,
                    "allowed": [MATERIAL_RISK_ACCEPTED, "pending_capture"],
                },
            )
    if item.selection is None or item.selection.relation != PROBABLE_BRAND_RELATION:
        _apply_generic_policy(food, config)
    return _generic_proxy(food, item.selection)


def _revalidate_discovery(
    item: AgentPlanItem,
    *,
    accuracy_profile: str,
    config: ProviderConfig,
    off_client: OpenFoodFactsClient,
    usda_client: USDAClient,
) -> dict | None:
    selection = item.selection
    if selection is None:
        return None
    discovery = discover_candidates(
        item.input,
        accuracy_profile=accuracy_profile,
        provider_config=config,
        off_client=off_client,
        usda_client=usda_client,
    )
    if (
        selection.discovery_receipt is not None
        and discovery["discovery_receipt"] != selection.discovery_receipt
    ):
        raise NomnomError(
            "agent_discovery_evidence_mismatch",
            "Provider text discovery changed or the discovery receipt was not produced "
            "for this input",
            details={
                "source_ref": selection.source_ref,
                "provided_receipt": selection.discovery_receipt,
                "revalidated_receipt": discovery["discovery_receipt"],
                "text_search": discovery["text_search"],
            },
        )
    candidates = {
        candidate["source_ref"]: candidate for candidate in discovery["candidates"]
    }
    candidate = candidates.get(selection.source_ref)
    required_status = (
        "agent_selection_eligible"
        if selection.relation in {
            AGENT_SELECTION_RELATION,
            BRANDED_GENERIC_RELATION,
        }
        else "brand_candidate_requires_semantic_assessment"
    )
    provider = selection.source_ref.split(":", 1)[0]
    provider_status_key = "openfoodfacts" if provider == "off" else "usda"
    selected_provider_status = discovery["text_search"]["providers"][
        provider_status_key
    ]["status"]
    if candidate is None and selected_provider_status in {
        "disabled",
        "not_configured",
        "unavailable",
    }:
        return discovery
    if candidate is None or candidate["candidate_status"] != required_status:
        error_code = (
            "agent_semantic_compatibility_rejected"
            if selection.relation == AGENT_SELECTION_RELATION
            else "agent_discovery_candidate_mismatch"
        )
        raise NomnomError(
            error_code,
            "Selected source is not eligible under the revalidated text discovery",
            details={
                "source_ref": selection.source_ref,
                "required_status": required_status,
                "candidate_status": (
                    candidate["candidate_status"] if candidate is not None else "absent"
                ),
                "action": (
                    "photo_or_barcode"
                    if candidate is not None
                    and candidate["candidate_status"] == "pending_capture_required"
                    else "select_safe_candidate_or_pending"
                ),
            },
        )
    attested_identity = selection.semantic_attestation.selected_identity
    if candidate["semantic_identity"] != attested_identity:
        raise NomnomError(
            "agent_semantic_attestation_mismatch",
            "The revalidated candidate identity does not match the semantic attestation",
            details={
                "source_ref": selection.source_ref,
                "attested_identity": attested_identity,
                "candidate_identity": candidate["semantic_identity"],
            },
        )
    compatibility = _semantic_compatibility_evidence(
        discovery["query"],
        candidate,
        discovery["candidates"],
    )
    if compatibility is None:
        raise NomnomError(
            "agent_semantic_compatibility_rejected",
            "The raw and selected identities lack deterministic same-food-type evidence",
            details={
                "source_ref": selection.source_ref,
                "raw_identity": discovery["query"],
                "selected_identity": candidate["semantic_identity"],
                "action": "select_safe_candidate_or_pending",
            },
        )
    if selection.relation == BRANDED_GENERIC_RELATION:
        brand_candidates = {
            candidate["source_ref"]: candidate
            for candidate in discovery["candidates"]
            if candidate["candidate_status"]
            == "brand_candidate_requires_semantic_assessment"
        }
        dismissed = {
            dismissal.source_ref: dismissal.reason
            for dismissal in selection.dismissed_brand_candidates
        }
        if set(dismissed) != set(brand_candidates):
            raise NomnomError(
                "agent_brand_dismissal_evidence_invalid",
                "Branded generic fallback must dismiss every discovered brand candidate",
                details={
                    "source_ref": selection.source_ref,
                    "required_source_refs": sorted(brand_candidates),
                    "provided_source_refs": sorted(dismissed),
                },
            )
    return {**discovery, "semantic_compatibility": compatibility}


def _validate_refetched_discovery_evidence(
    item: AgentPlanItem,
    food: Food,
    discovery: dict | None,
) -> None:
    if item.selection is None or discovery is None:
        return
    candidate = next(
        (
            value
            for value in discovery["candidates"]
            if value["source_ref"] == item.selection.source_ref
        ),
        None,
    )
    if candidate is None:
        raise NomnomError(
            "agent_semantic_compatibility_rejected",
            "The selected source could not be tied to revalidated discovery evidence",
            details={
                "source_ref": item.selection.source_ref,
                "action": "retry_discovery_or_pending",
            },
        )
    returned_category = food.categories[0] if food.categories else None
    if (
        candidate.get("type") != food.provider_data_type
        or candidate.get("category") != returned_category
    ):
        raise NomnomError(
            "agent_discovery_candidate_mismatch",
            "The refetched source metadata no longer matches the revalidated candidate",
            details={
                "source_ref": item.selection.source_ref,
                "candidate_type": candidate.get("type"),
                "returned_type": food.provider_data_type,
                "candidate_category": candidate.get("category"),
                "returned_category": returned_category,
            },
        )


def resolve_agent_plan(
    plan: AgentPlan,
    *,
    provider_config: ProviderConfig | None = None,
    off_client: OpenFoodFactsClient | None = None,
    usda_client: USDAClient | None = None,
) -> dict:
    config = provider_config or ProviderConfig()
    configured_profile = config.accuracy_profile()
    accuracy_profile = plan.accuracy_profile or configured_profile
    if plan.accuracy_profile is not None and plan.accuracy_profile != configured_profile:
        raise NomnomError(
            "accuracy_profile_mismatch",
            "Agent plan accuracy profile does not match the active profile",
            details={
                "plan_profile": plan.accuracy_profile,
                "active_profile": configured_profile,
                "action": "Run discovery and intake with the active configured profile.",
            },
        )
    if accuracy_profile == "exact" and any(
        item.portion_estimate is not None for item in plan.items
    ):
        raise NomnomError(
            "accuracy_profile_exact_required",
            "Exact profile requires measured or explicit grams, not a fuzzy portion estimate",
            details={"accuracy_profile": accuracy_profile, "action": "provide_measured_grams"},
        )
    if accuracy_profile == "exact" and any(
        item.selection is not None
        and item.selection.relation
        in {BRANDED_GENERIC_RELATION, PROBABLE_BRAND_RELATION}
        for item in plan.items
    ):
        raise NomnomError(
            "accuracy_profile_exact_required",
            "Exact profile requires barcode, label, pin, or other exact brand evidence",
            details={"accuracy_profile": accuracy_profile, "action": "photo_or_barcode"},
        )
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
                "accuracy_profile": accuracy_profile,
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
        discovery = _revalidate_discovery(
            planned,
            accuracy_profile=accuracy_profile,
            config=config,
            off_client=off,
            usda_client=usda,
        )
        food = _refetch_source(
            planned,
            accuracy_profile=accuracy_profile,
            config=config,
            off_client=off,
            usda_client=usda,
        )
        _validate_refetched_discovery_evidence(planned, food, discovery)
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
        resolved_item.update(
            {
                "item_index": index,
                "input": planned.input,
                "status": "resolved",
                "accuracy_profile": accuracy_profile,
            }
        )
        if planned.selection is not None:
            selection_mode = {
                AGENT_SELECTION_RELATION: "agent_generic",
                BRANDED_GENERIC_RELATION: "agent_branded_generic_fallback",
                PROBABLE_BRAND_RELATION: "agent_probable_brand_match",
            }[planned.selection.relation]
            resolved_item.update(
                {
                    "selection_mode": selection_mode,
                    "selection_relation": planned.selection.relation,
                    "selection_assumption": planned.selection.assumption,
                    "semantic_attestation": (
                        planned.selection.semantic_attestation.as_dict()
                    ),
                    "selected_source_ref": planned.selection.source_ref,
                    "source_canonical_name": food.name,
                }
            )
            if discovery is not None:
                resolved_item.update(
                    {
                        "discovery_receipt": discovery["discovery_receipt"],
                        "text_search": discovery["text_search"],
                    }
                )
                if discovery.get("semantic_compatibility") is not None:
                    resolved_item["semantic_compatibility"] = discovery[
                        "semantic_compatibility"
                    ]
            if planned.selection.dismissed_brand_candidates:
                resolved_item["dismissed_brand_candidates"] = [
                    dismissal.as_dict()
                    for dismissal in planned.selection.dismissed_brand_candidates
                ]
        items.append(resolved_item)

    resolved_items = [item for item in items if item["status"] == "resolved"]
    pending_count = len(items) - len(resolved_items)
    totals = total_items(resolved_items)
    if pending_count:
        totals["complete"] = False
    return {
        "accuracy_profile": accuracy_profile,
        "items": items,
        "totals": totals,
        "complete": pending_count == 0,
        "nutrition_status": "incomplete" if pending_count else "complete",
        "pending_count": pending_count,
        "approximate": any(item.get("approximate") is True for item in items),
    }
