from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass

from nomnomcli.errors import NomnomError

PORTION_POLICIES = ("strict", "ask", "estimate")
DEFAULT_PORTION_POLICY = "strict"
PORTION_METHOD = "agent_estimate"
PORTION_CORRECTION = "Correct approximate portions with scale grams, photo, or barcode."
ESTIMATE_FIELDS = frozenset(
    {
        "item_index",
        "input",
        "grams",
        "lower_grams",
        "upper_grams",
        "confidence",
        "method",
        "assumption",
    }
)


@dataclass(frozen=True, slots=True)
class PortionEstimate:
    item_index: int
    input: str
    grams: float
    lower_grams: float
    upper_grams: float
    confidence: float
    method: str
    assumption: str

    def portion_dict(self) -> dict:
        return asdict(self)


class PortionEstimateSet:
    def __init__(self, estimates: list[PortionEstimate]) -> None:
        self._by_index = {estimate.item_index: estimate for estimate in estimates}
        self._used: set[int] = set()

    def entry_for(self, item_index: int, input_phrase: str) -> PortionEstimate | None:
        estimate = self._by_index.get(item_index)
        if estimate is None:
            return None
        if estimate.input != input_phrase:
            raise NomnomError(
                "portion_estimate_mismatch",
                "Portion estimate input does not exactly match the parsed item",
                details={
                    "item_index": item_index,
                    "expected_input": input_phrase,
                    "estimate_input": estimate.input,
                    "action": "Use the exact item_index and input returned from the original text.",
                },
            )
        return estimate

    def mark_used(self, item_index: int) -> None:
        self._used.add(item_index)

    def ensure_all_used(self) -> None:
        unused = [
            {
                "item_index": estimate.item_index,
                "input": estimate.input,
            }
            for index, estimate in sorted(self._by_index.items())
            if index not in self._used
        ]
        if unused:
            raise NomnomError(
                "portion_estimate_mismatch",
                "Portion estimates were supplied for items that do not need an estimate",
                details={
                    "unused_estimates": unused,
                    "action": "Supply estimates only for fuzzy portions without explicit grams.",
                },
            )


def validate_portion_policy(value: str, *, source: str) -> str:
    policy = value.strip()
    if policy not in PORTION_POLICIES:
        raise NomnomError(
            "portion_policy_invalid",
            f"Unsupported portion policy: {policy or '(empty)'}",
            details={"source": source, "allowed": list(PORTION_POLICIES)},
        )
    return policy


def _invalid_estimate(message: str, *, item_index=None, field=None) -> NomnomError:
    details = {"required_fields": sorted(ESTIMATE_FIELDS)}
    if item_index is not None:
        details["item_index"] = item_index
    if field is not None:
        details["field"] = field
    return NomnomError("portion_estimate_invalid", message, details=details)


def _number(entry: dict, field: str, item_index: int) -> float:
    value = entry.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid_estimate(
            f"{field} must be a finite nonnegative number",
            item_index=item_index,
            field=field,
        )
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise _invalid_estimate(
            f"{field} must be a finite nonnegative number",
            item_index=item_index,
            field=field,
        )
    return result


def parse_portion_estimates(value: str) -> PortionEstimateSet:
    try:
        payload = json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise NomnomError(
            "portion_estimates_malformed",
            "--portion-estimates must be valid inline JSON",
            details={"action": "Pass one JSON object with an items array."},
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {"items"}:
        raise NomnomError(
            "portion_estimates_malformed",
            "Portion estimate JSON must contain exactly one items array",
            details={"schema": {"items": [sorted(ESTIMATE_FIELDS)]}},
        )
    entries = payload["items"]
    if not isinstance(entries, list):
        raise NomnomError(
            "portion_estimates_malformed",
            "Portion estimate items must be an array",
        )

    estimates = []
    indexes: set[int] = set()
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != ESTIMATE_FIELDS:
            raise _invalid_estimate(
                "Each portion estimate must contain exactly the documented fields",
                item_index=position,
            )
        item_index = entry["item_index"]
        if isinstance(item_index, bool) or not isinstance(item_index, int) or item_index < 0:
            raise _invalid_estimate(
                "item_index must be a nonnegative integer",
                item_index=position,
                field="item_index",
            )
        if item_index in indexes:
            raise NomnomError(
                "portion_estimate_duplicate",
                f"Duplicate portion estimate for item_index {item_index}",
                details={"item_index": item_index},
            )
        indexes.add(item_index)

        input_phrase = entry["input"]
        if not isinstance(input_phrase, str) or not input_phrase.strip():
            raise _invalid_estimate(
                "input must be a nonempty exact item phrase",
                item_index=item_index,
                field="input",
            )
        method = entry["method"]
        if method != PORTION_METHOD:
            raise _invalid_estimate(
                "method must be agent_estimate",
                item_index=item_index,
                field="method",
            )
        assumption = entry["assumption"]
        if not isinstance(assumption, str) or not assumption.strip():
            raise _invalid_estimate(
                "assumption must be a nonempty human-readable string",
                item_index=item_index,
                field="assumption",
            )
        grams = _number(entry, "grams", item_index)
        lower = _number(entry, "lower_grams", item_index)
        upper = _number(entry, "upper_grams", item_index)
        confidence = _number(entry, "confidence", item_index)
        if not lower <= grams <= upper:
            raise _invalid_estimate(
                "Portion range must satisfy lower_grams <= grams <= upper_grams",
                item_index=item_index,
            )
        if confidence > 1:
            raise _invalid_estimate(
                "confidence must be between 0 and 1",
                item_index=item_index,
                field="confidence",
            )
        estimates.append(
            PortionEstimate(
                item_index=item_index,
                input=input_phrase,
                grams=grams,
                lower_grams=lower,
                upper_grams=upper,
                confidence=confidence,
                method=method,
                assumption=assumption.strip(),
            )
        )
    return PortionEstimateSet(estimates)


def estimate_required_error(policy: str, item_index: int, input_phrase: str) -> NomnomError:
    code = "portion_estimate_missing" if policy == "estimate" else "portion_estimate_required"
    return NomnomError(
        code,
        "This fuzzy portion needs one explicit external agent estimate",
        details={
            "policy": policy,
            "item_index": item_index,
            "input": input_phrase,
            "required_method": PORTION_METHOD,
            "action": (
                "Supply exact grams or use --portion-policy estimate with one exactly matched "
                "--portion-estimates entry."
            ),
            "correction": PORTION_CORRECTION,
        },
    )
