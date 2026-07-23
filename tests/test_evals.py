from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from evals.run import default_actor_command, run_actor, run_episode, summarize

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


def test_practical_release_metrics_ignore_balanced_and_exact_failures():
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
        "hard_failures": ["catastrophic_semantic_substitution:cheese"],
    }

    report = summarize([practical, balanced], 1, actor_kind="external")

    assert report["practical_metrics"]["catastrophic_semantic_substitutions"] == 0
    assert report["practical_counters"]["hard_failures"] == {}
    assert report["all_profile_counters"]["hard_failures"] == {
        "catastrophic_semantic_substitution:cheese": 1
    }
    assert report["release_gate_passed"] is True
