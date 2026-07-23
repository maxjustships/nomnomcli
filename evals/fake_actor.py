from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

NOISE_TOKENS = {
    "a",
    "an",
    "and",
    "g",
    "gram",
    "grams",
    "note",
    "of",
    "please",
    "then",
    "the",
    "uh",
    "voice",
}


def tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if token not in NOISE_TOKENS and not token.isdigit()
    }


def cli_command() -> list[str]:
    configured = os.environ.get("NOMNOM_EVAL_CLI", "").strip()
    return shlex.split(configured) if configured else [sys.executable, "-m", "nomnomcli"]


def invoke(arguments: list[str]) -> tuple[int, dict]:
    completed = subprocess.run(
        [*cli_command(), *arguments, "--json"],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=30,
    )
    stream = completed.stdout if completed.returncode == 0 else completed.stderr
    return completed.returncode, json.loads(stream)


def split_items(prompt: str) -> list[str]:
    return [part.strip() for part in prompt.split(";") if part.strip()]


def explicit_grams(value: str) -> float | None:
    match = re.search(r"(?<![\w.])(\d+(?:\.\d+)?)\s*g(?:rams?)?\b", value.casefold())
    return float(match.group(1)) if match else None


def looks_branded(value: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", value)
    return len(words) > 1 and words[0][0].isupper()


def choose_candidate(raw_item: str, discovery: dict) -> dict | None:
    raw_tokens = tokens(raw_item)
    ranked = []
    for candidate in discovery["candidates"]:
        candidate_tokens = tokens(
            " ".join(
                str(value)
                for value in (
                    candidate.get("canonical_name"),
                    candidate.get("brand"),
                    candidate.get("category"),
                )
                if value
            )
        )
        overlap = len(raw_tokens & candidate_tokens)
        ranked.append(
            (
                overlap,
                candidate["candidate_status"] == "probable_brand_match",
                candidate["direct_source_ref_eligible"],
                candidate,
            )
        )
    ranked.sort(key=lambda entry: (-entry[0], -entry[1], -entry[2], entry[3]["source_ref"]))
    if not ranked or ranked[0][0] == 0:
        return None
    return ranked[0][3]


def pending_item(raw_item: str) -> dict:
    return {
        "input": raw_item,
        "pending_capture": {
            "status": "pending_capture",
            "action": "photo_or_barcode",
        },
    }


def build_plan(prompt: str, profile: str) -> dict:
    plan_items = []
    estimates = []
    discoveries = []
    for index, raw_item in enumerate(split_items(prompt)):
        code, discovery = invoke(["agent", "candidates", "--input", raw_item])
        if code != 0:
            plan_items.append(pending_item(raw_item))
            discoveries.append(discovery)
            continue
        discoveries.append(discovery)
        candidate = choose_candidate(raw_item, discovery)
        grams = explicit_grams(raw_item)
        fuzzy = grams is None
        if candidate is None or profile == "exact" and fuzzy:
            plan_items.append(pending_item(raw_item))
            continue
        status = candidate["candidate_status"]
        branded = looks_branded(raw_item)
        if profile == "exact" and (branded or status == "probable_brand_match"):
            plan_items.append(pending_item(raw_item))
            continue

        item = {"input": raw_item}
        if status == "probable_brand_match":
            item["selection"] = {
                "source_ref": candidate["source_ref"],
                "relation": "probable_brand_match",
                "assumption": (
                    "Provider text match is probable only; no barcode or label established "
                    "exact product identity."
                ),
                "discovery_receipt": discovery["discovery_receipt"],
            }
        elif branded:
            selection = {
                "source_ref": candidate["source_ref"],
                "relation": "branded_same_type_generic",
                "assumption": (
                    "Brand/SKU was not exact; used a source-backed same-type generic proxy "
                    "after provider text discovery."
                ),
                "discovery_receipt": discovery["discovery_receipt"],
            }
            if profile == "balanced":
                selection["risk_disposition"] = "material_risk_accepted"
            item["selection"] = selection
        elif candidate["direct_source_ref_eligible"]:
            item["source_ref"] = candidate["source_ref"]
        else:
            item["selection"] = {
                "source_ref": candidate["source_ref"],
                "relation": "semantic_equivalent",
                "assumption": (
                    "External actor selected this source-backed same-type semantic record."
                ),
            }

        if fuzzy:
            estimate = {
                "item_index": index,
                "input": raw_item,
                "grams": 50,
                "lower_grams": 40,
                "upper_grams": 60,
                "confidence": 0.7,
                "method": "agent_estimate",
                "assumption": "External actor estimated the fuzzy portion at 50 g.",
            }
            estimates.append(estimate)
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
    return {"plan": plan, "discoveries": discoveries}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    args = parser.parse_args()
    profile = os.environ.get("NOMNOM_ACCURACY_PROFILE", "balanced")
    actor = build_plan(args.prompt, profile)
    code, payload = invoke(["agent", "intake", "--plan", json.dumps(actor["plan"])])
    result = {
        "actor_status": "complete" if code == 0 else "error",
        "cli_returncode": code,
        "cli": payload,
        **actor,
    }
    trace_path = os.environ.get("NOMNOM_ACTOR_TRACE_PATH")
    if trace_path:
        Path(trace_path).write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
