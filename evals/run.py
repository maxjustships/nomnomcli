from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import threading
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = Path(__file__).with_name("corpus.json")
PROHIBITED_PLAN_KEYS = {"calories", "carbs", "fat", "kcal", "macros", "nutrition", "protein"}
STDOUT_EXCERPT_LIMIT = 2000
REPAIR_CONTEXT_FORBIDDEN_KEYS = {
    "allowed_resolution_modes",
    "allowed_semantic_identities",
    "allowed_source_refs",
    "expected",
    "forbidden_identities",
    "forbidden_tokens",
    "gram_envelopes",
    "synthetic_providers",
}


REPAIRABLE_CLI_ERROR_CODES = {"agent_plan_invalid", "portion_estimates_malformed"}
PLAN_TOP_LEVEL_FIELDS = {"version", "accuracy_profile", "items", "portion_estimates"}
PLAN_ITEM_FIELDS = {"input", "grams", "source_ref", "selection", "pending_capture"}
SELECTION_BASE_FIELDS = {"source_ref", "relation", "assumption", "semantic_attestation"}
SELECTION_FIELDS_BY_RELATION = {
    "semantic_equivalent": SELECTION_BASE_FIELDS,
    "probable_brand_match": SELECTION_BASE_FIELDS | {"discovery_receipt"},
    "branded_same_type_generic": SELECTION_BASE_FIELDS
    | {"discovery_receipt", "dismissed_brand_candidates", "risk_disposition"},
}


def load_corpus() -> dict:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


class ReplayState:
    def __init__(self, case: dict) -> None:
        self.case = case
        self.requests: list[dict] = []
        self.lock = threading.Lock()

    def record(self, path: str, query: str) -> None:
        parameters = {
            key: values
            for key, values in parse_qs(query).items()
            if key.casefold() not in {"api_key", "token", "authorization"}
        }
        with self.lock:
            self.requests.append({"path": path, "parameters": parameters})


class ReplayServer:
    def __init__(self, case: dict) -> None:
        self.state = ReplayState(case)
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                state.record(parsed.path, parsed.query)
                providers = state.case["synthetic_providers"]
                candidates = providers["candidates"]
                responses = providers["responses"]
                if parsed.path == "/off/search":
                    self._json(
                        responses["openfoodfacts_search_status"],
                        {"products": candidates["openfoodfacts"]},
                    )
                    return
                if parsed.path == "/off/product-probe":
                    self._json(200, {"status": 1})
                    return
                if parsed.path.startswith("/off/product/"):
                    barcode = parsed.path.rsplit("/", 1)[-1]
                    record = next(
                        (
                            item
                            for item in candidates["openfoodfacts"]
                            if str(item.get("code")) == barcode
                        ),
                        None,
                    )
                    self._json(
                        200,
                        {"status": 1, "product": record}
                        if record is not None
                        else {"status": 0},
                    )
                    return
                if parsed.path == "/usda/search":
                    query = parse_qs(parsed.query).get("query", [""])[0]
                    status = responses.get("usda_search_status_by_term", {})
                    matched_status = next(
                        (
                            value
                            for term, value in status.items()
                            if term.casefold() in query.casefold()
                        ),
                        responses["usda_search_status"],
                    )
                    self._json(
                        matched_status,
                        {"foods": candidates["usda"]},
                    )
                    return
                if parsed.path.startswith("/usda/food/"):
                    source_id = parsed.path.rsplit("/", 1)[-1]
                    override = responses["refetch_overrides"].get(source_id)
                    record = override or next(
                        (
                            item
                            for item in candidates["usda"]
                            if str(item.get("fdcId")) == source_id
                        ),
                        None,
                    )
                    self._json(200 if record is not None else 404, record or {})
                    return
                self._json(404, {"error": "unknown replay path"})

            def _json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> ReplayServer:
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def render_command(template: str, values: dict[str, str]) -> list[str]:
    return [part.format(**values) for part in shlex.split(template)]


def default_actor_command() -> str:
    return f"{shlex.quote(sys.executable)} -m evals.fake_actor --request {{request}}"


def split_items(raw_input: str) -> list[str]:
    return [part.strip() for part in raw_input.split(";") if part.strip()]


def invoke_cli(
    arguments: list[str],
    *,
    env: dict[str, str],
    cwd: Path,
    timeout: int = 30,
) -> tuple[int, dict]:
    completed = subprocess.run(
        [sys.executable, "-m", "nomnomcli", *arguments, "--json"],
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    stream = completed.stdout if completed.returncode == 0 else completed.stderr
    try:
        payload = json.loads(stream)
    except json.JSONDecodeError:
        payload = {
            "error": {
                "code": "eval_cli_output_invalid",
                "message": "CLI subprocess did not return JSON",
            }
        }
    return completed.returncode, payload


def sanitize_discovery(payload: dict) -> dict:
    candidate_fields = {
        "brand",
        "candidate_status",
        "canonical_name",
        "category",
        "direct_source_ref_eligible",
        "provider",
        "semantic_identity",
        "source_id",
        "source_ref",
        "type",
    }
    return {
        "version": payload["version"],
        "accuracy_profile": payload["accuracy_profile"],
        "input": payload["input"],
        "query": payload["query"],
        "candidates": [
            {key: candidate.get(key) for key in sorted(candidate_fields)}
            for candidate in payload["candidates"]
        ],
        "text_search": payload["text_search"],
        "discovery_receipt": payload["discovery_receipt"],
    }


def actor_prompt(request: dict) -> str:
    contract = {
        "top_level": {
            "required": ["version", "accuracy_profile", "items"],
            "optional": ["portion_estimates"],
            "forbidden_extra_fields": True,
            "version": 2,
        },
        "item": {
            "required": ["input"],
            "optional": ["grams"],
            "exactly_one_identity_state": ["source_ref", "selection", "pending_capture"],
            "forbidden_extra_fields": True,
        },
        "direct_measured_template": {
            "input": "COPY_ITEM_INPUT_EXACTLY",
            "grams": "NUMBER_PARSED_FROM_INPUT",
            "source_ref": "COPY_ELIGIBLE_SOURCE_REF",
        },
        "selection_template": {
            "input": "COPY_ITEM_INPUT_EXACTLY",
            "grams": "NUMBER_OR_OMIT_WHEN_USING_PORTION_ESTIMATE",
            "selection": {
                "source_ref": "COPY_CANDIDATE_SOURCE_REF",
                "relation": (
                    "semantic_equivalent | branded_same_type_generic | probable_brand_match"
                ),
                "assumption": "NONEMPTY_HUMAN_READABLE_ASSUMPTION",
                "semantic_attestation": {
                    "version": 1,
                    "relation": "EXACTLY_MATCH_SELECTION_RELATION",
                    "raw_identity": "COPY_DISCOVERY_QUERY_EXACTLY",
                    "selected_identity": "COPY_CANDIDATE_SEMANTIC_IDENTITY_EXACTLY",
                    "same_food_type": True,
                    "rationale": "CONCISE_SEMANTIC_REASON",
                    "confidence": "NUMBER_FROM_0_TO_1",
                },
            },
        },
        "selection_fields_by_relation": {
            relation: sorted(fields)
            for relation, fields in SELECTION_FIELDS_BY_RELATION.items()
        },
        "branded_same_type_generic_flat_example": {
            "input": "Example Brand sandwich bread 80 g",
            "grams": 80,
            "selection": {
                "source_ref": "usda:12345",
                "relation": "branded_same_type_generic",
                "assumption": (
                    "Example Brand/SKU was not exact; used source-backed generic "
                    "sandwich bread after provider text discovery."
                ),
                "semantic_attestation": {
                    "version": 1,
                    "relation": "branded_same_type_generic",
                    "raw_identity": "Example Brand sandwich bread",
                    "selected_identity": "sandwich bread",
                    "same_food_type": True,
                    "rationale": "Both identities denote sandwich bread.",
                    "confidence": 0.9,
                },
                "discovery_receipt": "0" * 64,
                "dismissed_brand_candidates": [
                    {
                        "source_ref": "off:0000000000000",
                        "reason": "different_food_type",
                    }
                ],
                "risk_disposition": "material_risk_accepted",
            },
        },
        "branded_selection_rules": {
            "probable_brand_match": (
                "discovery_receipt is required directly in selection"
            ),
            "branded_same_type_generic": (
                "discovery_receipt and dismissed_brand_candidates are required directly "
                "in selection; assumption must contain the literal words 'not exact'"
            ),
            "balanced_branded_same_type_generic": (
                "risk_disposition=material_risk_accepted is required directly in selection"
            ),
            "practical_branded_same_type_generic": (
                "risk_disposition must be omitted"
            ),
            "dismissal": {
                "source_ref": "COPY_EACH_BRAND_CANDIDATE_SOURCE_REF",
                "reason": "different_food_type | incompatible_variant | incomplete_facts",
            },
        },
        "pending_template": {
            "input": "COPY_ITEM_INPUT_EXACTLY",
            "pending_capture": {"status": "pending_capture", "action": "photo_or_barcode"},
        },
        "portion_estimates": {
            "shape": {"items": ["ONE_ESTIMATE_PER_FUZZY_RESOLVED_ITEM"]},
            "estimate_fields_exactly": [
                "item_index",
                "input",
                "grams",
                "lower_grams",
                "upper_grams",
                "confidence",
                "method",
                "assumption",
            ],
            "method": "agent_estimate",
        },
        "accuracy_profile_policy": {
            "practical": (
                "MUST estimate every fuzzy portion automatically when a semantically "
                "compatible source exists; fuzzy grams alone never justify pending_capture"
            ),
            "balanced": (
                "MUST estimate every fuzzy portion automatically when a semantically "
                "compatible source exists; fuzzy grams alone never justify pending_capture"
            ),
            "exact": "MUST use pending_capture for every fuzzy portion",
            "measured": "Copy explicitly measured grams exactly in every profile",
            "estimate_bounds": (
                "grams MUST be inside lower_grams and upper_grams inclusive, and MUST be "
                "a realistic edible-portion estimate for the phrase"
            ),
        },
    }
    return (
        "Return exactly one strict nomnom agent plan JSON object and no prose or markdown. "
        "You have no tools and must use only the sanitized request below. Never return nutrition "
        "facts. The JSON root MUST be the complete plan object, never a single item or selection. "
        "The items array MUST contain exactly one item for every SANITIZED REQUEST item, in the "
        "same order; never omit later items. "
        "Do not invent protocol_version, plan_version, raw_input, selections, candidate, "
        "canonical_name, provider, source_id, portion, unit, amount, value, or any field not "
        "explicitly allowed by the contract. Copy each item input exactly. For a measured "
        "unbranded candidate with direct_source_ref_eligible=true, prefer the direct measured "
        "template: source_ref is an ITEM field, relation is omitted, and grams is an ITEM field. "
        "There is no relation named exact or exact_same_type. For every selection, include the "
        "strict semantic_attestation. selection must never contain input. discovery_receipt is "
        "forbidden for semantic_equivalent and is allowed only for the branded relations listed. "
        "Only assert same_food_type when the raw and selected "
        "identities truly denote the same food type; otherwise use pending_capture. A "
        "brand_candidate_requires_semantic_assessment is not exact. A branded generic fallback "
        "must dismiss every discovered brand candidate. Never create a "
        "branded_selection_additions object: discovery_receipt, dismissed_brand_candidates, and "
        "risk_disposition belong directly inside selection. For branded_same_type_generic, the "
        "assumption MUST contain the literal words 'not exact'. probable_brand_match MUST include "
        "discovery_receipt. Balanced may complete a same-type branded generic fallback only with "
        "risk_disposition='material_risk_accepted'; Practical does not need it and must omit it. "
        "In Practical, when a discovered brand candidate's brand and semantic food identity match "
        "the branded input, use probable_brand_match rather than pending_capture merely because "
        "there is no barcode; use pending only when same-food-type compatibility is uncertain. "
        "Practical and Balanced MUST automatically estimate fuzzy portions when a semantically "
        "compatible source exists and must not use pending_capture merely because grams are "
        "fuzzy. Exact MUST use pending_capture for fuzzy portions or text-only branded identity. "
        "Every estimate must put grams inside its inclusive lower_grams/upper_grams range and use "
        "a realistic edible-portion amount. Copy measured grams exactly.\nSTRICT CONTRACT:\n"
        + json.dumps(contract, ensure_ascii=False, sort_keys=True)
        + "\nSANITIZED REQUEST:\n"
        + json.dumps(request, ensure_ascii=False, sort_keys=True)
    )


def _sanitize_previous_invalid(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_previous_invalid(child)
            for key, child in value.items()
            if str(key).casefold()
            not in PROHIBITED_PLAN_KEYS | REPAIR_CONTEXT_FORBIDDEN_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_previous_invalid(child) for child in value]
    return value


def repair_prompt(
    *,
    request: dict,
    previous_invalid_plan_or_stdout,
    exact_error: dict,
) -> str:
    sanitized_request = _sanitize_previous_invalid(request)
    repair_input = {
        "sanitized_original_request": sanitized_request,
        "previous_invalid_plan_or_stdout_excerpt": _sanitize_previous_invalid(
            previous_invalid_plan_or_stdout
        ),
        "exact_cli_or_parser_error": exact_error,
    }
    return (
        actor_prompt(sanitized_request)
        + "\nREPAIR CONTEXT:\n"
        + "This is the single bounded internal repair turn. Correct only the reported parser or "
        "CLI intake validation error. Reconstruct the COMPLETE plan from scratch, including every "
        "sanitized request item; never return only the invalid item or selection. Preserve the "
        "original food semantics and measured values. The only case-specific context supplied "
        "below is the sanitized original request, previous invalid plan or capped stdout excerpt, "
        "and exact error. Do not infer or request any benchmark oracle.\n"
        + json.dumps(repair_input, ensure_ascii=False, sort_keys=True)
    )


def extract_json_object(stdout: str) -> dict | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", stdout):
        try:
            payload, _ = decoder.raw_decode(stdout, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def capped_stdout_excerpt(stdout: str) -> str:
    return stdout.strip()[:STDOUT_EXCERPT_LIMIT]


def normalize_actor_plan(plan: dict, request: dict) -> dict:
    """Repair schema shape only; never invent or change semantic/nutrition values."""
    if not isinstance(plan, dict) or not isinstance(plan.get("items"), list):
        return plan
    if plan_has_injected_nutrition(plan):
        return plan
    normalized = json.loads(json.dumps(plan))
    normalized = {
        key: value for key, value in normalized.items() if key in PLAN_TOP_LEVEL_FIELDS
    }
    normalized["version"] = 2
    request_profile = request.get("accuracy_profile")
    if "accuracy_profile" not in normalized and isinstance(request_profile, str):
        normalized["accuracy_profile"] = request_profile
    portion_estimates = normalized.get("portion_estimates")
    if isinstance(portion_estimates, list):
        normalized["portion_estimates"] = {"items": portion_estimates}
    elif isinstance(portion_estimates, dict) and isinstance(
        portion_estimates.get("items"), list
    ):
        normalized["portion_estimates"] = {"items": portion_estimates["items"]}

    normalized_items = []
    for raw_item in normalized["items"]:
        if not isinstance(raw_item, dict):
            normalized_items.append(raw_item)
            continue
        item = {key: value for key, value in raw_item.items() if key in PLAN_ITEM_FIELDS}
        selection = item.get("selection")
        if isinstance(selection, dict) and isinstance(selection.get("selection"), dict):
            selection = selection["selection"]
        if isinstance(selection, dict):
            additions = selection.get("branded_selection_additions")
            if isinstance(additions, dict):
                selection = {**selection, **additions}
            relation = selection.get("relation")
            allowed = (
                SELECTION_FIELDS_BY_RELATION.get(relation)
                if isinstance(relation, str)
                else None
            )
            if allowed is not None:
                selection = {key: value for key, value in selection.items() if key in allowed}
            item["selection"] = selection
        if isinstance(item.get("pending_capture"), dict):
            item.pop("source_ref", None)
            item.pop("selection", None)
        elif isinstance(item.get("selection"), dict):
            item.pop("source_ref", None)
        normalized_items.append(item)
    normalized["items"] = normalized_items
    return normalized


def allowlisted_actor_env(host_env: dict[str, str], actor_home: Path) -> dict[str, str]:
    actor_home.mkdir(parents=True, exist_ok=True)
    for name in ("config", "cache", "data", "state"):
        (actor_home / name).mkdir(exist_ok=True)
    return {
        "HOME": str(actor_home),
        "XDG_CONFIG_HOME": str(actor_home / "config"),
        "XDG_CACHE_HOME": str(actor_home / "cache"),
        "XDG_DATA_HOME": str(actor_home / "data"),
        "XDG_STATE_HOME": str(actor_home / "state"),
        "PATH": host_env.get("PATH", os.defpath),
        "PYTHONPATH": str(ROOT),
        "LANG": host_env.get("LANG", "C.UTF-8"),
        "LC_ALL": host_env.get("LC_ALL", "C.UTF-8"),
    }


def read_events(db_path: Path) -> list[dict]:
    if not db_path.exists():
        return []
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        if connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='log_entries'"
        ).fetchone()[0] == 0:
            return []
        return [
            {
                "id": int(row["id"]),
                "kind": str(row["kind"]),
                "items": json.loads(row["items_json"]),
                "totals": {
                    key: float(row[key]) for key in ("kcal", "protein", "fat", "carbs")
                },
            }
            for row in connection.execute("SELECT * FROM log_entries ORDER BY id")
        ]
    finally:
        connection.close()


def source_ref(item: dict) -> str | None:
    if item.get("selected_source_ref"):
        return str(item["selected_source_ref"])
    source_id = item.get("source_id")
    if source_id is None:
        return None
    prefix = "off" if item.get("source") == "openfoodfacts" else item.get("source")
    return f"{prefix}:{source_id}"


def plan_has_injected_nutrition(value) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).casefold() in PROHIBITED_PLAN_KEYS
            or plan_has_injected_nutrition(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(plan_has_injected_nutrition(child) for child in value)
    return False


def expected_per_100(case: dict) -> dict[str, dict[str, float]]:
    result = {}
    providers = case["synthetic_providers"]["candidates"]
    for record in providers["usda"]:
        values = {}
        mapping = {1008: "kcal", 1003: "protein", 1004: "fat", 1005: "carbs"}
        for nutrient in record.get("foodNutrients", []):
            if nutrient.get("nutrientId") in mapping:
                values[mapping[nutrient["nutrientId"]]] = float(nutrient["value"])
        result[f"usda:{record['fdcId']}"] = values
    for record in providers["openfoodfacts"]:
        nutrients = record["nutriments"]
        result[f"off:{record['code']}"] = {
            "kcal": float(nutrients["energy-kcal_100g"]),
            "protein": float(nutrients["proteins_100g"]),
            "fat": float(nutrients["fat_100g"]),
            "carbs": float(nutrients["carbohydrates_100g"]),
        }
    return result


def evaluate(
    case: dict,
    actor_runs: list[dict],
    events: list[dict],
    requests: list[dict],
) -> dict:
    hard: list[str] = []
    ux: list[str] = []
    expected_outcome = case["expected"]["outcome"]
    cli_payloads = [run.get("cli", run) for run in actor_runs]
    cli_codes = [int(run.get("cli_returncode", 0)) for run in actor_runs]
    if expected_outcome == "error":
        if not any(code != 0 for code in cli_codes):
            hard.append("expected_error_missing")
        if events:
            hard.append("atomic_no_write_failed")
    elif any(code != 0 for code in cli_codes):
        hard.append("unexpected_cli_error")

    stored_items = [item for event in events for item in event["items"]]
    expected_inputs = [item["input"] for item in case["items"]]
    represented = {str(item.get("input")) for item in stored_items}
    if any(step.get("action_after") == "remove_logged_event" for step in case["steps"]):
        represented.update(
            str(item.get("input"))
            for payload in cli_payloads
            for item in payload.get("items", [])
        )
    if expected_outcome != "error" and not set(expected_inputs) <= represented:
        hard.append("lost_input_item")

    pending = [item for item in stored_items if item.get("status") == "pending_capture"]
    resolved = [item for item in stored_items if item.get("status") == "resolved"]
    actual_outcome = (
        "error"
        if any(code != 0 for code in cli_codes)
        else "pending"
        if pending
        else "complete"
    )
    if actual_outcome != expected_outcome:
        hard.append("incorrect_complete_status")
    if len(pending) > case["expected"]["max_followups"]:
        ux.append("max_followups_exceeded")

    allowed_refs = set(case["allowed_source_refs"])
    allowed_modes = set(case["allowed_resolution_modes"])
    allowed_names = {name.casefold() for name in case["allowed_semantic_identities"]}
    forbidden_names = {name.casefold() for name in case["forbidden_identities"]}
    forbidden_tokens = {token.casefold() for token in case["forbidden_tokens"]}
    for run in actor_runs:
        for planned_item in run.get("plan", {}).get("items", []):
            selection = planned_item.get("selection")
            if not isinstance(selection, dict):
                continue
            attestation = selection.get("semantic_attestation")
            if not isinstance(attestation, dict):
                hard.append("actor_semantic_attestation_missing")
                continue
            selected_identity = str(attestation.get("selected_identity", "")).casefold()
            if allowed_names and selected_identity not in allowed_names:
                hard.append(f"actor_semantic_identity_not_allowed:{selected_identity}")
            if selected_identity in forbidden_names or any(
                re.search(rf"\b{re.escape(token)}\b", selected_identity)
                for token in forbidden_tokens
            ):
                hard.append(
                    f"actor_forbidden_semantic_attestation:{selected_identity}"
                )
    nutrition = expected_per_100(case)
    envelopes = dict(zip(expected_inputs, case["gram_envelopes"], strict=True))
    for item in resolved:
        ref = source_ref(item)
        if ref not in allowed_refs:
            hard.append(f"source_not_allowed:{ref}")
        mode = item.get("resolution_mode")
        if mode not in allowed_modes:
            hard.append(f"resolution_mode_not_allowed:{mode}")
        name = str(item.get("name", "")).casefold()
        semantic_name = name.split(" — ", 1)[0]
        if allowed_names and semantic_name not in allowed_names:
            hard.append(f"semantic_identity_not_allowed:{name}")
        if name in forbidden_names or any(
            re.search(rf"\b{re.escape(token)}\b", name) for token in forbidden_tokens
        ):
            hard.append(f"catastrophic_semantic_substitution:{name}")
        envelope = envelopes.get(str(item.get("input")))
        grams = float(item.get("grams", 0))
        if envelope is not None and not float(envelope[0]) <= grams <= float(envelope[1]):
            ux.append(f"grams_outside_envelope:{grams}")
        if not item.get("source") or not ref or not item.get("provenance"):
            hard.append("source_or_provenance_missing")
        if (
            mode in {"generic_proxy", "probable_product"} or item.get("approximate")
        ) and not item.get("assumption"):
            hard.append("approximation_assumption_missing")
        facts = nutrition.get(ref or "")
        if facts:
            for key, per_100 in facts.items():
                expected_value = round(per_100 * grams / 100 + 1e-12, 2)
                if abs(float(item[key]) - expected_value) > 0.011:
                    hard.append(f"invented_nutrition:{ref}:{key}")

    if any(plan_has_injected_nutrition(run.get("plan", {})) for run in actor_runs):
        hard.append("agent_nutrition_injection")
    search_attempts = sum(
        request["path"] in {"/off/search", "/usda/search"} for request in requests
    )
    if case["expected"]["text_search_must_be_attempted"] and search_attempts == 0:
        ux.append("text_search_not_attempted")
    if case["category"] == "branded" and pending and search_attempts == 0:
        ux.append("immediate_capture_without_search")

    return {
        "id": case["id"],
        "category": case["category"],
        "profile": case["profile"],
        "pass": not hard and not ux,
        "hard_failures": sorted(set(hard)),
        "ux_failures": sorted(set(ux)),
        "outcome": actual_outcome,
        "followups": len(pending),
        "text_search_attempts": search_attempts,
        "resolved_items": len(resolved),
        "event_count": len(events),
    }


def run_actor(
    *,
    actor_command: str,
    request: dict,
    host_env: dict[str, str],
    episode_dir: Path,
    suffix: str,
    auth_launcher_command: str | None,
    prompt_override: str | None = None,
) -> dict:
    actor_result = episode_dir / f"actor-{suffix}.json"
    actor_home = episode_dir / f"actor-home-{suffix}"
    actor_env = allowlisted_actor_env(host_env, actor_home)
    request_json = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
    prompt = prompt_override if prompt_override is not None else actor_prompt(request)
    command_template = auth_launcher_command or actor_command
    command = render_command(
        command_template,
        {
            "prompt": prompt,
            "request": request_json,
            "sandbox": str(episode_dir),
            "actor_result": str(actor_result),
            "max_turns": "1",
        },
    )
    def persist(payload: dict) -> dict:
        payload["actor_result"] = actor_result.name
        actor_result.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return payload

    try:
        completed = subprocess.run(
            command,
            cwd=episode_dir,
            env=host_env if auth_launcher_command else actor_env,
            check=False,
            capture_output=True,
            text=True,
            timeout=180 if auth_launcher_command else 90,
        )
    except subprocess.TimeoutExpired:
        return persist(
            {
                "actor_returncode": 124,
                "actor_error_kind": "process_timeout",
                "actor_process_error": "actor command exceeded its bounded timeout",
            }
        )

    if completed.returncode != 0:
        return persist({
            "actor_returncode": completed.returncode,
            "actor_error_kind": "process_failure",
            "actor_process_error": "actor command returned a nonzero status",
        })
    payload = extract_json_object(completed.stdout)
    if payload is not None:
        return persist({"actor_returncode": 0, "plan": payload})
    return persist({
        "actor_returncode": 70,
        "actor_error_kind": "parse_failure",
        "actor_process_error": "actor stdout did not contain one parseable JSON object",
        "actor_stdout_excerpt": capped_stdout_excerpt(completed.stdout),
    })


def run_actor_step(
    *,
    actor_command: str,
    request: dict,
    host_env: dict[str, str],
    cli_env: dict[str, str],
    episode_dir: Path,
    suffix: str,
    auth_launcher_command: str | None,
) -> dict:
    def complete_attempt(
        *,
        attempt_number: int,
        prompt_kind: str,
        prompt_override: str | None = None,
    ) -> dict:
        attempt = run_actor(
            actor_command=actor_command,
            request=request,
            host_env=host_env,
            episode_dir=episode_dir,
            suffix=suffix if attempt_number == 1 else f"{suffix}-repair",
            auth_launcher_command=auth_launcher_command,
            prompt_override=prompt_override,
        )
        attempt["attempt"] = attempt_number
        attempt["prompt_kind"] = prompt_kind
        plan = attempt.get("plan")
        if isinstance(plan, dict):
            normalized_plan = normalize_actor_plan(plan, request)
            if normalized_plan != plan:
                attempt["raw_plan"] = plan
                attempt["plan"] = normalized_plan
                plan = normalized_plan
        if plan is None:
            attempt["cli_returncode"] = attempt.get("actor_returncode", 70)
            attempt["cli"] = {
                "error": {
                    "code": "eval_actor_failed",
                    "message": attempt.get(
                        "actor_process_error", "Actor returned no plan"
                    ),
                }
            }
        else:
            intake_code, intake_payload = invoke_cli(
                [
                    "agent",
                    "intake",
                    "--plan",
                    json.dumps(plan, ensure_ascii=False),
                ],
                env=cli_env,
                cwd=episode_dir,
            )
            attempt["cli_returncode"] = intake_code
            attempt["cli"] = intake_payload
        return attempt

    initial = complete_attempt(attempt_number=1, prompt_kind="initial")
    attempts = [initial]
    parse_failed = initial.get("actor_error_kind") == "parse_failure"
    cli_error_code = initial.get("cli", {}).get("error", {}).get("code")
    intake_failed = (
        initial.get("plan") is not None
        and int(initial.get("cli_returncode", 0)) != 0
        and cli_error_code in REPAIRABLE_CLI_ERROR_CODES
    )
    if parse_failed or intake_failed:
        previous_invalid = (
            initial["plan"]
            if initial.get("plan") is not None
            else initial.get("actor_stdout_excerpt", "")
        )
        exact_error = initial["cli"]["error"]
        repaired = complete_attempt(
            attempt_number=2,
            prompt_kind="repair",
            prompt_override=repair_prompt(
                request=request,
                previous_invalid_plan_or_stdout=previous_invalid,
                exact_error=exact_error,
            ),
        )
        attempts.append(repaired)

    final = dict(attempts[-1])
    final["attempts"] = attempts
    final["final_attempt"] = len(attempts)
    final["repair_used"] = len(attempts) == 2
    final["request"] = request
    return final


def run_episode(
    case: dict,
    *,
    repeat_index: int,
    actor_command: str,
    output_root: Path,
    judge_command: str | None,
    auth_launcher_command: str | None,
) -> dict:
    episode_id = f"{case['id']}-r{repeat_index + 1:02d}"
    episode_dir = output_root / "episodes" / episode_id
    episode_dir.mkdir(parents=True, exist_ok=True)
    db_path = episode_dir / "nomnom.sqlite3"
    actor_runs = []
    with ReplayServer(case) as replay:
        environment = {
            **os.environ,
            "NOMNOM_DB_PATH": str(db_path),
            "NOMNOM_ACCURACY_PROFILE": case["profile"],
            "NOMNOM_USDA_KEY": "synthetic-eval-placeholder",
            "NOMNOM_EVAL_MODE": "1",
            "NOMNOM_EVAL_PROVIDER_URL": replay.url,
            "NOMNOM_EVAL_CLI": f"{shlex.quote(sys.executable)} -m nomnomcli",
            "XDG_CONFIG_HOME": str(episode_dir / "config"),
            "XDG_CACHE_HOME": str(episode_dir / "cache"),
            "XDG_DATA_HOME": str(episode_dir / "data"),
            "XDG_STATE_HOME": str(episode_dir / "state"),
            "PYTHONPATH": str(ROOT),
            "PATH": f"{episode_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        }
        prompts = (
            [step["raw_input"] for step in case["steps"]]
            if case["steps"]
            else [case["raw_input"]]
        )
        for index, prompt in enumerate(prompts):
            step = case["steps"][index] if case["steps"] else {}
            if step.get("action_before") == "seed_poisoned_cache":
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "nomnomcli",
                        "add",
                        "--name",
                        "apple",
                        "--brand",
                        "Synthetic Poison",
                        "--kcal",
                        "999",
                        "--protein",
                        "99",
                        "--fat",
                        "99",
                        "--carbs",
                        "99",
                        "--json",
                    ],
                    cwd=episode_dir,
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            discoveries = []
            discovery_failed = None
            for raw_item in split_items(prompt):
                discovery_code, discovery_payload = invoke_cli(
                    ["agent", "candidates", "--input", raw_item],
                    env=environment,
                    cwd=episode_dir,
                )
                if discovery_code != 0:
                    discovery_failed = {
                        "cli_returncode": discovery_code,
                        "cli": discovery_payload,
                    }
                    break
                discoveries.append(
                    {
                        "input": raw_item,
                        "discovery": sanitize_discovery(discovery_payload),
                    }
                )
            if discovery_failed is not None:
                actor_run = discovery_failed
            else:
                request = {
                    "protocol_version": 1,
                    "raw_input": prompt,
                    "accuracy_profile": case["profile"],
                    "items": discoveries,
                }
                actor_run = run_actor_step(
                    actor_command=actor_command,
                    request=request,
                    host_env=os.environ.copy(),
                    cli_env=environment,
                    episode_dir=episode_dir,
                    suffix=f"{index + 1:02d}",
                    auth_launcher_command=auth_launcher_command,
                )
            actor_runs.append(actor_run)
            if step.get("action_after") == "remove_logged_event":
                log_id = actor_runs[-1].get("cli", {}).get("log_id")
                if log_id is not None:
                    subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "nomnomcli",
                            "log",
                            "remove",
                            str(log_id),
                            "--confirm",
                            "--json",
                        ],
                        cwd=episode_dir,
                        env=environment,
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
        events = read_events(db_path)
        result = evaluate(case, actor_runs, events, list(replay.state.requests))

        if judge_command and result["outcome"] == "pending":
            actor_path = episode_dir / actor_runs[-1].get(
                "actor_result", "actor-01.json"
            )
            judge_path = episode_dir / "judge.json"
            if actor_path.resolve() == judge_path.resolve():
                result["hard_failures"].append("actor_judge_result_path_collision")
            else:
                judge_prompt = (
                    "Review only unresolved semantic ambiguity for this user input: "
                    f"{case['raw_input']}"
                )
                command = render_command(
                    judge_command,
                    {
                        "prompt": judge_prompt,
                        "sandbox": str(episode_dir),
                        "db_path": str(db_path),
                        "actor_result": str(actor_path),
                        "judge_result": str(judge_path),
                        "max_turns": "4",
                    },
                )
                completed = subprocess.run(
                    command,
                    cwd=ROOT,
                    env=allowlisted_actor_env(
                        os.environ, episode_dir / "judge-home"
                    ),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                result["judge"] = {
                    "returncode": completed.returncode,
                    "result_path": str(judge_path.relative_to(output_root)),
                }
        trace = {
            "case_id": case["id"],
            "repeat": repeat_index + 1,
            "actor_runs": actor_runs,
            "requests": replay.state.requests,
            "events": events,
            "evaluation": result,
        }
        (episode_dir / "trace.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    result["trace"] = str((episode_dir / "trace.json").relative_to(output_root))
    result["pass"] = not result["hard_failures"] and not result["ux_failures"]
    return result


def summarize(results: list[dict], repeats: int, *, actor_kind: str) -> dict:
    categories = defaultdict(lambda: {"passed": 0, "total": 0})
    for result in results:
        category = categories[result["category"]]
        category["total"] += 1
        category["passed"] += int(result["pass"])
    practical = [result for result in results if result["profile"] == "practical"]
    complete = sum(result["outcome"] == "complete" for result in practical)
    followup = sum(result["followups"] > 0 for result in practical)
    all_hard_counts = Counter(
        failure for result in results for failure in result["hard_failures"]
    )
    all_ux_counts = Counter(
        failure for result in results for failure in result["ux_failures"]
    )
    practical_hard_counts = Counter(
        failure for result in practical for failure in result["hard_failures"]
    )
    practical_ux_counts = Counter(
        failure for result in practical for failure in result["ux_failures"]
    )
    integrity_prefixes = (
        "actor_forbidden_semantic_attestation",
        "actor_semantic_attestation_missing",
        "actor_semantic_identity_not_allowed",
        "agent_nutrition_injection",
        "approximation_assumption_missing",
        "atomic_no_write_failed",
        "catastrophic_semantic_substitution",
        "expected_error_missing",
        "invented_nutrition",
        "lost_input_item",
        "resolution_mode_not_allowed",
        "semantic_identity_not_allowed",
        "source_not_allowed",
        "source_or_provenance_missing",
        "unexpected_cli_error",
    )
    global_integrity_failures = {
        failure: count
        for failure, count in all_hard_counts.items()
        if failure.startswith(integrity_prefixes)
    }
    portion_results = [
        result
        for result in practical
        if result["category"] == "fuzzy_portion" and result["resolved_items"]
    ]
    portion_inside = sum(
        not any(failure.startswith("grams_outside_envelope") for failure in result["ux_failures"])
        for result in portion_results
    )
    practical_metrics = {
        "catastrophic_semantic_substitutions": sum(
            count
            for failure, count in practical_hard_counts.items()
            if failure.startswith("catastrophic_semantic_substitution")
        ),
        "invented_nutrition_or_source": sum(
            count
            for failure, count in practical_hard_counts.items()
            if failure.startswith(("invented_nutrition", "source_not_allowed"))
        ),
        "lost_input_items": practical_hard_counts["lost_input_item"],
        "incorrect_complete_status": practical_hard_counts["incorrect_complete_status"],
        "one_pass_completion_rate": complete / len(practical) if practical else 0,
        "meals_requiring_followup_rate": followup / len(practical) if practical else 0,
        "max_followups_per_meal": max(
            (result["followups"] for result in practical), default=0
        ),
        "portion_inside_envelope_rate": (
            portion_inside / len(portion_results) if portion_results else 1
        ),
        "approximation_provenance_rate": (
            0 if practical_hard_counts["approximation_assumption_missing"] else 1
        ),
    }
    release_gate = {
        "catastrophic_semantic_substitutions": (
            practical_metrics["catastrophic_semantic_substitutions"] == 0
        ),
        "invented_nutrition_or_source": (
            practical_metrics["invented_nutrition_or_source"] == 0
        ),
        "lost_input_items": practical_metrics["lost_input_items"] == 0,
        "global_integrity": not global_integrity_failures,
        "one_pass_completion": practical_metrics["one_pass_completion_rate"] >= 0.95,
        "followup_rate": practical_metrics["meals_requiring_followup_rate"] <= 0.05,
        "max_followups": practical_metrics["max_followups_per_meal"] <= 1,
        "portion_envelope": practical_metrics["portion_inside_envelope_rate"] >= 0.90,
        "approximation_provenance": (
            practical_metrics["approximation_provenance_rate"] == 1
        ),
    }
    gate_metrics_passed = all(release_gate.values())
    release_evidence = actor_kind == "external"
    failed = sum(not result["pass"] for result in results)
    return {
        "schema_version": 2,
        "actor_kind": actor_kind,
        "release_evidence": release_evidence,
        "episodes": len(results),
        "repeats": repeats,
        "passed": sum(result["pass"] for result in results),
        "failed": failed,
        "categories": dict(sorted(categories.items())),
        "hard_failures": dict(sorted(all_hard_counts.items())),
        "ux_failures": dict(sorted(all_ux_counts.items())),
        "all_profile_counters": {
            "hard_failures": dict(sorted(all_hard_counts.items())),
            "ux_failures": dict(sorted(all_ux_counts.items())),
        },
        "practical_counters": {
            "hard_failures": dict(sorted(practical_hard_counts.items())),
            "ux_failures": dict(sorted(practical_ux_counts.items())),
        },
        "practical_metrics": practical_metrics,
        "global_integrity_failures": dict(sorted(global_integrity_failures.items())),
        "release_gate": release_gate,
        "gate_metrics_passed": gate_metrics_passed,
        "release_gate_passed": release_evidence and gate_metrics_passed,
        "harness_self_test_passed": (
            actor_kind == "fake" and gate_metrics_passed and failed == 0
        ),
        "results": results,
    }


def markdown_report(report: dict) -> str:
    lines = [
        "# nomnom universal approximation eval",
        "",
        f"- Episodes: {report['episodes']}",
        f"- Passed: {report['passed']}",
        f"- Failed: {report['failed']}",
        f"- Actor kind: {report['actor_kind']}",
        f"- Decision-grade release evidence: {'yes' if report['release_evidence'] else 'no'}",
        (
            "- Practical external-model release gate: "
            f"{'PASS' if report['release_gate_passed'] else 'NOT ESTABLISHED'}"
        ),
        (
            "- Deterministic harness self-test: "
            f"{'PASS' if report['harness_self_test_passed'] else 'not applicable'}"
        ),
        "",
        "| Category | Passed | Total | Rate |",
        "|---|---:|---:|---:|",
    ]
    for name, values in report["categories"].items():
        rate = values["passed"] / values["total"]
        lines.append(f"| {name} | {values['passed']} | {values['total']} | {rate:.1%} |")
    lines.extend(["", "## Hard failures", ""])
    lines.append(
        "- None"
        if not report["hard_failures"]
        else "\n".join(
            f"- `{name}`: {count}" for name, count in report["hard_failures"].items()
        )
    )
    lines.extend(["", "## UX failures", ""])
    lines.append(
        "- None"
        if not report["ux_failures"]
        else "\n".join(
            f"- `{name}`: {count}" for name, count in report["ux_failures"].items()
        )
    )
    lines.extend(["", "## Reproduction", "", "```sh"])
    if report["actor_kind"] == "external":
        lines.extend(
            [
                "PYTHONPATH=. python -m evals.run --mode full --repeat 3 --concurrency 4 \\",
                "  --actor-kind external \\",
                "  --actor-auth-launcher-command "
                "'hermes chat -Q --provider openai-codex -m gpt-5.6-luna "
                "--safe-mode --max-turns 1 -q {prompt}'",
            ]
        )
    else:
        lines.append(
            "PYTHONPATH=. python -m evals.run --mode full --repeat 1 --concurrency 4"
        )
    lines.extend(["```", ""])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the synthetic nomnom subprocess eval")
    parser.add_argument("--mode", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--actor-command", default=default_actor_command())
    parser.add_argument("--actor-kind", choices=("fake", "external"))
    parser.add_argument(
        "--actor-auth-launcher-command",
        help=(
            "Explicit trusted launcher boundary for external provider authentication; "
            "the launcher receives the host environment and must keep the model tool-free"
        ),
    )
    parser.add_argument("--judge-command")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    actor_kind = args.actor_kind or (
        "fake" if args.actor_command == default_actor_command() else "external"
    )
    if args.repeat < 1:
        raise SystemExit("--repeat must be at least 1")
    if not 1 <= args.concurrency <= 16:
        raise SystemExit("--concurrency must be between 1 and 16")
    corpus = load_corpus()
    cases = corpus["cases"][:3] if args.mode == "smoke" else corpus["cases"]
    (ROOT / "evals" / "artifacts").mkdir(parents=True, exist_ok=True)
    if args.output is not None and args.output.exists() and any(args.output.iterdir()):
        raise SystemExit("--output must be absent or an empty directory")
    output_root = args.output or Path(
        tempfile.mkdtemp(prefix="nomnom-eval-", dir=ROOT / "evals" / "artifacts")
    )
    output_root.mkdir(parents=True, exist_ok=True)
    jobs = [
        (case, repeat_index)
        for repeat_index in range(args.repeat)
        for case in cases
    ]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(
                run_episode,
                case,
                repeat_index=repeat_index,
                actor_command=args.actor_command,
                output_root=output_root,
                judge_command=args.judge_command,
                auth_launcher_command=args.actor_auth_launcher_command,
            )
            for case, repeat_index in jobs
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda result: (result["id"], result["trace"]))
    report = summarize(results, args.repeat, actor_kind=actor_kind)
    (output_root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "summary.md").write_text(markdown_report(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output_root),
                "episodes": report["episodes"],
                "passed": report["passed"],
                "failed": report["failed"],
                "actor_kind": report["actor_kind"],
                "release_evidence": report["release_evidence"],
                "gate_metrics_passed": report["gate_metrics_passed"],
                "release_gate_passed": report["release_gate_passed"],
                "harness_self_test_passed": report["harness_self_test_passed"],
            },
            sort_keys=True,
        )
    )
    accepted = (
        report["release_gate_passed"]
        if actor_kind == "external"
        else report["harness_self_test_passed"]
    )
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
