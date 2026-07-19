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


def test_package_version_is_030():
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert __version__ == "0.3.0"
    assert 'version = "0.3.0"' in metadata
