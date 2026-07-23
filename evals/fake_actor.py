from __future__ import annotations

import argparse
import json
import re

PROTOCOL_VERSION = 1


def tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if not token.isdigit()
    }


def explicit_grams(value: str) -> float | None:
    match = re.search(r"(?<![\w.])(\d+(?:\.\d+)?)\s*g(?:rams?)?\b", value.casefold())
    return float(match.group(1)) if match else None


def compatible(raw_identity: str, candidate: dict) -> bool:
    raw_tokens = tokens(raw_identity)
    brand_tokens = tokens(str(candidate.get("brand") or ""))
    candidate_tokens = tokens(str(candidate["semantic_identity"]))
    semantic_raw = raw_tokens - brand_tokens
    return bool(candidate_tokens) and candidate_tokens <= semantic_raw


def choose_candidate(raw_identity: str, discovery: dict) -> dict | None:
    eligible = [
        candidate
        for candidate in discovery["candidates"]
        if compatible(raw_identity, candidate)
        and candidate["candidate_status"]
        in {
            "agent_selection_eligible",
            "brand_candidate_requires_semantic_assessment",
        }
    ]
    eligible.sort(
        key=lambda candidate: (
            -int(candidate["direct_source_ref_eligible"]),
            -len(tokens(candidate["semantic_identity"])),
            candidate["source_ref"],
        )
    )
    return eligible[0] if eligible else None


def semantic_attestation(
    *,
    relation: str,
    raw_identity: str,
    selected_identity: str,
) -> dict:
    return {
        "version": 1,
        "relation": relation,
        "raw_identity": raw_identity,
        "selected_identity": selected_identity,
        "same_food_type": True,
        "rationale": (
            "Deterministic fake actor classified the supplied candidate identity as the "
            "same food type for harness self-testing."
        ),
        "confidence": 0.8,
    }


def pending_item(raw_item: str) -> dict:
    return {
        "input": raw_item,
        "pending_capture": {
            "status": "pending_capture",
            "action": "photo_or_barcode",
        },
    }


def build_plan(request: dict) -> dict:
    if not isinstance(request, dict) or request.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("unsupported sanitized actor request")
    profile = request["accuracy_profile"]
    plan_items = []
    estimates = []
    for index, requested_item in enumerate(request["items"]):
        raw_item = requested_item["input"]
        discovery = requested_item["discovery"]
        raw_identity = discovery["query"]
        candidate = choose_candidate(raw_identity, discovery)
        grams = explicit_grams(raw_item)
        fuzzy = grams is None
        if candidate is None or profile == "exact" and fuzzy:
            plan_items.append(pending_item(raw_item))
            continue

        status = candidate["candidate_status"]
        branded = bool(
            any(
                item["candidate_status"]
                == "brand_candidate_requires_semantic_assessment"
                for item in discovery["candidates"]
            )
        )
        if profile == "exact" and (branded or status != "agent_selection_eligible"):
            plan_items.append(pending_item(raw_item))
            continue

        item = {"input": raw_item}
        if status == "brand_candidate_requires_semantic_assessment":
            relation = "probable_brand_match"
            item["selection"] = {
                "source_ref": candidate["source_ref"],
                "relation": relation,
                "assumption": (
                    "Provider text candidate is probable only; no barcode or label "
                    "established exact product identity."
                ),
                "semantic_attestation": semantic_attestation(
                    relation=relation,
                    raw_identity=raw_identity,
                    selected_identity=candidate["semantic_identity"],
                ),
                "discovery_receipt": discovery["discovery_receipt"],
            }
        elif branded:
            relation = "branded_same_type_generic"
            dismissals = [
                {
                    "source_ref": other["source_ref"],
                    "reason": (
                        "incompatible_variant"
                        if compatible(raw_identity, other)
                        else "different_food_type"
                    ),
                }
                for other in discovery["candidates"]
                if other["candidate_status"]
                == "brand_candidate_requires_semantic_assessment"
            ]
            selection = {
                "source_ref": candidate["source_ref"],
                "relation": relation,
                "assumption": (
                    "Brand/SKU was not exact; used a source-backed same-type generic "
                    "proxy after provider text discovery."
                ),
                "semantic_attestation": semantic_attestation(
                    relation=relation,
                    raw_identity=raw_identity,
                    selected_identity=candidate["semantic_identity"],
                ),
                "discovery_receipt": discovery["discovery_receipt"],
                "dismissed_brand_candidates": dismissals,
            }
            if profile == "balanced":
                selection["risk_disposition"] = "material_risk_accepted"
            item["selection"] = selection
        elif candidate["direct_source_ref_eligible"]:
            item["source_ref"] = candidate["source_ref"]
        else:
            relation = "semantic_equivalent"
            item["selection"] = {
                "source_ref": candidate["source_ref"],
                "relation": relation,
                "assumption": (
                    "External actor selected this source-backed same-type semantic record."
                ),
                "semantic_attestation": semantic_attestation(
                    relation=relation,
                    raw_identity=raw_identity,
                    selected_identity=candidate["semantic_identity"],
                ),
            }

        if fuzzy:
            estimates.append(
                {
                    "item_index": index,
                    "input": raw_item,
                    "grams": 50,
                    "lower_grams": 40,
                    "upper_grams": 60,
                    "confidence": 0.7,
                    "method": "agent_estimate",
                    "assumption": "External actor estimated the fuzzy portion at 50 g.",
                }
            )
        else:
            item["grams"] = grams
        plan_items.append(item)
    plan = {
        "version": 2,
        "accuracy_profile": profile,
        "items": plan_items,
    }
    if estimates:
        plan["portion_estimates"] = {"items": estimates}
    return plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    args = parser.parse_args()
    request = json.loads(args.request)
    print(json.dumps(build_plan(request), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
