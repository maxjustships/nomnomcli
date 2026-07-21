from __future__ import annotations

import errno
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import nomnomcli.db as database_module
from nomnomcli.cli import main
from nomnomcli.db import connect
from nomnomcli.errors import NomnomError
from nomnomcli.foods import FoodRepository
from nomnomcli.models import Food
from nomnomcli.semantic import parse_resolution_intent


def _intent(original: str, candidates: list[dict], *, brand_intent: bool = False) -> dict:
    return {
        "version": 1,
        "original": original,
        "brand_intent": brand_intent,
        "candidates": candidates,
    }


def _strict_json_loads(value: str) -> dict:
    def reject_constant(constant: str) -> None:
        pytest.fail(f"Non-finite constant in JSON output: {constant}")

    return json.loads(value, parse_constant=reject_constant)


def _generic_food(
    name: str,
    *,
    source: str = "usda",
    source_id: str = "171477",
    confidence: float = 0.9,
    provider_type: str = "Foundation",
) -> tuple[Food, float]:
    return (
        Food(
            name=name,
            kcal=165,
            protein=31,
            fat=3.6,
            carbs=1,
            source=source,
            fdc_id=int(source_id) if source == "usda" else None,
            barcode=source_id if source == "openfoodfacts" else None,
            categories=("poultry products",),
            source_id=source_id,
            provenance=source,
            provider_data_type=provider_type if source == "usda" else None,
        ),
        confidence,
    )


def _counts(repository: FoodRepository) -> dict[str, int]:
    return {
        table: repository.user_connection.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0]
        for table in ("food_cache", "log_entries", "food_aliases", "recipes")
    }


def _database_state(path) -> tuple[bytes, int, tuple, dict[str, int]]:
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        schema = tuple(
            connection.execute(
                """SELECT type, name, tbl_name, sql FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"""
            ).fetchall()
        )
        tables = [row[1] for row in schema if row[0] == "table"]
        counts = {
            table: connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            for table in tables
        }
    return path.read_bytes(), version, schema, counts


def _directory_file_state(path) -> dict[str, bytes]:
    return {
        child.name: child.read_bytes()
        for child in sorted(path.iterdir())
        if child.is_file()
    }


def _fifo_identity(path: Path) -> tuple[int, int, int, int, int]:
    metadata = os.lstat(path)
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _run_resolve_cli(database: Path, original: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "NOMNOM_DB_PATH": str(database),
            "NOMNOM_OFFLINE": "1",
        }
    )
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "nomnomcli",
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(_intent(original, [])),
            "--json",
        ],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=2,
    )


def _create_legacy_database(path, version: int) -> None:
    extra_columns = (
        """, barcode TEXT, brand TEXT, lookup_query TEXT, alternatives_json TEXT"""
        if version == 2
        else ""
    )
    with sqlite3.connect(path) as connection:
        connection.executescript(
            f"""
            PRAGMA user_version = {version};
            CREATE TABLE food_cache (
                name TEXT PRIMARY KEY COLLATE NOCASE,
                kcal REAL NOT NULL,
                protein REAL NOT NULL,
                fat REAL NOT NULL,
                carbs REAL NOT NULL,
                piece_grams REAL,
                density_g_ml REAL,
                source TEXT NOT NULL,
                fdc_id INTEGER
                {extra_columns}
            );
            INSERT INTO food_cache
            (name, kcal, protein, fat, carbs, source)
            VALUES ('legacy oats', 71, 2.54, 1.52, 12, 'legacy fixture');
            """
        )


def _create_legacy_sku_cache_database(path) -> None:
    _create_legacy_database(path, 2)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            INSERT INTO food_cache
            (name, kcal, protein, fat, carbs, source, lookup_query)
            VALUES ('Cached legacy chicken', 165, 31, 3.6, 1,
                    'legacy fixture', 'chicken 12345');
            CREATE TABLE log_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                logged_at TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'food',
                label TEXT,
                items_json TEXT NOT NULL,
                kcal REAL NOT NULL,
                protein REAL NOT NULL,
                fat REAL NOT NULL,
                carbs REAL NOT NULL
            );
            INSERT INTO log_entries
            (logged_at, kind, label, items_json, kcal, protein, fat, carbs)
            VALUES ('2026-07-20T12:00:00+05:00', 'food', 'existing log',
                    '[]', 0, 0, 0, 0);
            """
        )


def _create_legacy_brand_cache_database(path) -> None:
    _create_legacy_database(path, 2)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """INSERT INTO food_cache
            (name, kcal, protein, fat, carbs, source, brand, lookup_query)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("Acme chicken", 165, 31, 3.6, 1, "legacy fixture", "Acme", "Acme chicken"),
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"version": 2, "original": "x", "brand_intent": False, "candidates": []},
        {"version": 1, "original": "x", "brand_intent": 0, "candidates": []},
        _intent("x", [{"query": " ", "relation": "same_form"}]),
        _intent(
            "x",
            [
                {"query": "Chicken", "relation": "same_form"},
                {"query": " chicken ", "relation": "lexical_equivalent"},
            ],
        ),
        _intent("x", [{"query": "chicken", "relation": "closest"}]),
        _intent("x", [{"query": "chicken", "relation": "generic_fallback"}]),
        _intent(
            "x",
            [
                {"query": str(index), "relation": "same_form"}
                for index in range(4)
            ],
        ),
    ],
)
def test_intent_v1_rejects_unbounded_or_invalid_payloads(payload):
    with pytest.raises(NomnomError) as caught:
        parse_resolution_intent(json.dumps(payload), expected_original="x")

    assert caught.value.code == "invalid_resolution_intent"
    assert caught.value.details["would_write"] is False


def test_intent_v1_requires_exact_original_match():
    payload = _intent(" курица ", [])

    with pytest.raises(NomnomError) as caught:
        parse_resolution_intent(json.dumps(payload), expected_original="курица")

    assert caught.value.code == "resolution_intent_original_mismatch"
    assert caught.value.details["original"] == "курица"
    assert caught.value.details["intent_original"] == " курица "


@pytest.mark.parametrize(
    "raw_intent",
    [
        '{"version": NaN, "original": "chicken", "brand_intent": false, "candidates": []}',
        '{"version": Infinity, "original": "chicken", "brand_intent": false, "candidates": []}',
        '{"version": -Infinity, "original": "chicken", "brand_intent": false, "candidates": []}',
        '{"version": 1e400, "original": "chicken", "brand_intent": false, "candidates": []}',
        '{"version": -1e400, "original": "chicken", "brand_intent": false, "candidates": []}',
        '{"version": 1, "original": "chicken", "brand_intent": false, '
        '"candidates": [{"query": 1e400, "relation": "same_form"}]}',
    ],
    ids=(
        "nan",
        "positive-infinity",
        "negative-infinity",
        "positive-overflow",
        "negative-overflow",
        "nested-overflow",
    ),
)
def test_cli_rejects_non_finite_intent_numbers_with_strict_json_error(
    tmp_path, monkeypatch, capsys, raw_intent
):
    database = tmp_path / "non-finite-intent.sqlite3"
    monkeypatch.setenv("NOMNOM_DB_PATH", str(database))
    original = "chicken"

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            raw_intent,
            "--json",
        ]
    )
    error = _strict_json_loads(capsys.readouterr().err)

    assert code == 2
    assert error["error"]["code"] == "invalid_resolution_intent"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"] == {
        "would_write": False,
        "original": original,
        "reason": "Resolution intent numbers must be finite",
    }
    assert not database.exists()


def test_cli_rejects_deeply_nested_intent_json_without_traceback(
    tmp_path, monkeypatch, capsys
):
    database = tmp_path / "deep-intent.sqlite3"
    monkeypatch.setenv("NOMNOM_DB_PATH", str(database))
    original = "chicken"
    nesting = sys.getrecursionlimit() + 100
    raw_intent = "[" * nesting + "0" + "]" * nesting

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            raw_intent,
            "--json",
        ]
    )
    captured = capsys.readouterr()
    error = _strict_json_loads(captured.err)

    assert code == 2
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert error["error"]["code"] == "invalid_resolution_intent"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"] == {
        "would_write": False,
        "original": original,
        "reason": "Resolution intent JSON exceeds safe decoder limits",
    }
    assert not database.exists()


@pytest.mark.parametrize(
    "decoder_error",
    [RecursionError(), MemoryError(), OverflowError()],
    ids=("recursion", "memory", "overflow"),
)
def test_intent_decoder_capacity_errors_are_structured(
    monkeypatch, decoder_error
):
    def fail_decode(*args, **kwargs):
        raise decoder_error

    monkeypatch.setattr("nomnomcli.semantic.json.loads", fail_decode)

    with pytest.raises(NomnomError) as caught:
        parse_resolution_intent("{}", expected_original="chicken")

    assert caught.value.code == "invalid_resolution_intent"
    assert caught.value.details == {
        "would_write": False,
        "original": "chicken",
        "reason": "Resolution intent JSON exceeds safe decoder limits",
    }


@pytest.mark.parametrize(
    ("version", "parsed_version"),
    [("true", True), ("1.0", 1.0), ("1e0", 1.0)],
    ids=["boolean", "decimal", "exponent"],
)
def test_cli_rejects_non_integer_intent_version_with_strict_json_error(
    tmp_path, monkeypatch, capsys, version, parsed_version
):
    database = tmp_path / "non-integer-version.sqlite3"
    monkeypatch.setenv("NOMNOM_DB_PATH", str(database))
    original = "chicken"
    raw_intent = (
        f'{{"version": {version}, "original": "{original}", '
        '"brand_intent": false, "candidates": []}'
    )

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            raw_intent,
            "--json",
        ]
    )
    error = _strict_json_loads(capsys.readouterr().err)

    assert code == 2
    assert error["error"]["code"] == "invalid_resolution_intent"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"] == {
        "would_write": False,
        "original": original,
        "version": parsed_version,
    }
    assert not database.exists()


def test_cli_resolve_missing_nested_database_uses_empty_snapshot_without_creating_source(
    tmp_path, monkeypatch, capsys
):
    missing_parent = tmp_path / "fresh" / "nested"
    database = missing_parent / "nomnom.sqlite3"
    original = "fresh install chicken"
    monkeypatch.setenv("NOMNOM_DB_PATH", str(database))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(_intent(original, [])),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    error = _strict_json_loads(captured.err)["error"]

    assert code == 2
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert error["code"] == "semantic_resolution_not_found"
    assert error["would_write"] is False
    assert error["details"]["would_write"] is False
    assert not missing_parent.exists()
    assert not database.exists()


def test_cli_resolve_fails_closed_if_missing_parent_appears_during_confirmation(
    tmp_path, monkeypatch, capsys
):
    appearing_parent = tmp_path / "appearing-parent"
    database = appearing_parent / "nested" / "nomnom.sqlite3"
    original = "raced fresh install chicken"
    real_open_directory = database_module._open_snapshot_directory
    target_open_count = 0

    def open_directory_with_race(component, *, directory_descriptor=None):
        nonlocal target_open_count
        if component == appearing_parent.name:
            target_open_count += 1
            if target_open_count == 2:
                appearing_parent.mkdir()
        return real_open_directory(component, directory_descriptor=directory_descriptor)

    monkeypatch.setattr(
        database_module, "_open_snapshot_directory", open_directory_with_race
    )
    monkeypatch.setenv("NOMNOM_DB_PATH", str(database))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(_intent(original, [])),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    error = _strict_json_loads(captured.err)["error"]

    assert code == 2
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert error["code"] == "database_snapshot_unstable"
    assert error["would_write"] is False
    assert target_open_count == 2
    assert not database.exists()


def test_cli_resolve_parent_renamed_during_revalidation_is_structured_without_writes(
    tmp_path, monkeypatch, capsys
):
    source_parent = tmp_path / "source-parent"
    relocated_parent = tmp_path / "relocated-parent"
    database = source_parent / "nomnom.sqlite3"
    original = "parent churn chicken"
    source_parent.mkdir()
    with connect(database):
        pass
    original_state = _database_state(database)
    original_files = _directory_file_state(source_parent)
    real_open_directory = database_module._open_snapshot_directory
    target_open_count = 0

    def open_directory_with_race(component, *, directory_descriptor=None):
        nonlocal target_open_count
        if component == source_parent.name:
            target_open_count += 1
            if target_open_count == 2:
                source_parent.rename(relocated_parent)
        return real_open_directory(component, directory_descriptor=directory_descriptor)

    monkeypatch.setattr(
        database_module, "_open_snapshot_directory", open_directory_with_race
    )
    monkeypatch.setenv("NOMNOM_DB_PATH", str(database))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(_intent(original, [])),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    error = _strict_json_loads(captured.err)["error"]
    relocated_database = relocated_parent / database.name

    assert code == 2
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert error["code"] == "database_snapshot_unstable"
    assert error["would_write"] is False
    assert error["details"]["would_write"] is False
    assert target_open_count == 2
    assert not source_parent.exists()
    assert _database_state(relocated_database) == original_state
    assert _directory_file_state(relocated_parent) == original_files


@pytest.mark.parametrize(
    "confidence",
    [float("nan"), float("inf"), float("-inf")],
    ids=("nan", "positive-infinity", "negative-infinity"),
)
def test_cli_rejects_non_finite_provider_confidence_with_strict_json_error(
    user_db, monkeypatch, capsys, confidence
):
    original = "chicken breast roasted"
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.setattr(
        "nomnomcli.usda.USDAClient.resolve",
        lambda client, query, api_key: _generic_food(query, confidence=confidence),
    )
    with connect(user_db):
        pass
    original_state = _database_state(user_db)
    original_files = _directory_file_state(user_db.parent)

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(_intent(original, [])),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    error = _strict_json_loads(captured.err)["error"]

    assert code == 2
    assert captured.out == ""
    assert error["code"] == "provider_confidence_invalid"
    assert error["would_write"] is False
    assert error["details"] == {
        "would_write": False,
        "reason": "non_finite_confidence",
        "minimum": 0.0,
        "maximum": 1.0,
    }
    assert _database_state(user_db) == original_state
    assert _directory_file_state(user_db.parent) == original_files


@pytest.mark.parametrize("candidate_kind", ["raw", "semantic"])
@pytest.mark.parametrize("nutrient", ["kcal", "protein", "fat", "carbs"])
@pytest.mark.parametrize(
    "invalid_value",
    [-1.0, "NaN", "Infinity", "-Infinity"],
    ids=("negative", "nan", "positive-infinity", "negative-infinity"),
)
def test_cli_rejects_invalid_cached_candidate_nutrition_without_source_writes(
    user_db, monkeypatch, capsys, candidate_kind, nutrient, invalid_value
):
    original = (
        "chicken breast roasted"
        if candidate_kind == "raw"
        else "unresolved poultry description"
    )
    retrieval_query = "chicken breast roasted"
    cached, _ = _generic_food(retrieval_query)
    if candidate_kind == "semantic":
        cached = replace(
            cached,
            resolution_mode="generic_proxy",
            assumption=(
                "Brand not specified; used USDA generic proxy: "
                "chicken breast roasted."
            ),
        )
    with connect(user_db) as connection:
        repository = FoodRepository(connection)
        repository._cache_food(cached, lookup_query=retrieval_query)
        connection.execute(
            f"UPDATE food_cache SET {nutrient} = ? WHERE lookup_query = ?",
            (invalid_value, retrieval_query),
        )

    candidates = (
        []
        if candidate_kind == "raw"
        else [{"query": retrieval_query, "relation": "same_form"}]
    )
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    original_state = _database_state(user_db)
    original_files = _directory_file_state(user_db.parent)

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(_intent(original, candidates)),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    error = _strict_json_loads(captured.err)["error"]

    assert code == 2
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert error["code"] == "invalid_nutrition"
    assert error["would_write"] is False
    assert error["details"] == {
        "would_write": False,
        "reason": "non_finite_or_negative_nutrition",
        "invalid_nutrients": [nutrient],
    }
    assert _database_state(user_db) == original_state
    assert _directory_file_state(user_db.parent) == original_files


def test_raw_original_safe_resolution_wins_without_trying_semantic_candidates(
    repository, monkeypatch
):
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                "chicken breast roasted",
                [
                    {
                        "query": "fallback chicken",
                        "relation": "generic_fallback",
                        "assumption": "Used a less specific chicken preparation.",
                    }
                ],
            )
        ),
        expected_original="chicken breast roasted",
    )
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")

    def resolve(query, api_key):
        assert query == "chicken breast roasted"
        return _generic_food("chicken breast roasted")

    monkeypatch.setattr(repository.usda_client, "resolve", resolve)
    before = _counts(repository)

    plan = repository.plan_resolution("chicken breast roasted", intent=intent)

    assert plan["retrieval_query"] == "chicken breast roasted"
    assert "candidate_index" not in plan
    assert plan["resolution_mode"] == "generic_proxy"
    assert plan["would_write"] is False
    assert _counts(repository) == before


def test_russian_smoked_chicken_uses_visible_roasted_generic_fallback(
    repository, monkeypatch
):
    original = "курица сырокопченая"
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [
                    {"query": "smoked chicken", "relation": "same_form"},
                    {
                        "query": "chicken breast roasted",
                        "relation": "generic_fallback",
                        "assumption": "Roasted chicken loses the smoked and cured preparation.",
                    },
                ],
            )
        ),
        expected_original=original,
    )
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [])

    def resolve(query, api_key):
        if query == "chicken breast roasted":
            return _generic_food("chicken breast roasted")
        if query == "smoked chicken":
            raise NomnomError(
                "usda_low_confidence",
                "Mixed-meat smoked sausage is below the safe threshold",
                details={"candidate": {"name": "chicken, beef and pork smoked sausage"}},
            )
        raise NomnomError("food_not_found", f"No safe food for {query}")

    monkeypatch.setattr(repository.usda_client, "resolve", resolve)
    before = _counts(repository)

    plan = repository.plan_resolution(original, intent=intent)

    assert plan == {
        "would_write": False,
        "original": original,
        "retrieval_query": "chicken breast roasted",
        "intent_version": 1,
        "candidate_index": 1,
        "relation": "generic_fallback",
        "assumption": "Roasted chicken loses the smoked and cured preparation.",
        "provider_assumption": (
            "Brand not specified; used USDA generic proxy: chicken breast roasted."
        ),
        "provider": "usda",
        "source": "usda",
        "source_id": "171477",
        "provider_type": "Foundation",
        "confidence": 0.9,
        "resolution_mode": "generic_proxy",
        "alternatives": [],
    }
    assert _counts(repository) == before


def test_chicken_pastrami_same_form_route_is_safe_off_proxy(repository, monkeypatch):
    original = "куриная пастрома"
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [{"query": "chicken pastrami", "relation": "same_form"}],
            )
        ),
        expected_original=original,
    )
    off_food, _ = _generic_food(
        "Chicken pastrami — Example Deli",
        source="openfoodfacts",
        source_id="10000003",
    )
    off_food = replace(
        off_food,
        brand="Example Deli",
        categories=("chicken pastrami",),
    )
    monkeypatch.delenv("NOMNOM_USDA_KEY", raising=False)
    monkeypatch.setattr(
        repository.off_client,
        "search",
        lambda query, page_size=5: [off_food] if query == "chicken pastrami" else [],
    )

    plan = repository.plan_resolution(original, intent=intent)

    assert plan["candidate_index"] == 0
    assert plan["relation"] == "same_form"
    assert plan["source"] == "openfoodfacts"
    assert plan["resolution_mode"] == "generic_proxy"


def test_relation_then_provider_quality_order_semantic_plans(repository, monkeypatch):
    original = "описание курицы"
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [
                    {"query": "chicken pastrami", "relation": "same_form"},
                    {"query": "chicken breast roasted", "relation": "same_form"},
                ],
            )
        ),
        expected_original=original,
    )
    off_food, _ = _generic_food(
        "Chicken pastrami",
        source="openfoodfacts",
        source_id="10000003",
    )
    off_food = replace(off_food, categories=("chicken pastrami",))
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setattr(
        repository.off_client,
        "search",
        lambda query, page_size=5: [off_food] if query == "chicken pastrami" else [],
    )

    def resolve(query, api_key):
        if query == "chicken breast roasted":
            return _generic_food("chicken breast roasted", confidence=0.81)
        raise NomnomError("food_not_found", f"No USDA food for {query}")

    monkeypatch.setattr(repository.usda_client, "resolve", resolve)

    plan = repository.plan_resolution(original, intent=intent)

    assert plan["candidate_index"] == 1
    assert plan["source"] == "usda"
    assert plan["confidence"] == 0.81


@pytest.mark.parametrize(
    ("original", "brand_intent"),
    [("0123456789012", False), ("chicken breast 12345", False), ("Acme mystery chicken", False)],
)
def test_original_barcode_sku_or_explicit_brand_cannot_be_bypassed(
    repository, monkeypatch, original, brand_intent
):
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [{"query": "chicken breast roasted", "relation": "same_form"}],
                brand_intent=brand_intent,
            )
        ),
        expected_original=original,
    )
    branded, _ = _generic_food(
        "Different chicken — Acme",
        source="openfoodfacts",
        source_id="10000009",
    )
    branded = replace(branded, brand="Acme", categories=("chicken",))
    monkeypatch.setattr(
        repository.off_client,
        "search",
        lambda query, page_size=5: [branded] if "Acme" in query else [],
    )
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setattr(
        repository.usda_client,
        "resolve",
        lambda query, api_key: _generic_food("chicken breast roasted"),
    )
    before = _counts(repository)

    with pytest.raises(NomnomError) as caught:
        repository.plan_resolution(original, intent=intent)

    assert caught.value.code == "exact_resolution_required"
    assert caught.value.details["would_write"] is False
    assert _counts(repository) == before


def test_all_unsafe_candidates_return_structured_failure_without_writes(
    repository, monkeypatch
):
    original = "курица сырокопченая"
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [{"query": "smoked chicken", "relation": "same_form"}],
            )
        ),
        expected_original=original,
    )
    unsafe, _ = _generic_food(
        "Beef sausage — Example Meat",
        source="openfoodfacts",
        source_id="999",
    )
    unsafe = replace(unsafe, brand="Example Meat", categories=("beef sausages",))
    monkeypatch.delenv("NOMNOM_USDA_KEY", raising=False)
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [unsafe])
    before = _counts(repository)

    with pytest.raises(NomnomError) as caught:
        repository.plan_resolution(original, intent=intent)

    assert caught.value.code == "semantic_resolution_not_found"
    assert caught.value.details["would_write"] is False
    assert caught.value.as_dict()["error"]["would_write"] is False
    assert caught.value.details["failures"][0]["candidate_index"] == 0
    assert _counts(repository) == before


def test_weak_mocked_usda_candidate_is_rejected_at_planning_boundary(
    repository, monkeypatch
):
    original = "курица сырокопченая"
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [{"query": "smoked chicken", "relation": "same_form"}],
            )
        ),
        expected_original=original,
    )
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.setattr(
        repository.usda_client,
        "resolve",
        lambda query, api_key: _generic_food(
            "chicken beef pork smoked sausage", confidence=0.77
        ),
    )

    with pytest.raises(NomnomError) as caught:
        repository.plan_resolution(original, intent=intent)

    assert caught.value.code == "semantic_resolution_not_found"
    assert caught.value.details["failures"][0]["error"]["code"] == (
        "provider_low_confidence"
    )


def test_brand_intent_rejects_raw_generic_resolution(repository, monkeypatch):
    original = "special chicken"
    intent = parse_resolution_intent(
        json.dumps(_intent(original, [], brand_intent=True)),
        expected_original=original,
    )
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.setattr(
        repository.usda_client,
        "resolve",
        lambda query, api_key: _generic_food("special chicken"),
    )

    with pytest.raises(NomnomError) as caught:
        repository.plan_resolution(original, intent=intent)

    assert caught.value.code == "exact_resolution_required"


def test_cli_resolve_outputs_plan_and_never_changes_database(
    user_db, monkeypatch, capsys
):
    original = "курица сырокопченая"
    payload = _intent(
        original,
        [
            {
                "query": "chicken breast roasted",
                "relation": "generic_fallback",
                "assumption": "Roasted chicken loses the smoked preparation.",
            }
        ],
    )
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setattr("nomnomcli.off.OpenFoodFactsClient.search", lambda *args, **kwargs: [])

    def resolve(client, query, api_key):
        if query == "chicken breast roasted":
            return _generic_food("chicken breast roasted")
        raise NomnomError("food_not_found", f"No USDA food for {query}")

    monkeypatch.setattr("nomnomcli.usda.USDAClient.resolve", resolve)
    with connect(user_db) as connection:
        before = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("food_cache", "log_entries", "food_aliases", "recipes")
        }

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(payload),
            "--json",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert code == 0
    assert result["would_write"] is False
    assert result["original"] == original
    with connect(user_db) as connection:
        after = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("food_cache", "log_entries", "food_aliases", "recipes")
        }
    assert after == before


@pytest.mark.parametrize("database_kind", ["empty", "v1", "v2"])
def test_cli_resolve_uses_isolated_migrated_copy_for_existing_databases(
    tmp_path, monkeypatch, capsys, database_kind
):
    database = tmp_path / f"{database_kind}.sqlite3"
    if database_kind == "empty":
        database.touch()
    else:
        _create_legacy_database(database, int(database_kind[1:]))
    original_state = _database_state(database)
    original = "chicken breast roasted"
    payload = _intent(original, [])
    monkeypatch.setenv("NOMNOM_DB_PATH", str(database))
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.setattr(
        "nomnomcli.usda.USDAClient.resolve",
        lambda client, query, api_key: _generic_food(query),
    )

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(payload),
            "--json",
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["would_write"] is False
    assert output["original"] == original
    assert _database_state(database) == original_state


@pytest.mark.parametrize("remove_shm", [True, False], ids=["absent-shm", "existing-shm"])
def test_cli_resolve_reads_pending_wal_without_creating_source_sidecars(
    tmp_path, monkeypatch, capsys, remove_shm
):
    database = tmp_path / "wal-source.sqlite3"
    original = "Pending WAL chicken"
    with connect(database):
        pass
    original_directory_mode = tmp_path.stat().st_mode
    try:
        subprocess.run(
            [
                sys.executable,
                "-c",
                """
import os
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
connection.execute(
    "INSERT INTO food_cache "
    "(name, kcal, protein, fat, carbs, source, lookup_query, "
    "resolution_mode, source_id, provenance) "
    "VALUES (?, 165, 31, 3.6, 1, 'user', ?, "
    "'exact_product', 'pending-wal-pin', 'user')",
    (sys.argv[2], sys.argv[2]),
)
connection.commit()
os._exit(0)
""",
                str(database),
                original,
            ],
            check=True,
        )

        wal_path = tmp_path / f"{database.name}-wal"
        shm_path = tmp_path / f"{database.name}-shm"
        assert wal_path.exists()
        with sqlite3.connect(
            f"{database.resolve().as_uri()}?mode=ro&immutable=1", uri=True
        ) as main_only:
            assert (
                main_only.execute(
                    "SELECT count(*) FROM food_cache WHERE name = ?", (original,)
                ).fetchone()[0]
                == 0
            )
        if remove_shm:
            try:
                shm_path.unlink()
            except PermissionError:
                pytest.skip("platform cannot unlink an open SQLite SHM file")
            assert not shm_path.exists()
        else:
            assert shm_path.exists()

        original_files = _directory_file_state(tmp_path)
        tmp_path.chmod(0o555)
        monkeypatch.setenv("NOMNOM_DB_PATH", str(database))
        monkeypatch.setenv("NOMNOM_OFFLINE", "1")

        code = main(
            [
                "resolve",
                "--food",
                original,
                "--intent-json",
                json.dumps(_intent(original, [])),
                "--json",
            ]
        )
        output = json.loads(capsys.readouterr().out)

        assert code == 0
        assert output["would_write"] is False
        assert output["retrieval_query"] == original
        assert output["source_id"] == "pending-wal-pin"
        assert output["resolution_mode"] == "exact_product"
        assert _directory_file_state(tmp_path) == original_files
        assert shm_path.exists() is not remove_shm
    finally:
        tmp_path.chmod(original_directory_mode)


def test_cli_resolve_recovers_hot_rollback_journal_only_in_private_snapshot(
    tmp_path, monkeypatch, capsys
):
    database = tmp_path / "rollback-source.sqlite3"
    original = "Committed rollback chicken"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA page_size = 512")
        connection.execute("VACUUM")
    with connect(database) as connection:
        connection.execute(
            """INSERT INTO food_cache
            (name, kcal, protein, fat, carbs, source, lookup_query,
             resolution_mode, source_id, provenance)
            VALUES (?, 165, 31, 3.6, 1, 'user', ?,
                    'exact_product', 'committed-rollback-pin', 'user')""",
            (original, original),
        )
        connection.execute(
            "CREATE TABLE rollback_spill (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO rollback_spill (id, payload) VALUES (?, ?)",
            ((index, f"committed-{index:04d}-" + "c" * 1800) for index in range(300)),
        )

    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
assert connection.execute("PRAGMA journal_mode = DELETE").fetchone()[0] == "delete"
connection.execute("PRAGMA synchronous = FULL")
connection.execute("PRAGMA cache_size = 5")
connection.execute("PRAGMA cache_spill = ON")
connection.execute("BEGIN IMMEDIATE")
connection.execute(
    "UPDATE food_cache SET source_id = 'uncommitted-rollback-pin' WHERE name = ?",
    (sys.argv[2],),
)
connection.execute(
    "UPDATE rollback_spill SET payload = ? || printf('%04d', id)",
    ("dirty-" + "d" * 1800,),
)
assert connection.in_transaction
os._exit(0)
""",
            str(database),
            original,
        ],
        check=True,
    )

    journal_path = tmp_path / f"{database.name}-journal"
    assert journal_path.exists()
    journal_bytes = journal_path.read_bytes()
    assert len(journal_bytes) > 512
    assert any(journal_bytes[:28])
    with sqlite3.connect(
        f"{database.resolve().as_uri()}?mode=ro&immutable=1", uri=True
    ) as dirty_main:
        assert (
            dirty_main.execute(
                "SELECT source_id FROM food_cache WHERE name = ?", (original,)
            ).fetchone()[0]
            == "uncommitted-rollback-pin"
        )

    original_files = _directory_file_state(tmp_path)
    original_entries = sorted(path.name for path in tmp_path.iterdir())
    original_directory_mode = tmp_path.stat().st_mode
    try:
        tmp_path.chmod(0o555)
        monkeypatch.setenv("NOMNOM_DB_PATH", str(database))
        monkeypatch.setenv("NOMNOM_OFFLINE", "1")

        code = main(
            [
                "resolve",
                "--food",
                original,
                "--intent-json",
                json.dumps(_intent(original, [])),
                "--json",
            ]
        )
        output = json.loads(capsys.readouterr().out)

        assert code == 0
        assert output["would_write"] is False
        assert output["retrieval_query"] == original
        assert output["source_id"] == "committed-rollback-pin"
        assert output["resolution_mode"] == "exact_product"
        assert sorted(path.name for path in tmp_path.iterdir()) == original_entries
        assert _directory_file_state(tmp_path) == original_files
    finally:
        tmp_path.chmod(original_directory_mode)


@pytest.mark.parametrize("journal_mode", ["MEMORY", "OFF"])
def test_cli_resolve_refuses_dirty_spilled_journal_less_writer_without_source_changes(
    tmp_path, monkeypatch, capsys, journal_mode
):
    database = tmp_path / f"{journal_mode.lower()}-source.sqlite3"
    original = f"Committed {journal_mode} chicken"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA page_size = 512")
        connection.execute("VACUUM")
    with connect(database) as connection:
        connection.execute(
            """INSERT INTO food_cache
            (name, kcal, protein, fat, carbs, source, lookup_query,
             resolution_mode, source_id, provenance)
            VALUES (?, 165, 31, 3.6, 1, 'user', ?,
                    'exact_product', 'committed-pin', 'user')""",
            (original, original),
        )
        connection.execute(
            "CREATE TABLE spill_pages (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO spill_pages (id, payload) VALUES (?, ?)",
            ((index, f"committed-{index:04d}-" + "c" * 1800) for index in range(300)),
        )

    writer = subprocess.Popen(
        [
            sys.executable,
            "-c",
            """
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
mode = sys.argv[3]
assert connection.execute(f"PRAGMA journal_mode = {mode}").fetchone()[0] == mode.lower()
connection.execute("PRAGMA synchronous = OFF")
connection.execute("PRAGMA cache_size = 5")
connection.execute("PRAGMA cache_spill = ON")
connection.execute("BEGIN IMMEDIATE")
connection.execute(
    "UPDATE food_cache SET source_id = 'uncommitted-pin' WHERE name = ?",
    (sys.argv[2],),
)
connection.execute(
    "UPDATE spill_pages SET payload = ? || printf('%04d', id)",
    ("dirty-" + "d" * 1800,),
)
assert connection.in_transaction
print("ready", flush=True)
sys.stdin.readline()
connection.rollback()
connection.close()
""",
            str(database),
            original,
            journal_mode,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert writer.stdout is not None
        assert writer.stdout.readline().strip() == "ready"
        with sqlite3.connect(
            f"{database.resolve().as_uri()}?mode=ro&immutable=1", uri=True
        ) as dirty_main:
            assert (
                dirty_main.execute(
                    "SELECT source_id FROM food_cache WHERE name = ?", (original,)
                ).fetchone()[0]
                == "uncommitted-pin"
            )
        assert not Path(f"{database}-journal").exists()
        original_files = _directory_file_state(tmp_path)
        original_fingerprint = database_module._source_snapshot_fingerprint(database)
        monkeypatch.setenv("NOMNOM_DB_PATH", str(database))
        monkeypatch.setenv("NOMNOM_OFFLINE", "1")

        code = main(
            [
                "resolve",
                "--food",
                original,
                "--intent-json",
                json.dumps(_intent(original, [])),
                "--json",
            ]
        )
        error = json.loads(capsys.readouterr().err)

        assert code == 2
        assert error["error"]["code"] == "database_snapshot_busy"
        assert error["error"]["would_write"] is False
        assert error["error"]["details"]["lock_target"] == "main"
        assert _directory_file_state(tmp_path) == original_files
        assert database_module._source_snapshot_fingerprint(database) == original_fingerprint
    finally:
        if writer.poll() is None:
            assert writer.stdin is not None
            writer.stdin.write("finish\n")
            writer.stdin.flush()
        return_code = writer.wait(timeout=10)
        if return_code != 0:
            assert writer.stderr is not None
            pytest.fail(writer.stderr.read())


def test_cli_snapshot_lock_unavailable_is_structured_and_does_not_copy(
    user_db, monkeypatch, capsys
):
    with connect(user_db):
        pass
    before = _directory_file_state(user_db.parent)
    monkeypatch.setattr(database_module, "_ofd_locks_supported", lambda: False)
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")

    code = main(
        [
            "resolve",
            "--food",
            "Safe chicken",
            "--intent-json",
            json.dumps(_intent("Safe chicken", [])),
            "--json",
        ]
    )
    error = json.loads(capsys.readouterr().err)

    assert code == 2
    assert error["error"]["code"] == "database_snapshot_lock_unavailable"
    assert error["error"]["would_write"] is False
    assert _directory_file_state(user_db.parent) == before


@pytest.mark.parametrize(
    ("platform", "ofd_supported"),
    [("darwin", True), ("linux", False)],
    ids=["non-linux", "missing-ofd-locking"],
)
def test_cli_snapshot_platform_lock_capability_is_classified_without_writes(
    user_db, monkeypatch, capsys, platform, ofd_supported
):
    with connect(user_db):
        pass
    before = _directory_file_state(user_db.parent)
    monkeypatch.setattr(database_module.sys, "platform", platform)
    monkeypatch.setattr(
        database_module, "_ofd_locks_supported", lambda: ofd_supported
    )
    monkeypatch.setattr(
        database_module,
        "_copy_stable_database_snapshot",
        lambda *args, **kwargs: pytest.fail(
            "snapshot copy started without platform lock capability"
        ),
    )
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")

    code = main(
        [
            "resolve",
            "--food",
            "Safe chicken",
            "--intent-json",
            json.dumps(_intent("Safe chicken", [])),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    error = _strict_json_loads(captured.err)

    assert code == 2
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert error["error"]["code"] == "database_snapshot_lock_unavailable"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"]["would_write"] is False
    assert _directory_file_state(user_db.parent) == before


def test_cli_snapshot_missing_linux_noatime_is_classified_without_writes(
    user_db, monkeypatch, capsys
):
    with connect(user_db):
        pass
    before = _directory_file_state(user_db.parent)
    monkeypatch.setattr(database_module.sys, "platform", "linux")
    monkeypatch.setattr(database_module, "_ofd_locks_supported", lambda: True)
    monkeypatch.delattr(database_module.os, "O_NOATIME")
    monkeypatch.setattr(
        database_module,
        "_copy_stable_database_snapshot",
        lambda *args, **kwargs: pytest.fail(
            "snapshot copy started without O_NOATIME capability"
        ),
    )
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")

    code = main(
        [
            "resolve",
            "--food",
            "Safe chicken",
            "--intent-json",
            json.dumps(_intent("Safe chicken", [])),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    error = _strict_json_loads(captured.err)

    assert code == 2
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert error["error"]["code"] == "database_snapshot_noatime_unavailable"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"]["would_write"] is False
    assert _directory_file_state(user_db.parent) == before


def test_cli_fifo_database_is_rejected_without_hanging_or_source_changes(tmp_path):
    database = tmp_path / "fifo-source.sqlite3"
    os.mkfifo(database)
    before = _fifo_identity(database)

    completed = _run_resolve_cli(database, "FIFO chicken")
    error = _strict_json_loads(completed.stderr)["error"]

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "Traceback" not in completed.stderr
    assert error["code"] == "database_snapshot_unsafe_file_type"
    assert error["would_write"] is False
    assert error["details"]["would_write"] is False
    assert error["details"]["snapshot_target"] == "main"
    assert error["details"]["file_type"] == "fifo"
    assert "regular file" in error["details"]["action"]
    assert _fifo_identity(database) == before
    assert {child.name for child in tmp_path.iterdir()} == {database.name}


def test_cli_invalid_regular_database_is_structured_without_source_changes(tmp_path):
    database = tmp_path / "invalid-source.sqlite3"
    content = b"not a SQLite database\n\x00invalid source bytes"
    database.write_bytes(content)
    initial = database.stat()
    stale_atime_ns = 946_684_800_000_000_000
    os.utime(database, ns=(stale_atime_ns, initial.st_mtime_ns))
    before = database.stat()
    before_metadata = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_nlink,
        before.st_uid,
        before.st_gid,
        before.st_size,
        before.st_atime_ns,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )

    completed = _run_resolve_cli(database, "Invalid source chicken")
    error = _strict_json_loads(completed.stderr)["error"]
    after = database.stat()

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "Traceback" not in completed.stderr
    assert error["code"] == "database_snapshot_invalid"
    assert error["would_write"] is False
    assert error["details"]["would_write"] is False
    assert error["details"]["snapshot_target"] == "main"
    assert "valid SQLite database" in error["details"]["action"]
    assert (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_nlink,
        after.st_uid,
        after.st_gid,
        after.st_size,
        after.st_atime_ns,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ) == before_metadata
    assert database.read_bytes() == content
    assert {child.name for child in tmp_path.iterdir()} == {database.name}


@pytest.mark.parametrize(
    "damage",
    ["DROP TABLE food_aliases", "DROP INDEX idx_log_entries_logged_at"],
    ids=["missing-food-aliases", "missing-required-index"],
)
def test_cli_incomplete_current_schema_is_structured_without_source_changes(
    tmp_path, damage
):
    database = tmp_path / "incomplete-v4.sqlite3"
    with connect(database) as connection:
        connection.execute(damage)
    before = _database_state(database)
    before_files = _directory_file_state(tmp_path)

    completed = _run_resolve_cli(database, "Incomplete schema chicken")
    error = _strict_json_loads(completed.stderr)["error"]

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "Traceback" not in completed.stderr
    assert error["code"] == "database_snapshot_invalid"
    assert error["would_write"] is False
    assert error["details"]["would_write"] is False
    assert error["details"]["snapshot_target"] == "main"
    assert _database_state(database) == before
    assert _directory_file_state(tmp_path) == before_files


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_cli_fifo_snapshot_sidecar_is_rejected_without_hanging_or_source_changes(
    tmp_path, suffix
):
    database = tmp_path / "regular-source.sqlite3"
    with connect(database):
        pass
    sidecar = Path(f"{database}{suffix}")
    os.mkfifo(sidecar)
    database_content = database.read_bytes()
    sidecar_identity = _fifo_identity(sidecar)

    completed = _run_resolve_cli(database, "Sidecar FIFO chicken")
    error = _strict_json_loads(completed.stderr)["error"]

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "Traceback" not in completed.stderr
    assert error["code"] == "database_snapshot_unsafe_file_type"
    assert error["would_write"] is False
    assert error["details"]["would_write"] is False
    assert error["details"]["snapshot_target"] == suffix.removeprefix("-")
    assert error["details"]["file_type"] == "fifo"
    assert "regular file" in error["details"]["action"]
    assert database.read_bytes() == database_content
    assert _fifo_identity(sidecar) == sidecar_identity
    assert {child.name for child in tmp_path.iterdir()} == {
        database.name,
        sidecar.name,
    }


@pytest.mark.parametrize("suffix", ["-wal", "-journal"])
def test_cli_unreadable_snapshot_sidecar_is_structured_without_source_writes(
    user_db, monkeypatch, capsys, suffix
):
    with connect(user_db):
        pass
    sidecar = Path(f"{user_db}{suffix}")
    sidecar.write_bytes(b"existing SQLite sidecar")
    before = _directory_file_state(user_db.parent)
    real_open = database_module.os.open

    def refuse_sidecar_read(path, flags, *args, **kwargs):
        if path == sidecar.name and kwargs.get("dir_fd") is not None:
            assert flags & database_module.os.O_NOATIME
            raise PermissionError(errno.EACCES, "sidecar is unreadable", path)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(database_module.os, "open", refuse_sidecar_read)
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")

    code = main(
        [
            "resolve",
            "--food",
            "Safe chicken",
            "--intent-json",
            json.dumps(_intent("Safe chicken", [])),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    error = _strict_json_loads(captured.err)

    assert code == 2
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert error["error"]["code"] == "database_snapshot_unreadable"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"]["snapshot_target"] == suffix.removeprefix("-")
    assert error["error"]["details"]["os_error"] == errno.EACCES
    assert _directory_file_state(user_db.parent) == before


def test_cli_resolve_preserves_stale_source_atime_mtime_and_content(
    tmp_path, monkeypatch, capsys
):
    database = tmp_path / "no-atime-source.sqlite3"
    original = "No-atime chicken"
    with connect(database):
        pass

    writer = sqlite3.connect(database)
    try:
        assert writer.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        writer.execute(
            "INSERT INTO food_cache "
            "(name, kcal, protein, fat, carbs, source, lookup_query, "
            "resolution_mode, source_id, provenance) "
            "VALUES (?, 165, 31, 3.6, 1, 'user', ?, "
            "'exact_product', 'no-atime-pin', 'user')",
            (original, original),
        )
        writer.commit()

        source_paths = [database, Path(f"{database}-wal"), Path(f"{database}-shm")]
        assert all(path.exists() for path in source_paths)
        noatime = getattr(database_module.os, "O_NOATIME", None)
        if noatime is None:
            pytest.skip("runtime does not expose Linux O_NOATIME")
        for path in source_paths:
            try:
                descriptor = database_module.os.open(
                    path,
                    database_module.os.O_RDONLY | noatime,
                )
            except OSError as error:
                if error.errno in {
                    errno.EPERM,
                    errno.EINVAL,
                    errno.EOPNOTSUPP,
                    errno.ENOTSUP,
                }:
                    pytest.skip(f"filesystem does not support O_NOATIME: {error}")
                raise
            else:
                database_module.os.close(descriptor)

        original_content = {path: path.read_bytes() for path in source_paths}
        stale_atime_ns = 946_684_800_000_000_000
        for path in source_paths:
            stat = path.stat()
            assert stale_atime_ns < stat.st_mtime_ns
            database_module.os.utime(
                path,
                ns=(stale_atime_ns, stat.st_mtime_ns),
            )
        original_metadata = {
            path: (path.stat().st_atime_ns, path.stat().st_mtime_ns)
            for path in source_paths
        }

        monkeypatch.setenv("NOMNOM_DB_PATH", str(database))
        monkeypatch.setenv("NOMNOM_OFFLINE", "1")
        code = main(
            [
                "resolve",
                "--food",
                original,
                "--intent-json",
                json.dumps(_intent(original, [])),
                "--json",
            ]
        )
        output = _strict_json_loads(capsys.readouterr().out)

        assert code == 0
        assert output["would_write"] is False
        assert output["source_id"] == "no-atime-pin"
        assert {
            path: (path.stat().st_atime_ns, path.stat().st_mtime_ns)
            for path in source_paths
        } == original_metadata
        assert {path: path.read_bytes() for path in source_paths} == original_content
    finally:
        writer.close()


@pytest.mark.parametrize("symlink_kind", ["final", "parent"])
def test_cli_resolve_rejects_stale_atime_symlink_without_metadata_or_source_changes(
    tmp_path, monkeypatch, capsys, symlink_kind
):
    source_directory = tmp_path / "source"
    source_directory.mkdir()
    database = source_directory / "safe.sqlite3"
    original = "Symlink-safe chicken"
    with connect(database) as connection:
        pinned = Food(
            name=original,
            kcal=165,
            protein=31,
            fat=3.6,
            carbs=1,
            source="user",
            resolution_mode="exact_product",
            source_id="symlink-safe-pin",
            provenance="user",
        )
        FoodRepository(connection)._cache_food(pinned, lookup_query=original)

    if symlink_kind == "final":
        supplied_path = tmp_path / "supplied.sqlite3"
        supplied_path.symlink_to(database)
        symlink = supplied_path
        snapshot_target = "main"
    else:
        linked_directory = tmp_path / "linked-source"
        linked_directory.symlink_to(source_directory, target_is_directory=True)
        supplied_path = linked_directory / database.name
        symlink = linked_directory
        snapshot_target = "parent"

    link_content = os.readlink(symlink)
    source_content = database.read_bytes()
    stale_atime_ns = 946_684_800_000_000_000
    initial = os.lstat(symlink)
    os.utime(
        symlink,
        ns=(stale_atime_ns, initial.st_mtime_ns),
        follow_symlinks=False,
    )
    before = os.lstat(symlink)
    before_metadata = (
        before.st_atime_ns,
        before.st_mtime_ns,
        before.st_size,
        before.st_ino,
    )

    monkeypatch.setenv("NOMNOM_DB_PATH", str(supplied_path))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(_intent(original, [])),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    error = _strict_json_loads(captured.err)

    after = os.lstat(symlink)
    assert code == 2
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert error["error"]["code"] == "database_snapshot_unsafe_path"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"]["snapshot_target"] == snapshot_target
    assert (
        after.st_atime_ns,
        after.st_mtime_ns,
        after.st_size,
        after.st_ino,
    ) == before_metadata
    assert database.read_bytes() == source_content
    assert os.readlink(symlink) == link_content


def test_cli_resolve_rejects_stale_atime_sidecar_symlink_without_changes(
    tmp_path, monkeypatch, capsys
):
    database = tmp_path / "safe.sqlite3"
    with connect(database):
        pass
    sidecar_target = tmp_path / "foreign-wal"
    sidecar_target.write_bytes(b"not a SQLite WAL")
    sidecar = Path(f"{database}-wal")
    sidecar.symlink_to(sidecar_target)
    link_content = os.readlink(sidecar)
    source_content = database.read_bytes()
    target_content = sidecar_target.read_bytes()
    stale_atime_ns = 946_684_800_000_000_000
    initial = os.lstat(sidecar)
    os.utime(
        sidecar,
        ns=(stale_atime_ns, initial.st_mtime_ns),
        follow_symlinks=False,
    )
    before = os.lstat(sidecar)
    before_metadata = (before.st_atime_ns, before.st_mtime_ns, before.st_size)

    monkeypatch.setenv("NOMNOM_DB_PATH", str(database))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    code = main(
        [
            "resolve",
            "--food",
            "Safe chicken",
            "--intent-json",
            json.dumps(_intent("Safe chicken", [])),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    error = _strict_json_loads(captured.err)

    after = os.lstat(sidecar)
    assert code == 2
    assert captured.out == ""
    assert error["error"]["code"] == "database_snapshot_unsafe_path"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"]["snapshot_target"] == "wal"
    assert (after.st_atime_ns, after.st_mtime_ns, after.st_size) == before_metadata
    assert database.read_bytes() == source_content
    assert sidecar_target.read_bytes() == target_content
    assert os.readlink(sidecar) == link_content


@pytest.mark.parametrize(
    ("suffix", "snapshot_target"),
    [("", "main"), ("-wal", "wal")],
)
@pytest.mark.parametrize("open_errno", [errno.EPERM, errno.EOPNOTSUPP])
def test_cli_snapshot_noatime_unavailable_is_structured_and_does_not_copy(
    user_db, monkeypatch, capsys, open_errno, suffix, snapshot_target
):
    with connect(user_db):
        pass
    denied_path = Path(f"{user_db}{suffix}")
    if suffix:
        denied_path.write_bytes(b"existing SQLite sidecar")
    before = _directory_file_state(user_db.parent)
    real_open = database_module.os.open
    source_open_flags = []

    def refuse_noatime(path, flags, *args, **kwargs):
        if path == denied_path.name and kwargs.get("dir_fd") is not None:
            source_open_flags.append(flags)
            if flags & getattr(database_module.os, "O_NOATIME", 0):
                raise OSError(open_errno, "O_NOATIME unavailable", path)
        return real_open(path, flags, *args, **kwargs)

    def reject_copy(*args, **kwargs):
        pytest.fail("snapshot copy started after O_NOATIME refusal")

    monkeypatch.setattr(database_module.os, "open", refuse_noatime)
    monkeypatch.setattr(database_module, "_copy_open_file", reject_copy)
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")

    code = main(
        [
            "resolve",
            "--food",
            "Safe chicken",
            "--intent-json",
            json.dumps(_intent("Safe chicken", [])),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    error = _strict_json_loads(captured.err)

    assert code == 2
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert error["error"]["code"] == "database_snapshot_noatime_unavailable"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"]["snapshot_target"] == snapshot_target
    assert error["error"]["details"]["os_error"] == open_errno
    assert "owner" in error["error"]["details"]["action"]
    assert source_open_flags
    assert all(
        flags & database_module.os.O_NOATIME for flags in source_open_flags
    )
    assert _directory_file_state(user_db.parent) == before


def test_cli_resolve_rejects_legacy_non_exact_sku_cache_without_source_writes(
    tmp_path, monkeypatch, capsys
):
    database = tmp_path / "legacy-sku.sqlite3"
    _create_legacy_sku_cache_database(database)
    original_state = _database_state(database)
    original_files = {
        path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()
    }
    original = "chicken 12345"
    monkeypatch.setenv("NOMNOM_DB_PATH", str(database))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(_intent(original, [])),
            "--json",
        ]
    )
    error = json.loads(capsys.readouterr().err)

    assert code == 2
    assert error["error"]["code"] == "exact_resolution_required"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"]["original"] == original
    assert _database_state(database) == original_state
    assert {
        path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()
    } == original_files


@pytest.mark.parametrize(
    "original",
    [
        "курица SKU12345",
        "SKUABC123",
        "курица SKU 12345",
        "курица SKU: ABC-123",
        "курица SKU: ABC/123",
        "курица АБ12345",
    ],
)
def test_cli_alphanumeric_sku_refuses_semantic_candidate_without_source_writes(
    user_db, monkeypatch, capsys, original
):
    semantic_query = "chicken"
    cached, _ = _generic_food(semantic_query)
    cached = replace(
        cached,
        resolution_mode="generic_proxy",
        assumption="Brand not specified; used USDA generic proxy: chicken.",
    )
    with connect(user_db) as connection:
        FoodRepository(connection)._cache_food(cached, lookup_query=semantic_query)

    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    original_state = _database_state(user_db)
    original_files = _directory_file_state(user_db.parent)

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(
                _intent(
                    original,
                    [{"query": semantic_query, "relation": "same_form"}],
                    brand_intent=False,
                )
            ),
            "--json",
        ]
    )

    assert code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "exact_resolution_required"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"]["original"] == original
    assert _database_state(user_db) == original_state
    assert _directory_file_state(user_db.parent) == original_files


def test_cli_snapshot_lock_blocks_wal_checkpoint_during_copy(
    tmp_path, monkeypatch, capsys
):
    database = tmp_path / "checkpoint-source.sqlite3"
    original = "Checkpointed chicken"
    with connect(database):
        pass

    writer = sqlite3.connect(database)
    assert writer.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
    writer.execute(
        "INSERT INTO food_cache "
        "(name, kcal, protein, fat, carbs, source, lookup_query, "
        "resolution_mode, source_id, provenance) "
        "VALUES (?, 165, 31, 3.6, 1, 'user', ?, "
        "'exact_product', 'checkpoint-pin', 'user')",
        (original, original),
    )
    writer.commit()
    wal_path = tmp_path / f"{database.name}-wal"
    assert wal_path.exists()
    with sqlite3.connect(
        f"{database.resolve().as_uri()}?mode=ro&immutable=1", uri=True
    ) as main_only:
        assert (
            main_only.execute(
                "SELECT count(*) FROM food_cache WHERE name = ?", (original,)
            ).fetchone()[0]
            == 0
        )

    original_files = _directory_file_state(tmp_path)
    source_inode = database.stat().st_ino
    real_copy_open_file = database_module._copy_open_file
    main_copy_count = 0
    checkpoint_result = None

    def checkpoint_during_locked_copy(source_descriptor, destination):
        nonlocal main_copy_count, checkpoint_result
        result = real_copy_open_file(source_descriptor, destination)
        if database_module.os.fstat(source_descriptor).st_ino == source_inode:
            main_copy_count += 1
            if main_copy_count == 1:
                checkpoint_result = writer.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                ).fetchone()
        return result

    monkeypatch.setattr(database_module, "_copy_open_file", checkpoint_during_locked_copy)
    monkeypatch.setenv("NOMNOM_DB_PATH", str(database))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")

    try:
        code = main(
            [
                "resolve",
                "--food",
                original,
                "--intent-json",
                json.dumps(_intent(original, [])),
                "--json",
            ]
        )
        output = json.loads(capsys.readouterr().out)

        assert code == 0
        assert output["would_write"] is False
        assert output["source_id"] == "checkpoint-pin"
        assert main_copy_count == 1
        assert checkpoint_result is not None
        assert checkpoint_result[0] == 1
        assert _directory_file_state(tmp_path) == original_files
    finally:
        writer.close()


def test_cli_snapshot_unstable_returns_structured_refusal_without_source_writes(
    user_db, monkeypatch, capsys
):
    original = "Stable source chicken"
    with connect(user_db):
        pass
    before = _directory_file_state(user_db.parent)
    real_fingerprint = database_module._source_snapshot_fingerprint
    fingerprint_call = 0

    def permanently_changing_fingerprint(source_path):
        nonlocal fingerprint_call
        fingerprint_call += 1
        fingerprint = real_fingerprint(source_path)
        main = fingerprint[""]
        assert main is not None
        fingerprint[""] = (*main[:-1], main[-1] + fingerprint_call)
        return fingerprint

    monkeypatch.setattr(
        database_module,
        "_source_snapshot_fingerprint",
        permanently_changing_fingerprint,
    )
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(_intent(original, [])),
            "--json",
        ]
    )
    error = json.loads(capsys.readouterr().err)

    assert code == 2
    assert error["error"]["code"] == "database_snapshot_unstable"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"]["attempts"] == 3
    assert fingerprint_call == 6
    assert _directory_file_state(user_db.parent) == before


@pytest.mark.parametrize(
    "original",
    [
        "курица SKU12345",
        "курица SKU 12345",
        "курица SKU ABC123",
        "курица SKU:12345",
        "курица SKU: ABC-123",
        "курица SKU : ABC_123",
        "курица SKU: ABC/123",
        "курица ABC-12345",
        "курица ABC_12345",
        "курица АБ12345",
    ],
)
def test_alphanumeric_sku_variants_require_exact_resolution(
    repository, original
):
    semantic_query = "chicken"
    cached, _ = _generic_food(semantic_query)
    cached = replace(
        cached,
        resolution_mode="generic_proxy",
        assumption="Brand not specified; used USDA generic proxy: chicken.",
    )
    repository._cache_food(cached, lookup_query=semantic_query)
    repository.user_connection.commit()
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [{"query": semantic_query, "relation": "same_form"}],
                brand_intent=False,
            )
        ),
        expected_original=original,
    )
    before = _counts(repository)

    with pytest.raises(NomnomError) as caught:
        repository.plan_resolution(original, intent=intent, allow_remote=False)

    assert caught.value.code == "exact_resolution_required"
    assert caught.value.details["would_write"] is False
    assert _counts(repository) == before


@pytest.mark.parametrize(
    ("original", "semantic_query"),
    [
        ("milk 3%", "dairy drink"),
        ("3 eggs", "omelette"),
        ("vitamin B12", "cobalamin"),
        ("vitamin D3", "cholecalciferol"),
        ("soup, 3 portions", "broth"),
        ("SKU chicken", "poultry"),
        ("chicken SKU", "poultry"),
        ("SKU: chicken", "poultry"),
    ],
)
def test_ordinary_food_expression_is_not_treated_as_sku(
    repository, original, semantic_query
):
    cached, _ = _generic_food(semantic_query)
    cached = replace(
        cached,
        resolution_mode="generic_proxy",
        assumption=f"Used declared semantic food candidate: {semantic_query}.",
    )
    repository._cache_food(cached, lookup_query=semantic_query)
    repository.user_connection.commit()
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [{"query": semantic_query, "relation": "lexical_equivalent"}],
                brand_intent=False,
            )
        ),
        expected_original=original,
    )
    before = _counts(repository)

    plan = repository.plan_resolution(original, intent=intent, allow_remote=False)

    assert plan["retrieval_query"] == semantic_query
    assert plan["resolution_mode"] == "generic_proxy"
    assert plan["would_write"] is False
    assert _counts(repository) == before


def test_cli_cross_language_numeric_overlap_uses_visible_proxy_without_writes(
    user_db, monkeypatch, capsys
):
    original = "молоко 3%"
    semantic_query = "milk 3%"
    cached, _ = _generic_food(semantic_query, source_id="171265")
    cached = replace(
        cached,
        resolution_mode="generic_proxy",
        assumption="Brand not specified; used USDA generic proxy: milk 3%.",
    )
    with connect(user_db) as connection:
        FoodRepository(connection)._cache_food(cached, lookup_query=semantic_query)

    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    original_state = _database_state(user_db)
    original_files = _directory_file_state(user_db.parent)

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(
                _intent(
                    original,
                    [{"query": semantic_query, "relation": "lexical_equivalent"}],
                    brand_intent=False,
                )
            ),
            "--json",
        ]
    )
    plan = json.loads(capsys.readouterr().out)

    assert code == 0
    assert plan["would_write"] is False
    assert plan["original"] == original
    assert plan["retrieval_query"] == semantic_query
    assert plan["candidate_index"] == 0
    assert plan["relation"] == "lexical_equivalent"
    assert plan["provider_assumption"] == (
        "Brand not specified; used USDA generic proxy: milk 3%."
    )
    assert plan["provider"] == "usda"
    assert plan["source"] == "usda"
    assert plan["source_id"] == "171265"
    assert plan["resolution_mode"] == "generic_proxy"
    assert _database_state(user_db) == original_state
    assert _directory_file_state(user_db.parent) == original_files


def test_cli_raw_cache_brand_requires_exact_resolution_without_source_writes(
    tmp_path, monkeypatch, capsys
):
    database = tmp_path / "legacy-brand.sqlite3"
    _create_legacy_brand_cache_database(database)
    original_state = _database_state(database)
    original_files = _directory_file_state(tmp_path)
    original = "Acme chicken"
    monkeypatch.setenv("NOMNOM_DB_PATH", str(database))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(
                _intent(
                    original,
                    [{"query": "tofu", "relation": "same_form"}],
                    brand_intent=False,
                )
            ),
            "--json",
        ]
    )
    error = json.loads(capsys.readouterr().err)

    assert code == 2
    assert error["error"]["code"] == "exact_resolution_required"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"]["original"] == original
    assert _database_state(database) == original_state
    assert _directory_file_state(tmp_path) == original_files


def test_partial_cached_exact_matching_brand_requires_exact_resolution(repository):
    original = "Acme"
    partial = Food(
        name="Acme chicken",
        kcal=165,
        protein=31,
        fat=3.6,
        carbs=1,
        source="user",
        brand="Acme",
        resolution_mode="exact_product",
        source_id="partial-acme-chicken",
        provenance="user",
    )
    proxy, _ = _generic_food("chicken")
    proxy = replace(
        proxy,
        resolution_mode="generic_proxy",
        assumption="Used declared semantic food candidate: chicken.",
    )
    repository._cache_food(partial, lookup_query=partial.name)
    repository._cache_food(proxy, lookup_query="chicken")
    repository.user_connection.commit()
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [{"query": "chicken", "relation": "same_form"}],
                brand_intent=False,
            )
        ),
        expected_original=original,
    )
    before = _counts(repository)

    with pytest.raises(NomnomError) as caught:
        repository.plan_resolution(original, intent=intent, allow_remote=False)

    assert caught.value.code == "exact_resolution_required"
    assert caught.value.details["would_write"] is False
    assert caught.value.details["original"] == original
    assert _counts(repository) == before


def test_cli_partial_cached_exact_matching_brand_refuses_generic_without_writes(
    user_db, monkeypatch, capsys
):
    original = "Acme"
    partial = Food(
        name="Acme chicken",
        kcal=165,
        protein=31,
        fat=3.6,
        carbs=1,
        source="user",
        brand="Acme",
        resolution_mode="exact_product",
        source_id="partial-acme-chicken",
        provenance="user",
    )
    proxy, _ = _generic_food("chicken")
    proxy = replace(
        proxy,
        resolution_mode="generic_proxy",
        assumption="Used declared semantic food candidate: chicken.",
    )
    with connect(user_db) as connection:
        repository = FoodRepository(connection)
        repository._cache_food(partial, lookup_query=partial.name)
        repository._cache_food(proxy, lookup_query="chicken")

    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    original_state = _database_state(user_db)
    original_files = _directory_file_state(user_db.parent)

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(
                _intent(
                    original,
                    [{"query": "chicken", "relation": "same_form"}],
                    brand_intent=False,
                )
            ),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    error = _strict_json_loads(captured.err)

    assert code == 2
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert error["error"]["code"] == "exact_resolution_required"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"]["would_write"] is False
    assert error["error"]["details"]["original"] == original
    assert _database_state(user_db) == original_state
    assert _directory_file_state(user_db.parent) == original_files


@pytest.mark.parametrize(
    ("original", "brand"),
    [("Acme's", "Acme"), ("Campbell", "Campbell’s")],
)
def test_cli_possessive_brand_raw_cache_match_requires_exact_resolution_without_writes(
    user_db, monkeypatch, capsys, original, brand
):
    semantic_query = "chicken"
    raw_food = Food(
        name=original,
        kcal=165,
        protein=31,
        fat=3.6,
        carbs=1,
        source="legacy fixture",
        brand=brand,
        resolution_mode="legacy",
        source_id="legacy-possessive-brand",
        provenance="legacy fixture",
    )
    cached, _ = _generic_food(semantic_query)
    cached = replace(
        cached,
        resolution_mode="generic_proxy",
        assumption="Brand not specified; used USDA generic proxy: chicken.",
    )
    with connect(user_db) as connection:
        repository = FoodRepository(connection)
        repository._cache_food(raw_food, lookup_query=original)
        repository._cache_food(cached, lookup_query=semantic_query)

    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    original_state = _database_state(user_db)
    original_files = _directory_file_state(user_db.parent)

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(
                _intent(
                    original,
                    [{"query": semantic_query, "relation": "same_form"}],
                    brand_intent=False,
                )
            ),
            "--json",
        ]
    )
    error = json.loads(capsys.readouterr().err)

    assert code == 2
    assert error["error"]["code"] == "exact_resolution_required"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"]["original"] == original
    assert _database_state(user_db) == original_state
    assert _directory_file_state(user_db.parent) == original_files


@pytest.mark.parametrize(
    ("original", "food"),
    [
        (
            "1234567890123",
            Food(
                name="Exact barcode chicken",
                kcal=165,
                protein=31,
                fat=3.6,
                carbs=1,
                source="openfoodfacts",
                barcode="1234567890123",
                resolution_mode="exact_product",
                source_id="1234567890123",
                provenance="openfoodfacts",
            ),
        ),
        (
            "chicken 12345",
            Food(
                name="Pinned chicken product",
                kcal=165,
                protein=31,
                fat=3.6,
                carbs=1,
                source="user",
                resolution_mode="exact_product",
                source_id="pin-12345",
                provenance="user",
            ),
        ),
        (
            "курица SKU12345",
            Food(
                name="Pinned alphanumeric SKU chicken",
                kcal=165,
                protein=31,
                fat=3.6,
                carbs=1,
                source="user",
                resolution_mode="exact_product",
                source_id="pin-sku12345",
                provenance="user",
            ),
        ),
        (
            "курица SKU: ABC-123",
            Food(
                name="Pinned separated SKU chicken",
                kcal=165,
                protein=31,
                fat=3.6,
                carbs=1,
                source="user",
                resolution_mode="exact_product",
                source_id="pin-separated-sku",
                provenance="user",
            ),
        ),
        (
            "курица SKU: ABC/123",
            Food(
                name="Pinned slash-delimited SKU chicken",
                kcal=165,
                protein=31,
                fat=3.6,
                carbs=1,
                source="user",
                resolution_mode="exact_product",
                source_id="pin-slash-delimited-sku",
                provenance="user",
            ),
        ),
        (
            "Acme chicken",
            Food(
                name="Pinned Acme chicken",
                kcal=165,
                protein=31,
                fat=3.6,
                carbs=1,
                source="user",
                brand="Acme",
                resolution_mode="exact_product",
                source_id="pin-acme-chicken",
                provenance="user",
            ),
        ),
        (
            "Acme's chicken",
            Food(
                name="Pinned Acme chicken",
                kcal=165,
                protein=31,
                fat=3.6,
                carbs=1,
                source="user",
                brand="Acme",
                resolution_mode="exact_product",
                source_id="pin-acme-possessive-chicken",
                provenance="user",
            ),
        ),
        (
            "Campbell chicken",
            Food(
                name="Pinned Campbell chicken",
                kcal=165,
                protein=31,
                fat=3.6,
                carbs=1,
                source="user",
                brand="Campbell’s",
                resolution_mode="exact_product",
                source_id="pin-campbell-possessive-chicken",
                provenance="user",
            ),
        ),
    ],
)
def test_exact_local_barcode_or_pin_still_returns_raw_plan(repository, original, food):
    repository._cache_food(food, lookup_query=original)
    intent = parse_resolution_intent(
        json.dumps(
            _intent(original, [{"query": "chicken", "relation": "same_form"}])
        ),
        expected_original=original,
    )

    plan = repository.plan_resolution(original, intent=intent, allow_remote=False)

    assert plan["retrieval_query"] == original
    assert plan["resolution_mode"] == "exact_product"
    assert plan["source_id"] == food.source_id
    assert plan["would_write"] is False


def test_exact_local_alias_still_returns_raw_plan(repository):
    canonical = Food(
        name="Pinned Acme chicken",
        kcal=165,
        protein=31,
        fat=3.6,
        carbs=1,
        source="user",
        brand="Acme",
        resolution_mode="exact_product",
        source_id="pin-acme-alias",
        provenance="user",
    )
    repository._cache_food(canonical, lookup_query=canonical.name)
    repository.add_alias("my chicken", canonical.name)
    intent = parse_resolution_intent(
        json.dumps(_intent("my chicken", [])),
        expected_original="my chicken",
    )

    plan = repository.plan_resolution("my chicken", intent=intent, allow_remote=False)

    assert plan["retrieval_query"] == "my chicken"
    assert plan["resolution_mode"] == "exact_product"
    assert plan["source_id"] == canonical.source_id
    assert plan["would_write"] is False


@pytest.mark.parametrize("use_alias", [False, True], ids=["pin", "alias"])
def test_cli_valid_exact_pin_or_alias_still_returns_raw_plan_without_writes(
    user_db, monkeypatch, capsys, use_alias
):
    original = "my chicken" if use_alias else "Acme chicken"
    canonical = Food(
        name="Pinned Acme chicken",
        kcal=165,
        protein=31,
        fat=3.6,
        carbs=1,
        source="user",
        brand="Acme",
        resolution_mode="exact_product",
        source_id="pin-acme-cli",
        provenance="user",
    )
    with connect(user_db) as connection:
        repository = FoodRepository(connection)
        repository._cache_food(canonical, lookup_query="Acme chicken")
        if use_alias:
            repository.add_alias(original, canonical.name)

    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    original_state = _database_state(user_db)
    original_files = _directory_file_state(user_db.parent)

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(_intent(original, [])),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    plan = _strict_json_loads(captured.out)

    assert code == 0
    assert captured.err == ""
    assert plan["retrieval_query"] == original
    assert plan["resolution_mode"] == "exact_product"
    assert plan["source_id"] == canonical.source_id
    assert plan["would_write"] is False
    assert _database_state(user_db) == original_state
    assert _directory_file_state(user_db.parent) == original_files


def test_cli_resolve_reuses_exact_captured_barcode_without_provider_or_writes(
    user_db, monkeypatch, capsys
):
    barcode = "0123456789012"
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setattr(
        "nomnomcli.foods.OpenFoodFactsClient.product_by_barcode",
        lambda self, code: Food(
            name="Fixture Bar — Acme",
            kcal=250,
            protein=9,
            fat=4,
            carbs=45,
            source="openfoodfacts",
            barcode=code,
            brand="Acme",
        ),
    )

    assert main(["capture", "barcode", barcode, "--json"]) == 0
    captured_product = _strict_json_loads(capsys.readouterr().out)
    assert captured_product["barcode"] == barcode

    def unexpected_provider_call(*args, **kwargs):
        pytest.fail("exact captured barcode reached a remote provider")

    monkeypatch.setattr(
        "nomnomcli.foods.OpenFoodFactsClient.product_by_barcode",
        unexpected_provider_call,
    )
    monkeypatch.setattr(
        "nomnomcli.foods.OpenFoodFactsClient.search", unexpected_provider_call
    )
    monkeypatch.setattr("nomnomcli.foods.USDAClient.resolve", unexpected_provider_call)
    monkeypatch.delenv("NOMNOM_OFFLINE", raising=False)
    monkeypatch.delenv("NOMNOM_DISABLE_OFF", raising=False)
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    original_state = _database_state(user_db)
    original_files = _directory_file_state(user_db.parent)

    code = main(
        [
            "resolve",
            "--food",
            barcode,
            "--intent-json",
            json.dumps(_intent(barcode, [])),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    plan = _strict_json_loads(captured.out)

    assert code == 0
    assert captured.err == ""
    assert plan["original"] == barcode
    assert plan["retrieval_query"] == barcode
    assert plan["provider"] == "openfoodfacts"
    assert plan["source_id"] == barcode
    assert plan["resolution_mode"] == "exact_product"
    assert plan["would_write"] is False
    assert _database_state(user_db) == original_state
    assert _directory_file_state(user_db.parent) == original_files


def test_cli_recaptured_barcode_replaces_stale_product_before_readonly_resolve(
    user_db, monkeypatch, capsys
):
    barcode = "0123456789012"
    unrelated_barcode = "9876543210987"
    products = iter(
        (
            Food(
                name="Old Fixture Bar — Acme",
                kcal=250,
                protein=9,
                fat=4,
                carbs=45,
                source="openfoodfacts",
                barcode=barcode,
                brand="Acme",
            ),
            Food(
                name="Current Fixture Bar — Acme",
                kcal=180,
                protein=12,
                fat=6,
                carbs=20,
                source="openfoodfacts",
                barcode=barcode,
                brand="Acme",
            ),
        )
    )
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    with connect(user_db) as connection:
        FoodRepository(connection)._cache_food(
            Food(
                name="Unrelated Fixture",
                kcal=90,
                protein=2,
                fat=1,
                carbs=18,
                source="openfoodfacts",
                barcode=unrelated_barcode,
                brand="Other",
                resolution_mode="exact_product",
                source_id=unrelated_barcode,
                provenance="openfoodfacts",
            ),
            lookup_query="Unrelated Fixture Other",
        )
    monkeypatch.setattr(
        "nomnomcli.foods.OpenFoodFactsClient.product_by_barcode",
        lambda self, code: next(products),
    )

    assert main(["capture", "barcode", barcode, "--json"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "alias",
                "add",
                "fixture favorite",
                "Old Fixture Bar — Acme",
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    with connect(user_db) as connection:
        FoodRepository(connection).add_alias("other favorite", "Unrelated Fixture")
    assert main(["capture", "barcode", barcode, "--json"]) == 0
    latest_capture = _strict_json_loads(capsys.readouterr().out)
    assert latest_capture["name"] == "Current Fixture Bar — Acme"
    assert latest_capture["source_id"] == barcode
    assert latest_capture["kcal_per_100g"] == 180
    assert latest_capture["protein_per_100g"] == 12
    assert latest_capture["fat_per_100g"] == 6
    assert latest_capture["carbs_per_100g"] == 20

    with sqlite3.connect(user_db) as connection:
        barcode_rows = connection.execute(
            """SELECT name, kcal, protein, fat, carbs, source_id
            FROM food_cache WHERE barcode = ?""",
            (barcode,),
        ).fetchall()
        unrelated = connection.execute(
            "SELECT name, barcode, kcal FROM food_cache WHERE name = 'Unrelated Fixture'"
        ).fetchone()
        aliases = connection.execute(
            """SELECT phrase, canonical_name FROM food_aliases
            ORDER BY normalized_phrase"""
        ).fetchall()
        dangling_aliases = connection.execute(
            """SELECT count(*) FROM food_aliases AS alias
            LEFT JOIN food_cache AS food ON food.name = alias.canonical_name
            WHERE food.name IS NULL"""
        ).fetchone()[0]
    assert barcode_rows == [
        ("Current Fixture Bar — Acme", 180, 12, 6, 20, barcode)
    ]
    assert unrelated == ("Unrelated Fixture", unrelated_barcode, 90)
    assert aliases == [
        ("fixture favorite", "Current Fixture Bar — Acme"),
        ("other favorite", "Unrelated Fixture"),
    ]
    assert dangling_aliases == 0

    with connect(user_db) as connection:
        aliased, confidence = FoodRepository(connection).resolve(
            "fixture favorite", allow_remote=False
        )
    assert aliased.name == "Current Fixture Bar — Acme"
    assert aliased.kcal == 180
    assert aliased.source_id == barcode
    assert confidence == 1.0

    def unexpected_provider_call(*args, **kwargs):
        pytest.fail("recaptured barcode reached a remote provider")

    monkeypatch.setattr(
        "nomnomcli.foods.OpenFoodFactsClient.product_by_barcode",
        unexpected_provider_call,
    )
    monkeypatch.setattr(
        "nomnomcli.foods.OpenFoodFactsClient.search", unexpected_provider_call
    )
    monkeypatch.setattr("nomnomcli.foods.USDAClient.resolve", unexpected_provider_call)
    resolved_food = {}
    original_resolution_plan = FoodRepository._resolution_plan

    def observe_resolution_plan(self, *, food, **kwargs):
        resolved_food.update(
            name=food.name,
            kcal=food.kcal,
            protein=food.protein,
            fat=food.fat,
            carbs=food.carbs,
            source_id=food.source_id,
        )
        return original_resolution_plan(self, food=food, **kwargs)

    monkeypatch.setattr(FoodRepository, "_resolution_plan", observe_resolution_plan)
    monkeypatch.delenv("NOMNOM_OFFLINE", raising=False)
    monkeypatch.delenv("NOMNOM_DISABLE_OFF", raising=False)
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    original_state = _database_state(user_db)
    original_files = _directory_file_state(user_db.parent)

    code = main(
        [
            "resolve",
            "--food",
            barcode,
            "--intent-json",
            json.dumps(_intent(barcode, [])),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    plan = _strict_json_loads(captured.out)

    assert code == 0
    assert captured.err == ""
    assert plan["source_id"] == barcode
    assert plan["resolution_mode"] == "exact_product"
    assert plan["would_write"] is False
    assert resolved_food == {
        "name": "Current Fixture Bar — Acme",
        "kcal": 180,
        "protein": 12,
        "fat": 6,
        "carbs": 20,
        "source_id": barcode,
    }
    assert _database_state(user_db) == original_state
    assert _directory_file_state(user_db.parent) == original_files


@pytest.mark.parametrize(
    "unknown_barcode",
    ["012345678901", "0123456789013"],
    ids=("partial", "unknown"),
)
def test_cli_resolve_refuses_nonexact_captured_barcode(
    user_db, monkeypatch, capsys, unknown_barcode
):
    captured_barcode = "0123456789012"
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setattr(
        "nomnomcli.foods.OpenFoodFactsClient.product_by_barcode",
        lambda self, code: Food(
            name="Fixture Bar — Acme",
            kcal=250,
            protein=9,
            fat=4,
            carbs=45,
            source="openfoodfacts",
            barcode=code,
            brand="Acme",
        ),
    )
    assert main(["capture", "barcode", captured_barcode, "--json"]) == 0
    capsys.readouterr()
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    original_state = _database_state(user_db)
    original_files = _directory_file_state(user_db.parent)

    code = main(
        [
            "resolve",
            "--food",
            unknown_barcode,
            "--intent-json",
            json.dumps(_intent(unknown_barcode, [])),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    error = _strict_json_loads(captured.err)

    assert code == 2
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert error["error"]["code"] == "exact_resolution_required"
    assert error["error"]["would_write"] is False
    assert _database_state(user_db) == original_state
    assert _directory_file_state(user_db.parent) == original_files


def test_conflicting_partial_pinned_brand_never_returns_raw_exact_plan(repository):
    original = "Other chicken"
    conflicting = Food(
        name="Acme chicken",
        kcal=165,
        protein=31,
        fat=3.6,
        carbs=1,
        source="user",
        brand="Acme",
        resolution_mode="exact_product",
        source_id="pin-acme-conflict",
        provenance="user",
    )
    repository._cache_food(conflicting, lookup_query=conflicting.name)
    repository.user_connection.commit()
    intent = parse_resolution_intent(
        json.dumps(_intent(original, [])),
        expected_original=original,
    )
    before = _counts(repository)

    with pytest.raises(NomnomError) as caught:
        repository.plan_resolution(original, intent=intent, allow_remote=False)

    assert caught.value.code in {"exact_resolution_required", "semantic_resolution_not_found"}
    assert caught.value.details["would_write"] is False
    assert _counts(repository) == before


def test_conflicting_partial_pinned_brand_continues_to_safe_semantic_candidate(
    repository,
):
    original = "Other chicken"
    conflicting = Food(
        name="Acme chicken",
        kcal=165,
        protein=31,
        fat=3.6,
        carbs=1,
        source="user",
        brand="Acme",
        resolution_mode="exact_product",
        source_id="pin-acme-conflict",
        provenance="user",
    )
    proxy, _ = _generic_food("tofu")
    proxy = replace(
        proxy,
        resolution_mode="generic_proxy",
        assumption="Used declared semantic food candidate: tofu.",
    )
    repository._cache_food(conflicting, lookup_query=conflicting.name)
    repository._cache_food(proxy, lookup_query="tofu")
    repository.user_connection.commit()
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [{"query": "tofu", "relation": "lexical_equivalent"}],
            )
        ),
        expected_original=original,
    )
    before = _counts(repository)

    plan = repository.plan_resolution(original, intent=intent, allow_remote=False)

    assert plan["retrieval_query"] == "tofu"
    assert plan["resolution_mode"] == "generic_proxy"
    assert plan["would_write"] is False
    assert _counts(repository) == before


def test_nonmatching_raw_cache_brand_does_not_infer_exact_intent(repository):
    original = "Other chicken"
    cached = Food(
        name=original,
        kcal=165,
        protein=31,
        fat=3.6,
        carbs=1,
        source="legacy fixture",
        brand="Acme",
        resolution_mode="legacy",
        source_id="legacy-other-chicken",
        provenance="legacy fixture",
    )
    repository._cache_food(cached, lookup_query=original)
    repository.user_connection.commit()
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [{"query": "tofu", "relation": "same_form"}],
                brand_intent=False,
            )
        ),
        expected_original=original,
    )
    before = _counts(repository)

    plan = repository.plan_resolution(original, intent=intent, allow_remote=False)

    assert plan["retrieval_query"] == original
    assert plan["resolution_mode"] == "legacy"
    assert plan["source_id"] == cached.source_id
    assert plan["would_write"] is False
    assert _counts(repository) == before


def test_cli_raw_cache_dropped_token_requires_exact_resolution_without_source_writes(
    user_db, monkeypatch, capsys
):
    original = "Acme chicken"
    cached, _ = _generic_food("chicken")
    cached = replace(
        cached,
        resolution_mode="generic_proxy",
        assumption="Brand not specified; used USDA generic proxy: chicken.",
    )
    with connect(user_db) as connection:
        FoodRepository(connection)._cache_food(cached, lookup_query=original)

    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    original_state = _database_state(user_db)
    original_files = _directory_file_state(user_db.parent)

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(
                _intent(
                    original,
                    [{"query": "chicken", "relation": "same_form"}],
                    brand_intent=False,
                )
            ),
            "--json",
        ]
    )
    error = json.loads(capsys.readouterr().err)

    assert code == 2
    assert error["error"]["code"] == "exact_resolution_required"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"]["original"] == original
    assert _database_state(user_db) == original_state
    assert _directory_file_state(user_db.parent) == original_files


def test_explicit_brand_is_protected_without_off_response(repository, monkeypatch):
    original = "Acme chicken"
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [{"query": "chicken", "relation": "same_form"}],
                brand_intent=False,
            )
        ),
        expected_original=original,
    )
    cached, _ = _generic_food("chicken")
    cached = replace(
        cached,
        resolution_mode="generic_proxy",
        assumption="Brand not specified; used USDA generic proxy: chicken.",
    )
    repository._cache_food(cached, lookup_query="chicken")
    repository.user_connection.commit()
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.delenv("NOMNOM_USDA_KEY", raising=False)
    before = _counts(repository)

    with pytest.raises(NomnomError) as caught:
        repository.plan_resolution(original, intent=intent)

    assert caught.value.code == "exact_resolution_required"
    assert caught.value.details["would_write"] is False
    assert _counts(repository) == before


@pytest.mark.parametrize(
    ("original", "brand"),
    [("Acme's", "Acme"), ("Campbell", "Campbell’s")],
)
def test_cli_possessive_brand_provider_match_requires_exact_resolution_without_writes(
    user_db, monkeypatch, capsys, original, brand
):
    semantic_query = "chicken"
    cached, _ = _generic_food(semantic_query)
    cached = replace(
        cached,
        resolution_mode="generic_proxy",
        assumption="Brand not specified; used USDA generic proxy: chicken.",
    )
    with connect(user_db) as connection:
        FoodRepository(connection)._cache_food(cached, lookup_query=semantic_query)

    branded, _ = _generic_food(
        f"{brand} chicken",
        source="openfoodfacts",
        source_id="10000010",
    )
    branded = replace(branded, brand=brand, categories=("chicken",))
    monkeypatch.setattr(
        "nomnomcli.off.OpenFoodFactsClient.search",
        lambda client, query, page_size=5: [branded] if query == original else [],
    )
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.delenv("NOMNOM_USDA_KEY", raising=False)
    original_state = _database_state(user_db)
    original_files = _directory_file_state(user_db.parent)

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(
                _intent(
                    original,
                    [{"query": semantic_query, "relation": "same_form"}],
                    brand_intent=False,
                )
            ),
            "--json",
        ]
    )
    error = json.loads(capsys.readouterr().err)

    assert code == 2
    assert error["error"]["code"] == "exact_resolution_required"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"]["original"] == original
    assert _database_state(user_db) == original_state
    assert _directory_file_state(user_db.parent) == original_files


def test_off_brand_match_survives_usda_failure_without_source_writes(
    user_db, monkeypatch, capsys
):
    original = "Acme"
    semantic_query = "chicken"
    cached, _ = _generic_food(semantic_query)
    cached = replace(
        cached,
        resolution_mode="generic_proxy",
        assumption="Brand not specified; used USDA generic proxy: chicken.",
    )
    with connect(user_db) as connection:
        FoodRepository(connection)._cache_food(cached, lookup_query=semantic_query)

    branded, _ = _generic_food(
        "Acme chicken",
        source="openfoodfacts",
        source_id="10000012",
    )
    branded = replace(branded, brand="Acme", categories=("chicken",))
    monkeypatch.setattr(
        "nomnomcli.off.OpenFoodFactsClient.search",
        lambda client, query, page_size=5: [branded] if query == original else [],
    )

    def fail_usda(client, query, api_key):
        raise NomnomError("food_not_found", f"No USDA food for {query}")

    monkeypatch.setattr("nomnomcli.usda.USDAClient.resolve", fail_usda)
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    original_state = _database_state(user_db)
    original_files = _directory_file_state(user_db.parent)

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(
                _intent(
                    original,
                    [{"query": semantic_query, "relation": "same_form"}],
                    brand_intent=False,
                )
            ),
            "--json",
        ]
    )
    error = json.loads(capsys.readouterr().err)

    assert code == 2
    assert error["error"]["code"] == "exact_resolution_required"
    assert error["error"]["would_write"] is False
    assert error["error"]["details"]["original"] == original
    assert _database_state(user_db) == original_state
    assert _directory_file_state(user_db.parent) == original_files


def test_nonmatching_provider_brand_does_not_infer_exact_intent(
    repository, monkeypatch
):
    original = "mystery poultry"
    semantic_query = "chicken"
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [{"query": semantic_query, "relation": "same_form"}],
            )
        ),
        expected_original=original,
    )
    cached, _ = _generic_food(semantic_query)
    cached = replace(
        cached,
        resolution_mode="generic_proxy",
        assumption="Brand not specified; used USDA generic proxy: chicken.",
    )
    repository._cache_food(cached, lookup_query=semantic_query)
    repository.user_connection.commit()
    branded, _ = _generic_food(
        "Acme chicken",
        source="openfoodfacts",
        source_id="10000011",
    )
    branded = replace(branded, brand="Acme", categories=("chicken",))
    monkeypatch.setattr(repository.off_client, "search", lambda *args, **kwargs: [branded])
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")

    def fail_usda(query, api_key):
        raise NomnomError("food_not_found", f"No USDA food for {query}")

    monkeypatch.setattr(repository.usda_client, "resolve", fail_usda)
    before = _counts(repository)

    plan = repository.plan_resolution(original, intent=intent)

    assert plan["retrieval_query"] == semantic_query
    assert plan["resolution_mode"] == "generic_proxy"
    assert plan["would_write"] is False
    assert _counts(repository) == before


def test_reopened_cached_usda_proxy_ranks_before_safe_off_same_relation(
    user_db, monkeypatch
):
    cached, _ = _generic_food("chicken breast roasted", confidence=0.81)
    cached = replace(
        cached,
        resolution_mode="generic_proxy",
        assumption="Brand not specified; used USDA generic proxy: chicken breast roasted.",
    )
    with connect(user_db) as connection:
        FoodRepository(connection)._cache_food(cached, lookup_query="chicken breast roasted")

    original = "описание курицы"
    intent = parse_resolution_intent(
        json.dumps(
            _intent(
                original,
                [
                    {"query": "chicken pastrami", "relation": "same_form"},
                    {"query": "chicken breast roasted", "relation": "same_form"},
                ],
            )
        ),
        expected_original=original,
    )
    off_food, _ = _generic_food(
        "Chicken pastrami",
        source="openfoodfacts",
        source_id="10000003",
    )
    off_food = replace(off_food, categories=("chicken pastrami",))
    monkeypatch.delenv("NOMNOM_USDA_KEY", raising=False)

    with connect(user_db) as connection:
        repository = FoodRepository(connection)
        reopened = repository._find_exact("chicken breast roasted")
        assert reopened is not None
        assert reopened.provider_data_type is None
        monkeypatch.setattr(
            repository.off_client,
            "search",
            lambda query, page_size=5: [off_food] if query == "chicken pastrami" else [],
        )

        plan = repository.plan_resolution(original, intent=intent)

    assert plan["candidate_index"] == 1
    assert plan["source"] == "usda"
    assert plan["resolution_mode"] == "generic_proxy"


def test_cli_rejects_whitespace_original_before_opening_cache(
    user_db, monkeypatch, capsys
):
    with connect(user_db) as connection:
        pinned = Food(
            name="Unrelated pinned product",
            kcal=100,
            protein=1,
            fat=1,
            carbs=1,
            source="user",
            resolution_mode="exact_product",
            source_id="pin-1",
        )
        FoodRepository(connection)._cache_food(pinned, lookup_query="unrelated")
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setattr(
        "nomnomcli.cli.connect_read_only",
        lambda: pytest.fail("whitespace intent reached the cache connection"),
    )
    original = "   \t"

    code = main(
        [
            "resolve",
            "--food",
            original,
            "--intent-json",
            json.dumps(_intent(original, [])),
            "--json",
        ]
    )
    error = json.loads(capsys.readouterr().err)

    assert code == 2
    assert error["error"]["code"] == "invalid_resolution_intent"
    with connect(user_db) as connection:
        assert connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 1
