from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from dataclasses import replace

import pytest

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
    ],
)
def test_exact_local_barcode_or_pin_still_returns_raw_plan(repository, original, food):
    repository._cache_food(food, lookup_query=original)
    intent = parse_resolution_intent(
        json.dumps(_intent(original, [])), expected_original=original
    )

    plan = repository.plan_resolution(original, intent=intent, allow_remote=False)

    assert plan["retrieval_query"] == original
    assert plan["resolution_mode"] == "exact_product"
    assert plan["source_id"] == food.source_id
    assert plan["would_write"] is False


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
