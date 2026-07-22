from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from nomnomcli.cli import main
from nomnomcli.db import connect
from nomnomcli.models import Food
from nomnomcli.off import OpenFoodFactsClient
from nomnomcli.usda import USDAClient


def test_cli_logs_default_safe_usda_proxy_with_visible_provenance(
    user_db, monkeypatch, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_USDA_KEY", "test-key")
    monkeypatch.setenv("NOMNOM_DISABLE_OFF", "1")
    monkeypatch.delenv("NOMNOM_GENERIC_PROXY_POLICY", raising=False)
    monkeypatch.setattr(
        USDAClient,
        "resolve",
        lambda self, query, api_key: (
            Food(
                "chicken breast, roasted",
                165,
                31,
                3.6,
                1,
                source="usda",
                fdc_id=171477,
                source_id="171477",
                provenance="usda",
                provider_data_type="Foundation",
            ),
            0.95,
        ),
    )

    assert (
        main(
            [
                "log",
                "--food",
                "chicken breast roasted",
                "--grams",
                "100",
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)

    assert result["assumptions"] == [
        "Brand not specified; used USDA generic proxy: chicken breast, roasted."
    ]
    assert result["items"][0]["resolution_mode"] == "generic_proxy"
    assert result["items"][0]["source"] == "usda"
    assert result["items"][0]["source_id"] == "171477"
    assert result["items"][0]["provenance"] == "usda"
    assert result["items"][0]["fdc_id"] == 171477
    with connect(user_db) as connection:
        assert connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM log_entries").fetchone()[0] == 1


def test_cli_capture_barcode_caches_exact_product_provenance(
    user_db, monkeypatch, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setattr(
        OpenFoodFactsClient,
        "product_by_barcode",
        lambda self, code: Food(
            "Fixture Bar — Acme",
            250,
            9,
            4,
            45,
            source="openfoodfacts",
            barcode=code,
            brand="Acme",
        ),
    )

    assert main(["capture", "barcode", "0123456789012", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["name"] == "Fixture Bar — Acme"
    assert result["source"] == "openfoodfacts"
    assert result["source_id"] == "0123456789012"
    assert result["barcode"] == "0123456789012"
    assert result["resolution_mode"] == "exact_product"
    assert result["provenance"] == "openfoodfacts"
    with connect(user_db) as connection:
        row = connection.execute(
            """SELECT source, source_id, barcode, resolution_mode, provenance
            FROM food_cache"""
        ).fetchone()
        assert tuple(row) == (
            "openfoodfacts",
            "0123456789012",
            "0123456789012",
            "exact_product",
            "openfoodfacts",
        )


def test_cli_barcode_recapture_consolidates_duplicate_rows_and_preserves_alias(
    user_db, monkeypatch, capsys
):
    barcode = "0123456789012"
    with connect(user_db) as connection:
        for name, kcal in (("Stale product", 100), ("Other stale product", 150)):
            connection.execute(
                """INSERT INTO food_cache
                (name, kcal, protein, fat, carbs, source, barcode, resolution_mode,
                 source_id, provenance)
                VALUES (?, ?, 10, 5, 20, 'openfoodfacts', ?, 'exact_product', ?,
                        'openfoodfacts')""",
                (name, kcal, barcode, barcode),
            )
        connection.execute(
            """INSERT INTO food_aliases (phrase, normalized_phrase, canonical_name)
            VALUES ('my bar', 'my bar', 'Stale product')"""
        )
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setattr(
        OpenFoodFactsClient,
        "product_by_barcode",
        lambda self, code: Food(
            "Current product — Acme",
            250,
            9,
            4,
            45,
            source="openfoodfacts",
            barcode=code,
            brand="Acme",
        ),
    )

    assert main(["capture", "barcode", barcode, "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["name"] == "Current product — Acme"

    with connect(user_db) as connection:
        rows = connection.execute(
            """SELECT name, kcal, resolution_mode, source_id, provenance
            FROM food_cache WHERE barcode = ?""",
            (barcode,),
        ).fetchall()
        alias = connection.execute(
            "SELECT canonical_name FROM food_aliases WHERE normalized_phrase = 'my bar'"
        ).fetchone()
    assert [tuple(row) for row in rows] == [
        ("Current product — Acme", 250.0, "exact_product", barcode, "openfoodfacts")
    ]
    assert alias[0] == "Current product — Acme"


def test_cli_capture_barcode_incomplete_product_is_never_cached(
    user_db, monkeypatch, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))

    def incomplete(self, code):
        from nomnomcli.errors import NomnomError

        raise NomnomError(
            "barcode_nutrition_incomplete",
            "Barcode product lacks complete core nutrition",
            details={"barcode": code},
        )

    monkeypatch.setattr(OpenFoodFactsClient, "product_by_barcode", incomplete)

    assert main(["capture", "barcode", "0123456789012", "--json"]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "barcode_nutrition_incomplete"
    with connect(user_db) as connection:
        assert connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 0


def test_cli_capture_label_requires_source_note_and_writes_nothing(
    user_db, monkeypatch, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    argv = [
        "capture",
        "label",
        "--name",
        "Chicken pastrami",
        "--brand",
        "Acme",
        "--kcal",
        "110",
        "--protein",
        "20",
        "--fat",
        "2",
        "--carbs",
        "3",
        "--json",
    ]

    assert main(argv) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "invalid_source_note"
    with connect(user_db) as connection:
        assert connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 0


def test_cli_capture_label_persists_agent_extracted_facts_alias_and_log(
    user_db, monkeypatch, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    assert (
        main(
            [
                "capture",
                "label",
                "--name",
                "Chicken pastrami",
                "--brand",
                "Acme",
                "--kcal",
                "110",
                "--protein",
                "20",
                "--fat",
                "2",
                "--carbs",
                "3",
                "--serving-grams",
                "75",
                "--source-note",
                "image:sha256:synthetic-fixture",
                "--json",
            ]
        )
        == 0
    )
    captured = json.loads(capsys.readouterr().out)
    assert captured == {
        "barcode": None,
        "brand": "Acme",
        "carbs_per_100g": 3.0,
        "fat_per_100g": 2.0,
        "kcal_per_100g": 110.0,
        "name": "Chicken pastrami — Acme",
        "protein_per_100g": 20.0,
        "provenance": "package_label",
        "resolution_mode": "exact_product",
        "serving_grams": 75.0,
        "source": "package_label",
        "source_id": "image:sha256:synthetic-fixture",
        "source_note": "image:sha256:synthetic-fixture",
    }

    assert (
        main(
            [
                "alias",
                "add",
                "куриная пастрома",
                captured["name"],
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    assert main(["log", "--parse", "куриная пастрома 150г", "--json"]) == 0
    logged = json.loads(capsys.readouterr().out)
    assert logged["items"][0] == {
        "brand": "Acme",
        "carbs": 4.5,
        "fat": 3.0,
        "grams": 150.0,
        "kcal": 165.0,
        "match_confidence": 1.0,
        "name": "Chicken pastrami — Acme",
        "protein": 30.0,
        "provenance": "package_label",
        "resolution_mode": "exact_product",
        "source": "package_label",
        "source_id": "image:sha256:synthetic-fixture",
        "source_note": "image:sha256:synthetic-fixture",
    }
    with connect(user_db) as connection:
        assert connection.execute("SELECT count(*) FROM food_aliases").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM log_entries").fetchone()[0] == 1


def test_cli_capture_label_rejects_invalid_values_without_cache(
    user_db, monkeypatch, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    assert (
        main(
            [
                "capture",
                "label",
                "--name",
                "Fixture",
                "--kcal",
                "-1",
                "--protein",
                "1",
                "--fat",
                "1",
                "--carbs",
                "1",
                "--source-note",
                "image:fixture",
                "--json",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "invalid_nutrition"
    with connect(user_db) as connection:
        assert connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 0


def _run_cli(repo: Path, database: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "NOMNOM_DB_PATH": str(database),
        "NOMNOM_OFFLINE": "1",
        "PYTHONPATH": str(repo),
    }
    return subprocess.run(
        [sys.executable, "-m", "nomnomcli", *args],
        cwd=repo,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_fresh_database_cli_capture_alias_log_and_bad_input_smoke(tmp_path):
    repo = Path(__file__).parents[1]
    database = tmp_path / "fresh-smoke.sqlite3"

    help_result = _run_cli(repo, database, "--help")
    version_result = _run_cli(repo, database, "--version")
    capture = _run_cli(
        repo,
        database,
        "capture",
        "label",
        "--name",
        "Synthetic bar",
        "--brand",
        "Fixture",
        "--kcal",
        "200",
        "--protein",
        "10",
        "--fat",
        "5",
        "--carbs",
        "30",
        "--source-note",
        "image:synthetic-smoke",
        "--json",
    )
    canonical = json.loads(capture.stdout)["name"]
    alias = _run_cli(repo, database, "alias", "add", "my bar", canonical, "--json")
    logged = _run_cli(repo, database, "log", "--parse", "my bar 50g", "--json")
    invalid = _run_cli(
        repo,
        database,
        "capture",
        "label",
        "--name",
        "Bad",
        "--kcal",
        "-1",
        "--protein",
        "1",
        "--fat",
        "1",
        "--carbs",
        "1",
        "--source-note",
        "image:bad",
        "--json",
    )

    assert help_result.returncode == 0
    assert "capture" in help_result.stdout
    assert version_result.stdout.strip() == "nomnom 0.4.0"
    assert capture.returncode == 0
    assert alias.returncode == 0
    assert json.loads(logged.stdout)["items"][0]["resolution_mode"] == "exact_product"
    assert invalid.returncode == 2
    assert json.loads(invalid.stderr)["error"]["code"] == "invalid_nutrition"
