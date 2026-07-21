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
GENERATED_DIRECTORY_NAMES = {
    ".git",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "venv",
}


def _git_tracked_paths(root: Path) -> set[str] | None:
    try:
        top_level = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if Path(top_level).resolve() != root.resolve():
            return None
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return {path.decode() for path in result.stdout.split(b"\0") if path}


def _filesystem_paths(root: Path) -> set[str]:
    paths = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(
            part in GENERATED_DIRECTORY_NAMES or part.endswith(".egg-info")
            for part in relative.parts
        ):
            continue
        if path.is_file():
            paths.add(relative.as_posix())
    return paths


def tracked_paths(root: Path = ROOT) -> set[str]:
    git_paths = _git_tracked_paths(root)
    if git_paths is not None:
        return git_paths
    return _filesystem_paths(root)


def test_architecture_contracts_exist_and_root_contract_is_concise():
    assert all(path.is_file() for path in CONTRACT_PATHS)
    assert len(CONTRACT_PATHS[0].read_text(encoding="utf-8").splitlines()) < 180


def test_architecture_contracts_are_linked_from_readme_and_skill():
    for path in (ROOT / "README.md", ROOT / "skill" / "SKILL.md"):
        text = path.read_text(encoding="utf-8")
        assert "AGENTS.md" in text
        assert "docs/ARCHITECTURE.md" in text


def test_installed_skill_uses_stable_contract_links():
    skill = (ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8")
    assert "https://github.com/maxjustships/nomnomcli/blob/main/AGENTS.md" in skill
    assert (
        "https://github.com/maxjustships/nomnomcli/blob/main/docs/ARCHITECTURE.md" in skill
    )


def test_tracked_paths_fall_back_without_git_and_ignore_generated_artifacts(
    monkeypatch, tmp_path
):
    archive_root = tmp_path / "nomnomcli-source"
    (archive_root / "tests" / "fixtures").mkdir(parents=True)
    (archive_root / "build").mkdir()
    (archive_root / "nomnomcli.egg-info").mkdir()
    (archive_root / "AGENTS.md").write_text("contract", encoding="utf-8")
    (archive_root / "tests" / "fixtures" / "foods.json").write_text("{}", encoding="utf-8")
    (archive_root / "build" / "generated.json").write_text("{}", encoding="utf-8")
    (archive_root / "nomnomcli.egg-info" / "generated.json").write_text(
        "{}", encoding="utf-8"
    )

    def git_unavailable(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", git_unavailable)

    assert tracked_paths(archive_root) == {
        "AGENTS.md",
        "tests/fixtures/foods.json",
    }


def test_tracked_paths_preserve_git_index_behavior(monkeypatch, tmp_path):
    (tmp_path / "tracked.json").write_text("{}", encoding="utf-8")
    (tmp_path / "untracked.json").write_text("{}", encoding="utf-8")
    responses = iter(
        (
            subprocess.CompletedProcess([], 0, stdout=f"{tmp_path}\n"),
            subprocess.CompletedProcess([], 0, stdout=b"tracked.json\0"),
        )
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: next(responses))

    assert tracked_paths(tmp_path) == {"tracked.json"}


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
