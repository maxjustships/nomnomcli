from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import NoReturn

from nomnomcli.errors import NomnomError


class SemanticRelation(StrEnum):
    LEXICAL_EQUIVALENT = "lexical_equivalent"
    SAME_FORM = "same_form"
    GENERIC_FALLBACK = "generic_fallback"


@dataclass(frozen=True, slots=True)
class ResolutionCandidate:
    query: str
    relation: SemanticRelation
    assumption: str | None = None


@dataclass(frozen=True, slots=True)
class ResolutionIntent:
    version: int
    original: str
    brand_intent: bool
    candidates: tuple[ResolutionCandidate, ...]


@dataclass(frozen=True, slots=True)
class ResolutionPlan:
    original: str
    retrieval_query: str
    intent_version: int
    provider: str
    source: str
    source_id: str | None
    provider_type: str
    confidence: float
    resolution_mode: str
    alternatives: tuple[dict, ...] = ()
    candidate_index: int | None = None
    relation: SemanticRelation | None = None
    assumption: str | None = None
    provider_assumption: str | None = None
    would_write: bool = False

    def to_dict(self) -> dict:
        result = asdict(self)
        result["alternatives"] = list(self.alternatives)
        for key in ("candidate_index", "relation", "assumption", "provider_assumption"):
            if result[key] is None:
                del result[key]
        return result


def _intent_error(
    message: str, *, expected_original: str, details: dict | None = None
) -> NoReturn:
    raise NomnomError(
        "invalid_resolution_intent",
        message,
        details={
            "would_write": False,
            "original": expected_original,
            **(details or {}),
        },
    )


def _candidate_key(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def parse_resolution_intent(raw_json: str, *, expected_original: str) -> ResolutionIntent:
    try:
        payload = json.loads(raw_json)
    except (TypeError, json.JSONDecodeError) as exc:
        _intent_error(
            "Resolution intent must be valid inline JSON",
            expected_original=expected_original,
            details={"reason": str(exc)},
        )
    if not isinstance(payload, dict):
        _intent_error(
            "Resolution intent must be a JSON object",
            expected_original=expected_original,
        )
    allowed_fields = {"version", "original", "brand_intent", "candidates"}
    missing = sorted(allowed_fields - payload.keys())
    unknown = sorted(payload.keys() - allowed_fields)
    if missing or unknown:
        _intent_error(
            "Resolution intent fields do not match version 1",
            expected_original=expected_original,
            details={"missing_fields": missing, "unknown_fields": unknown},
        )
    if isinstance(payload["version"], bool) or payload["version"] != 1:
        _intent_error(
            "Resolution intent version must be exactly 1",
            expected_original=expected_original,
            details={"version": payload["version"]},
        )
    if not isinstance(payload["original"], str) or not payload["original"]:
        _intent_error(
            "Resolution intent original must be a nonempty string",
            expected_original=expected_original,
        )
    if payload["original"] != expected_original:
        raise NomnomError(
            "resolution_intent_original_mismatch",
            "Resolution intent original must exactly match --food",
            details={
                "would_write": False,
                "original": expected_original,
                "intent_original": payload["original"],
            },
        )
    if not isinstance(payload["brand_intent"], bool):
        _intent_error(
            "Resolution intent brand_intent must be a boolean",
            expected_original=expected_original,
        )
    raw_candidates = payload["candidates"]
    if not isinstance(raw_candidates, list) or len(raw_candidates) > 3:
        _intent_error(
            "Resolution intent candidates must be an array with at most 3 entries",
            expected_original=expected_original,
        )

    candidates = []
    seen = set()
    for index, candidate in enumerate(raw_candidates):
        if not isinstance(candidate, dict):
            _intent_error(
                "Every resolution candidate must be an object",
                expected_original=expected_original,
                details={"candidate_index": index},
            )
        allowed_candidate_fields = {"query", "relation", "assumption"}
        unknown_candidate_fields = sorted(candidate.keys() - allowed_candidate_fields)
        missing_candidate_fields = sorted({"query", "relation"} - candidate.keys())
        if missing_candidate_fields or unknown_candidate_fields:
            _intent_error(
                "Resolution candidate fields do not match version 1",
                expected_original=expected_original,
                details={
                    "candidate_index": index,
                    "missing_fields": missing_candidate_fields,
                    "unknown_fields": unknown_candidate_fields,
                },
            )
        query = candidate["query"]
        if not isinstance(query, str) or not (normalized_query := " ".join(query.split())):
            _intent_error(
                "Resolution candidate query must be a nonempty string",
                expected_original=expected_original,
                details={"candidate_index": index},
            )
        key = _candidate_key(normalized_query)
        if key in seen:
            _intent_error(
                "Resolution candidate queries must be unique",
                expected_original=expected_original,
                details={"candidate_index": index, "query": normalized_query},
            )
        seen.add(key)
        try:
            relation = SemanticRelation(candidate["relation"])
        except (TypeError, ValueError):
            _intent_error(
                "Resolution candidate relation is invalid",
                expected_original=expected_original,
                details={"candidate_index": index, "relation": candidate["relation"]},
            )
        assumption = candidate.get("assumption")
        if assumption is not None and (
            not isinstance(assumption, str) or not (assumption := " ".join(assumption.split()))
        ):
            _intent_error(
                "Resolution candidate assumption must be a nonempty string when supplied",
                expected_original=expected_original,
                details={"candidate_index": index},
            )
        if relation is SemanticRelation.GENERIC_FALLBACK and assumption is None:
            _intent_error(
                "A generic_fallback candidate requires an explicit assumption",
                expected_original=expected_original,
                details={"candidate_index": index},
            )
        candidates.append(
            ResolutionCandidate(
                query=normalized_query,
                relation=relation,
                assumption=assumption,
            )
        )
    return ResolutionIntent(
        version=1,
        original=payload["original"],
        brand_intent=payload["brand_intent"],
        candidates=tuple(candidates),
    )
