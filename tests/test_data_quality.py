from __future__ import annotations

import json
import subprocess
from pathlib import Path

from nomnomcli import __version__

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATHS = (ROOT / "AGENTS.md", ROOT / "docs" / "ARCHITECTURE.md")
REMOVED_FOOD_INPUTS = (
    "nomnomcli/data/foods.sqlite",
    "nomnomcli/data/synonyms_ru.json",
    "nomnomcli/data/piece_weights.json",
    "scripts/build_mini_db.py",
    "scripts/synonym_foods.json",
    "scripts/food_overrides.json",
    "nomnomcli/data/food_aliases.json",
    "nomnomcli/data/aliases.json",
)
STRUCTURED_DATA_SUFFIXES = {".csv", ".db", ".json", ".sqlite", ".sqlite3"}
ALLOWED_STRUCTURED_FIXTURES = {"tests/fixtures/foods.json"}


def tracked_paths() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return {path.decode() for path in result.stdout.split(b"\0") if path}


def test_architecture_contracts_exist_and_root_contract_is_concise():
    assert all(path.is_file() for path in CONTRACT_PATHS)
    assert len(CONTRACT_PATHS[0].read_text(encoding="utf-8").splitlines()) < 180


def test_architecture_contracts_are_linked_from_readme_and_skill():
    for path in (ROOT / "README.md", ROOT / "skill" / "SKILL.md"):
        text = path.read_text(encoding="utf-8")
        assert "AGENTS.md" in text
        assert "docs/ARCHITECTURE.md" in text


def test_repository_contains_no_bundled_food_data_or_build_inputs():
    remaining = [path for path in REMOVED_FOOD_INPUTS if (ROOT / path).exists()]
    assert remaining == []
    assert not (ROOT / "nomnomcli" / "data").exists()


def test_tracked_structured_data_is_limited_to_intentional_tiny_fixtures():
    payloads = {
        path for path in tracked_paths() if Path(path).suffix.lower() in STRUCTURED_DATA_SUFFIXES
    }
    assert payloads == ALLOWED_STRUCTURED_FIXTURES
    assert all((ROOT / path).stat().st_size <= 10_000 for path in payloads)


def test_package_metadata_has_no_food_data_patterns():
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.setuptools.package-data]" not in metadata
    assert "data/*.sqlite" not in metadata
    assert "data/*.json" not in metadata


def test_runtime_has_no_bundled_food_references():
    runtime = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((ROOT / "nomnomcli").rglob("*.py"))
    )
    forbidden_references = (
        "food_aliases.json",
        "foods.sqlite",
        "importlib.resources",
        "nomnomcli.data",
        "nomnomcli/0.2",
        "offline food database",
        "piece_weights.json",
        'source: str = "bundled"',
        "synonyms_ru.json",
    )
    assert [reference for reference in forbidden_references if reference in runtime] == []


def test_food_fixture_corpus_is_limited_to_ten_records():
    fixtures = json.loads((ROOT / "tests" / "fixtures" / "foods.json").read_text())
    record_count = len(fixtures["cache"]) + len(fixtures["off"]) + 1
    assert record_count <= 10


def test_package_version_is_040():
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert __version__ == "0.4.0"
    assert 'version = "0.4.0"' in metadata


def test_readme_documents_language_agnostic_agent_contract():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Canonical agent input contract" in readme
    assert "food name + quantity + unit + optional modifiers" in readme
    assert "### Adding a new language" in readme
    assert "parser code changes are not required for ordinary unit aliases" in readme


def test_v04_docs_define_safe_proxy_and_private_exact_capture_flow():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    skill = (ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8")

    assert "The default generic policy is `allow_for_unbranded`" in readme
    assert "nomnom capture barcode" in readme
    assert "nomnom capture label" in readme
    assert "`--source-note` is required" in readme
    assert "never receives or stores the photo" in readme
    assert "request a clear package photo" in skill
    assert "Vision/OCR remains agent-side" in skill
    assert "Candidate confidence never establishes exact identity." in readme
    assert "unbranded text is always a `generic_proxy`" in readme
    assert "never makes an arbitrary branded result `exact_product`" in skill
    assert len(skill.splitlines()) <= 200


def test_contract_docs_enforce_critical_data_identity_and_privacy_rules():
    contract = " ".join(
        " ".join(path.read_text(encoding="utf-8").lower().split()) for path in CONTRACT_PATHS
    )

    required_rules = (
        "no bundled production food",
        "static food aliases",
        "static food synonym/translation corpus",
        "never silently substitute",
        "never open or operate on a real user's database",
        "must never write aliases, cache entries, logs, or user data",
    )
    assert all(rule in contract for rule in required_rules)
