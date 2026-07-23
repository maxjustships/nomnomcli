from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

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
    assert result["release_gate_passed"] is True
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["failed"] == 0
    assert len(list((output / "episodes").glob("*/nomnom.sqlite3"))) == 3
    assert default_db.read_bytes() == sentinel
