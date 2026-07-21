from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from nomnomcli.errors import NomnomError
from nomnomcli.models import Food
from nomnomcli.usda import USDA_CONFIDENCE_FLOOR

SEMANTIC_VERSION = 1
SEMANTIC_RELATIONS = (
    "lexical_equivalent",
    "same_form",
    "generic_fallback",
)
_INTENT_FIELDS = frozenset({"version", "original", "brand_intent", "candidates"})
_CANDIDATE_FIELDS = frozenset({"query", "relation", "assumption"})
_RELATION_PRIORITY = {relation: index for index, relation in enumerate(SEMANTIC_RELATIONS)}
_SPECIES_MARKERS = frozenset(
    {"beef", "chicken", "duck", "goat", "lamb", "mutton", "pork", "turkey"}
)


@dataclass(frozen=True, slots=True)
class SemanticCandidate:
    index: int
    query: str
    relation: str
    assumption: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticIntent:
    version: int
    original: str
    brand_intent: bool
    candidates: tuple[SemanticCandidate, ...]


@dataclass(frozen=True, slots=True)
class PlannedCandidate:
    semantic: SemanticCandidate
    food: Food
    confidence: float


def _details(original: str, *, version: object = None, **extra: Any) -> dict[str, Any]:
    details: dict[str, Any] = {"would_write": False, "original": original}
    if isinstance(version, int) and not isinstance(version, bool):
        details["intent_version"] = version
    details.update(extra)
    return details


def _malformed(
    code: str,
    message: str,
    original: str,
    *,
    version: object = None,
    **extra: Any,
) -> NomnomError:
    return NomnomError(code, message, details=_details(original, version=version, **extra))


def normalize_semantic_query(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").strip().split())


def parse_semantic_intent(
    payload: str | dict[str, Any] | SemanticIntent,
    *,
    original: str,
) -> SemanticIntent:
    if isinstance(payload, SemanticIntent):
        payload = {
            "version": payload.version,
            "original": payload.original,
            "brand_intent": payload.brand_intent,
            "candidates": [
                {
                    "query": candidate.query,
                    "relation": candidate.relation,
                    **(
                        {"assumption": candidate.assumption}
                        if candidate.assumption is not None
                        else {}
                    ),
                }
                for candidate in payload.candidates
            ],
        }
    if isinstance(payload, str):
        try:
            value = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise _malformed(
                "semantic_intent_malformed",
                "Semantic intent must be valid inline JSON",
                original,
                reason="invalid_json",
            ) from exc
    else:
        value = payload
    if not isinstance(value, dict):
        raise _malformed(
            "semantic_intent_malformed",
            "Semantic intent must be a JSON object",
            original,
        )

    version = value.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version != SEMANTIC_VERSION:
        raise _malformed(
            "unsupported_semantic_version",
            "Semantic intent version must be 1",
            original,
            version=version,
            supported_versions=[SEMANTIC_VERSION],
        )
    unknown_fields = sorted(set(value) - _INTENT_FIELDS)
    missing_fields = sorted(_INTENT_FIELDS - set(value))
    if unknown_fields or missing_fields:
        raise _malformed(
            "semantic_intent_malformed",
            "Semantic intent fields must exactly match contract v1",
            original,
            version=version,
            missing_fields=missing_fields,
            unknown_fields=unknown_fields,
        )
    supplied_original = value["original"]
    if not isinstance(supplied_original, str) or supplied_original != original:
        raise _malformed(
            "semantic_original_mismatch",
            "Semantic intent original must exactly match --food",
            original,
            version=version,
            supplied_original=supplied_original,
        )
    if not original.strip():
        raise _malformed(
            "semantic_intent_malformed",
            "Semantic original must not be empty",
            original,
            version=version,
        )
    if not isinstance(value["brand_intent"], bool):
        raise _malformed(
            "semantic_intent_malformed",
            "brand_intent must be a boolean",
            original,
            version=version,
            field="brand_intent",
        )
    raw_candidates = value["candidates"]
    if not isinstance(raw_candidates, list) or len(raw_candidates) > 3:
        raise _malformed(
            "semantic_candidates_invalid",
            "candidates must be a list containing at most 3 entries",
            original,
            version=version,
            maximum=3,
        )

    candidates: list[SemanticCandidate] = []
    normalized_queries: set[str] = set()
    for index, candidate in enumerate(raw_candidates):
        if not isinstance(candidate, dict):
            raise _candidate_error(original, version, index, "candidate must be an object")
        unknown = sorted(set(candidate) - _CANDIDATE_FIELDS)
        missing = sorted({"query", "relation"} - set(candidate))
        if unknown or missing:
            raise _candidate_error(
                original,
                version,
                index,
                "candidate fields do not match contract v1",
                missing_fields=missing,
                unknown_fields=unknown,
            )
        query = candidate["query"]
        if not isinstance(query, str) or not (normalized_query := normalize_semantic_query(query)):
            raise _candidate_error(
                original, version, index, "candidate query must be a nonempty string"
            )
        if normalized_query in normalized_queries:
            raise _candidate_error(
                original,
                version,
                index,
                "candidate queries must be unique after normalization",
                normalized_query=normalized_query,
            )
        normalized_queries.add(normalized_query)
        relation = candidate["relation"]
        if relation not in SEMANTIC_RELATIONS:
            raise _candidate_error(
                original,
                version,
                index,
                "candidate relation is unsupported",
                allowed_relations=list(SEMANTIC_RELATIONS),
            )
        assumption = candidate.get("assumption")
        if assumption is not None and (
            not isinstance(assumption, str) or not assumption.strip()
        ):
            raise _candidate_error(
                original,
                version,
                index,
                "candidate assumption must be a nonempty string when supplied",
            )
        if relation == "generic_fallback" and assumption is None:
            raise _candidate_error(
                original,
                version,
                index,
                "generic_fallback requires a nonempty assumption",
            )
        candidates.append(
            SemanticCandidate(
                index=index,
                query=normalized_query,
                relation=relation,
                assumption=assumption.strip() if assumption is not None else None,
            )
        )
    return SemanticIntent(
        version=version,
        original=original,
        brand_intent=value["brand_intent"],
        candidates=tuple(candidates),
    )


def _candidate_error(
    original: str,
    version: int,
    index: int,
    message: str,
    **extra: Any,
) -> NomnomError:
    return _malformed(
        "semantic_candidate_invalid",
        message,
        original,
        version=version,
        candidate_index=index,
        **extra,
    )


def semantic_proxy_rejection(query: str, food: Food, confidence: float) -> str | None:
    if food.resolution_mode != "generic_proxy":
        return "semantic_exact_product_forbidden"
    if not math.isfinite(confidence):
        return "invalid_provider_confidence"
    if not (food.source_id or food.fdc_id or food.barcode):
        return "provider_source_identity_missing"
    if food.source == "usda":
        data_type = (food.provider_data_type or "").casefold()
        if (
            food.brand is not None
            or (data_type and data_type not in {"foundation", "sr legacy"})
            or confidence < USDA_CONFIDENCE_FLOOR
        ):
            return "unsafe_usda_generic_proxy"
    elif food.source == "openfoodfacts":
        if confidence < 0.5:
            return "unsafe_openfoodfacts_generic_proxy"
    else:
        return "unsupported_semantic_provider"
    query_species = _tokens(query) & _SPECIES_MARKERS
    candidate_species = _tokens(food.name) & _SPECIES_MARKERS
    if query_species and candidate_species - query_species:
        return "conflicting_species"
    return None


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"\w+", normalize_semantic_query(value)))


def candidate_sort_key(candidate: PlannedCandidate) -> tuple[int, int, float, str, int]:
    food = candidate.food
    provider_quality = (
        0
        if food.source == "usda"
        and food.brand is None
        and (food.provider_data_type or "").casefold() in {"", "foundation", "sr legacy"}
        else 1
    )
    return (
        _RELATION_PRIORITY[candidate.semantic.relation],
        provider_quality,
        -candidate.confidence,
        candidate.semantic.query,
        candidate.semantic.index,
    )


def resolution_plan(
    *,
    intent: SemanticIntent,
    retrieval_query: str,
    food: Food,
    confidence: float,
    semantic: SemanticCandidate | None,
) -> dict[str, Any]:
    source_id = food.source_id
    if source_id is None and food.fdc_id is not None:
        source_id = str(food.fdc_id)
    if source_id is None:
        source_id = food.barcode
    plan: dict[str, Any] = {
        "status": "resolution_plan",
        "would_write": False,
        "original": intent.original,
        "retrieval_query": retrieval_query,
        "intent_version": intent.version,
        "resolution_origin": "semantic_candidate" if semantic is not None else "raw",
        "requires_confirmation": semantic is not None,
        "name": food.name,
        "source": food.source,
        "source_id": source_id,
        "confidence": round(confidence, 2),
        "resolution_mode": food.resolution_mode,
    }
    if food.provider_data_type:
        plan["data_type"] = food.provider_data_type
    if food.alternatives:
        plan["provider_alternatives"] = list(food.alternatives)
    if food.assumption:
        plan["provider_assumption"] = food.assumption
    if semantic is not None:
        plan.update(
            {
                "candidate_index": semantic.index,
                "relation": semantic.relation,
            }
        )
        if semantic.assumption:
            plan["semantic_assumption"] = semantic.assumption
    return plan
