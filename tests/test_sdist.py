from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SDIST_PATHS = {
    "AGENTS.md",
    "docs/ARCHITECTURE.md",
    "skill/SKILL.md",
    "tests/fixtures/foods.json",
    "tests/test_data_quality.py",
}


def test_sdist_ships_and_runs_architecture_guardrails(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(
        ROOT,
        source,
        ignore=shutil.ignore_patterns(
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "*.egg-info",
            "__pycache__",
            "build",
            "dist",
        ),
    )
    dist = tmp_path / "dist"
    dist.mkdir()
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from setuptools.build_meta import build_sdist; "
            "build_sdist(__import__('sys').argv[1])",
            str(dist),
        ],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    )

    archives = list(dist.glob("*.tar.gz"))
    assert len(archives) == 1
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    with tarfile.open(archives[0], "r:gz") as source_archive:
        source_archive_names = {member.name for member in source_archive.getmembers()}
        for member in source_archive.getmembers():
            member_path = PurePosixPath(member.name)
            assert not member_path.is_absolute()
            assert ".." not in member_path.parts
        source_archive.extractall(extracted)

    roots = [path for path in extracted.iterdir() if path.is_dir()]
    assert len(roots) == 1
    archive_root = roots[0]
    assert {path for path in REQUIRED_SDIST_PATHS if not (archive_root / path).is_file()} == set()
    shipped_tests = {
        path.relative_to(archive_root).as_posix()
        for path in (archive_root / "tests").rglob("test_*.py")
    }
    assert shipped_tests == {"tests/test_data_quality.py"}

    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_data_quality.py"],
        cwd=archive_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    wheel_dist = tmp_path / "wheel-dist"
    wheel_dist.mkdir()
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from setuptools.build_meta import build_wheel; "
            "build_wheel(__import__('sys').argv[1])",
            str(wheel_dist),
        ],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(wheel_dist.glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as wheel:
        wheel_paths = set(wheel.namelist())
    assert not any("evals/" in path or path.endswith("corpus.json") for path in wheel_paths)
    assert not any("evals/" in name for name in source_archive_names)
