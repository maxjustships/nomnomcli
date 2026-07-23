from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from evals import fake_actor, generate_corpus
from evals import run as eval_run
from evals.run import (
    actor_prompt,
    default_actor_command,
    extract_json_object,
    normalize_actor_plan,
    repair_prompt,
    run_actor,
    run_actor_step,
    run_episode,
    summarize,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "evals" / "corpus.json"
EXPECTED_COUNTS = {
    "measured_generic": 20,
    "fuzzy_portion": 20,
    "branded": 20,
    "mixed_voice": 15,
    "cooking_yield": 10,
    "ambiguity_failure": 10,
    "stateful": 5,
}
REQUIRED_CASE_FIELDS = {
    "id",
    "category",
    "profile",
    "raw_input",
    "items",
    "synthetic_providers",
    "allowed_semantic_identities",
    "allowed_source_refs",
    "allowed_resolution_modes",
    "forbidden_identities",
    "forbidden_tokens",
    "gram_envelopes",
    "expected",
    "steps",
}


def test_eval_corpus_has_exactly_100_fully_declared_synthetic_cases():
    payload = json.loads(CORPUS.read_text(encoding="utf-8"))
    cases = payload["cases"]

    assert payload["schema_version"] == 1
    assert len(cases) == 100
    assert len({case["id"] for case in cases}) == 100
    assert Counter(case["category"] for case in cases) == EXPECTED_COUNTS
    assert payload["category_counts"] == EXPECTED_COUNTS
    for case in cases:
        assert set(case) == REQUIRED_CASE_FIELDS
        assert case["profile"] in {"practical", "balanced", "exact"}
        assert case["raw_input"].strip()
        assert case["items"]
        assert len(case["items"]) == len(case["gram_envelopes"])
        assert set(case["synthetic_providers"]) == {"candidates", "responses"}
        assert set(case["synthetic_providers"]["candidates"]) == {
            "openfoodfacts",
            "usda",
        }
        assert set(case["expected"]) == {
            "outcome",
            "max_followups",
            "text_search_must_be_attempted",
        }
        serialized = json.dumps(case).casefold()
        assert "api_key" not in serialized
        assert "credential" not in serialized
        assert "/home/" not in serialized


def test_eval_oracle_contains_required_semantic_adversaries():
    cases = {case["id"]: case for case in json.loads(CORPUS.read_text())["cases"]}

    assert cases["ambiguity-01"]["raw_input"] == "50 g cooked egg"
    assert "cooked cheese" in cases["ambiguity-01"]["forbidden_identities"]
    assert {"chocolate milk", "condensed milk"} <= set(
        cases["ambiguity-02"]["forbidden_identities"]
    )
    assert "tomato powder" in cases["ambiguity-03"]["forbidden_identities"]
    assert {"bread crumbs", "bread crackers"} <= set(
        cases["ambiguity-04"]["forbidden_identities"]
    )


def test_eval_smoke_uses_cli_subprocess_and_never_opens_default_user_db(tmp_path):
    fake_home = tmp_path / "home"
    default_db = fake_home / ".local" / "share" / "nomnomcli" / "nomnom.sqlite3"
    default_db.parent.mkdir(parents=True)
    sentinel = b"do-not-open-real-user-db"
    default_db.write_bytes(sentinel)
    output = tmp_path / "report"
    environment = {
        **os.environ,
        "HOME": str(fake_home),
        "PYTHONPATH": str(ROOT),
    }

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "evals.run",
            "--mode",
            "smoke",
            "--repeat",
            "1",
            "--concurrency",
            "2",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    result = json.loads(completed.stdout)
    assert result["episodes"] == 3
    assert result["passed"] == 3
    assert result["actor_kind"] == "fake"
    assert result["release_evidence"] is False
    assert result["release_gate_passed"] is False
    assert result["harness_self_test_passed"] is True
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["failed"] == 0
    assert report["gate_metrics_passed"] is True
    assert len(list((output / "episodes").glob("*/nomnom.sqlite3"))) == 3
    assert default_db.read_bytes() == sentinel


def test_adversarial_actor_oracle_and_harris_dismissal_paths(tmp_path):
    cases = {case["id"]: case for case in json.loads(CORPUS.read_text())["cases"]}
    output = tmp_path / "focused-evals"
    for case_id in ("ambiguity-01", "branded-01"):
        result = run_episode(
            cases[case_id],
            repeat_index=0,
            actor_command=default_actor_command(),
            output_root=output,
            judge_command=None,
            auth_launcher_command=None,
        )
        assert result["pass"] is True, result

    cooked_trace = json.loads(
        (output / "episodes" / "ambiguity-01-r01" / "trace.json").read_text()
    )
    cooked_plan = cooked_trace["actor_runs"][0]["plan"]
    assert (
        cooked_plan["items"][0].get("selection", {}).get("semantic_attestation", {})
        .get("selected_identity")
        != "cooked cheese"
    )

    harris_trace = json.loads(
        (output / "episodes" / "branded-01-r01" / "trace.json").read_text()
    )
    selection = harris_trace["actor_runs"][0]["plan"]["items"][0]["selection"]
    assert selection["relation"] == "branded_same_type_generic"
    assert selection["dismissed_brand_candidates"] == [
        {
            "source_ref": (
                "off:"
                + cases["branded-01"]["synthetic_providers"]["candidates"][
                    "openfoodfacts"
                ][0]["code"]
            ),
            "reason": "different_food_type",
        }
    ]


def test_generic_actor_environment_is_allowlisted_and_documented_adapter_is_tool_free(
    tmp_path, monkeypatch
):
    script = tmp_path / "capture_actor.py"
    script.write_text(
        "import argparse, json, os\n"
        "from pathlib import Path\n"
        "p=argparse.ArgumentParser(); p.add_argument('--capture'); "
        "p.add_argument('--request'); a=p.parse_args()\n"
        "Path(a.capture).write_text(json.dumps(dict(os.environ)), encoding='utf-8')\n"
        "print('{}')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NOMNOM_EVAL_SENTINEL_SECRET", "must-not-leak")
    monkeypatch.setenv("HOME", str(tmp_path / "host-home"))
    episode = tmp_path / "episode"
    episode.mkdir()
    request = {
        "protocol_version": 1,
        "raw_input": "50 g egg",
        "accuracy_profile": "practical",
        "items": [],
    }

    run_actor(
        actor_command=(
            f"{sys.executable} {script} --capture {{sandbox}}/env.json "
            "--request {request}"
        ),
        request=request,
        host_env=os.environ.copy(),
        episode_dir=episode,
        suffix="01",
        auth_launcher_command=None,
    )

    actor_env = json.loads((episode / "env.json").read_text())
    assert "NOMNOM_EVAL_SENTINEL_SECRET" not in actor_env
    assert actor_env["HOME"] != os.environ["HOME"]
    adapter = (
        "hermes chat -Q --provider openai-codex -m gpt-5.6-luna "
        "--safe-mode --max-turns 1 -q {prompt}"
    )
    assert "-t terminal" not in adapter
    assert "-s nomnomcli" not in adapter


def test_actor_prompt_exposes_exact_plan_grammar_without_golden_oracle():
    request = {
        "protocol_version": 1,
        "raw_input": "40 g apple",
        "accuracy_profile": "practical",
        "items": [
            {
                "input": "40 g apple",
                "discovery": {
                    "query": "apple",
                    "candidates": [
                        {
                            "source_ref": "usda:10001",
                            "semantic_identity": "apple",
                            "direct_source_ref_eligible": True,
                        }
                    ],
                },
            }
        ],
    }

    prompt = actor_prompt(request)

    assert '"top_level"' in prompt
    assert '"exactly_one_identity_state"' in prompt
    assert '"direct_measured_template"' in prompt
    assert '"source_ref": "COPY_ELIGIBLE_SOURCE_REF"' in prompt
    assert "There is no relation named exact or exact_same_type" in prompt
    assert "complete plan object, never a single item or selection" in prompt
    assert "exactly one item for every SANITIZED REQUEST item" in prompt
    assert "use probable_brand_match rather than pending_capture" in prompt
    assert "protocol_version, plan_version, raw_input" in prompt
    assert "allowed_source_refs" not in prompt
    assert "forbidden_identities" not in prompt


def test_external_actor_json_extraction_accepts_fenced_multiline_object():
    stdout = "Here is the plan:\n```json\n{\n  \"version\": 2,\n  \"items\": []\n}\n```\n"

    assert extract_json_object(stdout) == {"version": 2, "items": []}
    assert extract_json_object("not json") is None


def test_external_actor_timeout_is_persisted_instead_of_crashing_run(monkeypatch, tmp_path):
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timed_out)

    result = run_actor(
        actor_command="actor {prompt}",
        request={"raw_input": "40 g apple", "items": []},
        host_env={},
        episode_dir=tmp_path,
        suffix="01",
        auth_launcher_command="launcher {prompt}",
    )

    assert result["actor_returncode"] == 124
    assert result["actor_error_kind"] == "process_timeout"
    assert json.loads((tmp_path / "actor-01.json").read_text()) == result


def test_repair_prompt_reuses_contract_and_removes_oracle_and_nutrition():
    request = {
        "raw_input": "a handful of almonds",
        "items": [],
        "allowed_source_refs": ["usda:secret"],
        "expected": {"outcome": "complete"},
        "synthetic_providers": {"nutrition": "must-not-leak"},
    }
    prompt = repair_prompt(
        request=request,
        previous_invalid_plan_or_stdout={"calories": 999, "version": 2},
        exact_error={"code": "agent_plan_invalid", "details": {"grams": 123}},
    )

    assert '"direct_measured_template"' in prompt
    assert "single bounded internal repair turn" in prompt
    assert "Reconstruct the COMPLETE plan from scratch" in prompt
    assert "allowed_source_refs" not in prompt
    assert "synthetic_providers" not in prompt
    assert "must-not-leak" not in prompt
    assert '"calories"' not in prompt


def test_actor_step_repairs_one_invalid_draft_and_returns_only_final(monkeypatch, tmp_path):
    calls = []

    def fake_actor(**kwargs):
        calls.append(kwargs)
        return (
            {"actor_returncode": 0, "plan": {"version": 2, "bad": True}}
            if len(calls) == 1
            else {"actor_returncode": 0, "plan": {"version": 2, "items": []}}
        )

    def fake_intake(args, **kwargs):
        if '"bad": true' in args[-1]:
            return 2, {"error": {"code": "agent_plan_invalid", "message": "bad"}}
        return 0, {"items": []}

    monkeypatch.setattr(eval_run, "run_actor", fake_actor)
    monkeypatch.setattr(eval_run, "invoke_cli", fake_intake)

    result = run_actor_step(
        actor_command="actor {prompt}",
        request={"raw_input": "40 g apple", "items": []},
        host_env={},
        cli_env={},
        episode_dir=tmp_path,
        suffix="01",
        auth_launcher_command=None,
    )

    assert len(calls) == 2
    assert result["repair_used"] is True
    assert result["final_attempt"] == 2
    assert result["cli_returncode"] == 0
    assert result["plan"] == {"version": 2, "items": []}
    assert len(result["attempts"]) == 2


def test_actor_step_does_not_retry_after_successful_cli_write(monkeypatch, tmp_path):
    calls = []

    def fake_actor(**kwargs):
        calls.append(kwargs)
        return {"actor_returncode": 0, "plan": {"version": 2, "items": []}}

    monkeypatch.setattr(eval_run, "run_actor", fake_actor)
    monkeypatch.setattr(eval_run, "invoke_cli", lambda *args, **kwargs: (0, {"items": []}))

    result = run_actor_step(
        actor_command="actor {prompt}",
        request={"raw_input": "40 g apple", "items": []},
        host_env={},
        cli_env={},
        episode_dir=tmp_path,
        suffix="01",
        auth_launcher_command=None,
    )

    assert len(calls) == 1
    assert result["repair_used"] is False
    assert result["final_attempt"] == 1


def test_actor_step_repairs_parse_failure_once(monkeypatch, tmp_path):
    calls = []

    def fake_actor(**kwargs):
        calls.append(kwargs)
        return (
            {
                "actor_returncode": 70,
                "actor_error_kind": "parse_failure",
                "actor_process_error": "no JSON",
                "actor_stdout_excerpt": "```not-json",
            }
            if len(calls) == 1
            else {"actor_returncode": 0, "plan": {"version": 2, "items": []}}
        )

    monkeypatch.setattr(eval_run, "run_actor", fake_actor)
    monkeypatch.setattr(eval_run, "invoke_cli", lambda *args, **kwargs: (0, {"items": []}))

    result = run_actor_step(
        actor_command="actor {prompt}",
        request={"raw_input": "40 g apple", "items": []},
        host_env={},
        cli_env={},
        episode_dir=tmp_path,
        suffix="01",
        auth_launcher_command=None,
    )

    assert len(calls) == 2
    assert result["repair_used"] is True
    assert result["cli_returncode"] == 0


def test_actor_step_preserves_failed_repair_as_final_error(monkeypatch, tmp_path):
    calls = []

    def fake_actor(**kwargs):
        calls.append(kwargs)
        return {"actor_returncode": 0, "plan": {"version": 2, "invalid": len(calls)}}

    monkeypatch.setattr(eval_run, "run_actor", fake_actor)
    monkeypatch.setattr(
        eval_run,
        "invoke_cli",
        lambda *args, **kwargs: (
            2,
            {"error": {"code": "agent_plan_invalid", "message": "still invalid"}},
        ),
    )

    result = run_actor_step(
        actor_command="actor {prompt}",
        request={"raw_input": "40 g apple", "items": []},
        host_env={},
        cli_env={},
        episode_dir=tmp_path,
        suffix="01",
        auth_launcher_command=None,
    )

    assert len(calls) == 2
    assert result["repair_used"] is True
    assert result["final_attempt"] == 2
    assert result["cli_returncode"] == 2
    assert result["cli"]["error"]["message"] == "still invalid"


def test_generated_fuzzy_envelopes_are_realistic_and_match_corpus():
    generated = generate_corpus.build_corpus()
    stored = json.loads(CORPUS.read_text())
    assert generated == stored
    fuzzy = {case["id"]: case["gram_envelopes"] for case in generated["cases"]}
    assert fuzzy["fuzzy-01"] == [[20, 45]]
    assert fuzzy["fuzzy-02"] == [[100, 300]]
    assert fuzzy["fuzzy-16"] == [[150, 400]]
    assert fuzzy["fuzzy-18"] == [[30, 220]]
    assert fuzzy["fuzzy-05"] == [None]


def test_fake_actor_fuzzy_heuristic_tracks_portion_shape_not_single_50g_default():
    assert fake_actor.fuzzy_grams("a handful of almonds") == 30
    assert fake_actor.fuzzy_grams("half a bowl of porridge") == 200
    assert fake_actor.fuzzy_grams("one mug of cocoa") == 250


def test_schema_normalizer_is_mechanical_and_preserves_nutrition_rejection():
    plan = {
        "version": 1,
        "raw_input": "not a plan field",
        "items": [
            {
                "input": "one fist of pasta",
                "selection": {
                    "input": "forbidden here",
                    "source_ref": "usda:1",
                    "relation": "semantic_equivalent",
                    "assumption": "same pasta type",
                    "discovery_receipt": "forbidden for this relation",
                    "semantic_attestation": {"version": 1},
                },
            }
        ],
        "portion_estimates": [{"item_index": 0, "grams": 100}],
    }

    normalized = normalize_actor_plan(plan, {"accuracy_profile": "practical"})

    assert set(normalized) == {"version", "accuracy_profile", "items", "portion_estimates"}
    assert normalized["version"] == 2
    assert normalized["portion_estimates"] == {"items": [{"item_index": 0, "grams": 100}]}
    assert set(normalized["items"][0]["selection"]) == {
        "source_ref",
        "relation",
        "assumption",
        "semantic_attestation",
    }
    injected = {"version": 2, "items": [], "nutrition": {"kcal": 100}}
    assert normalize_actor_plan(injected, {"accuracy_profile": "practical"}) == injected


def test_integrity_cli_error_is_not_repaired_into_a_write(monkeypatch, tmp_path):
    calls = []

    def fake_actor(**kwargs):
        calls.append(kwargs)
        return {"actor_returncode": 0, "plan": {"version": 2, "items": []}}

    monkeypatch.setattr(eval_run, "run_actor", fake_actor)
    monkeypatch.setattr(
        eval_run,
        "invoke_cli",
        lambda *args, **kwargs: (
            2,
            {"error": {"code": "agent_source_ref_mismatch", "message": "changed source"}},
        ),
    )

    result = run_actor_step(
        actor_command="actor {prompt}",
        request={"raw_input": "70 g lentils", "items": []},
        host_env={},
        cli_env={},
        episode_dir=tmp_path,
        suffix="01",
        auth_launcher_command=None,
    )

    assert len(calls) == 1
    assert result["repair_used"] is False
    assert result["cli"]["error"]["code"] == "agent_source_ref_mismatch"


def test_practical_release_metrics_ignore_balanced_reliability_failures():
    practical = {
        "id": "p",
        "category": "measured_generic",
        "profile": "practical",
        "pass": True,
        "hard_failures": [],
        "ux_failures": [],
        "outcome": "complete",
        "followups": 0,
        "resolved_items": 1,
    }
    balanced = {
        **practical,
        "id": "b",
        "profile": "balanced",
        "pass": False,
        "hard_failures": [
            "incorrect_complete_status",
            "lost_input_item",
            "unexpected_cli_error",
        ],
        "ux_failures": ["max_followups_exceeded"],
    }

    report = summarize([practical, balanced], 1, actor_kind="external")

    assert report["practical_metrics"]["catastrophic_semantic_substitutions"] == 0
    assert report["practical_counters"]["hard_failures"] == {}
    assert report["all_profile_counters"]["hard_failures"] == {
        "incorrect_complete_status": 1,
        "lost_input_item": 1,
        "unexpected_cli_error": 1,
    }
    assert report["global_integrity_failures"] == {}
    assert report["release_gate_passed"] is True


def test_global_semantic_integrity_blocks_release_in_every_profile():
    result = {
        "id": "b",
        "category": "measured_generic",
        "profile": "balanced",
        "pass": False,
        "hard_failures": ["catastrophic_semantic_substitution:cheese"],
        "ux_failures": [],
        "outcome": "complete",
        "followups": 0,
        "resolved_items": 1,
    }
    practical = {**result, "id": "p", "profile": "practical", "pass": True, "hard_failures": []}

    report = summarize([practical, result], 1, actor_kind="external")

    assert report["release_gate"]["global_integrity"] is False
    assert report["release_gate_passed"] is False


def test_external_release_uses_practical_thresholds_not_perfect_episode_score():
    complete = {
        "id": "p",
        "category": "measured_generic",
        "profile": "practical",
        "pass": True,
        "hard_failures": [],
        "ux_failures": [],
        "outcome": "complete",
        "followups": 0,
        "resolved_items": 1,
    }
    results = [{**complete, "id": f"p-{index}"} for index in range(19)]
    results.append(
        {
            **complete,
            "id": "p-pending",
            "pass": False,
            "hard_failures": ["incorrect_complete_status"],
            "ux_failures": ["max_followups_exceeded"],
            "outcome": "pending",
            "followups": 1,
            "resolved_items": 0,
        }
    )

    report = summarize(results, 1, actor_kind="external")

    assert report["passed"] == 19
    assert report["failed"] == 1
    assert report["practical_metrics"]["one_pass_completion_rate"] == 0.95
    assert report["practical_metrics"]["meals_requiring_followup_rate"] == 0.05
    assert report["release_gate_passed"] is True
