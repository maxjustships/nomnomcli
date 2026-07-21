from __future__ import annotations

import json
from pathlib import Path

from nomnomcli import __version__

ROOT = Path(__file__).resolve().parents[1]
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


def test_repository_contains_no_bundled_food_data_or_build_inputs():
    remaining = [path for path in REMOVED_FOOD_INPUTS if (ROOT / path).exists()]
    assert remaining == []


def test_package_metadata_has_no_food_data_patterns():
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.setuptools.package-data]" not in metadata
    assert "data/*.sqlite" not in metadata
    assert "data/*.json" not in metadata


def test_runtime_has_no_bundled_food_references():
    runtime = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((ROOT / "nomnomcli").glob("*.py"))
    )
    assert "nomnomcli.data" not in runtime
    assert 'source: str = "bundled"' not in runtime
    assert "nomnomcli/0.2" not in runtime
    assert "offline food database" not in runtime


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
