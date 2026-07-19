from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from shutil import copyfile

import pytest


def bundled_rows():
    database = files("nomnomcli.data").joinpath("foods.sqlite")
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT name, kcal, protein, fat, carbs, source FROM foods ORDER BY name"
        ).fetchall()


def test_required_v02_profiles_replace_placeholders():
    rows = {row["name"]: row for row in bundled_rows()}
    expected_kcal = {
        "oil, sunflower": 884,
        "water": 0,
        "chocolate, dark": 598,
        "beer": 43,
        "wine": 83,
        "vodka": 231,
        "cola": 37,
        "jam": 278,
        "cheese, mozzarella": 280,
        "cheese, parmesan": 431,
        "mayonnaise": 680,
        "soy sauce": 53,
        "honey": 304,
        "croissant": 406,
        "ice cream, vanilla": 207,
        "herring": 203,
        "pizza": 266,
        "candy": 394,
        "kvass": 27,
    }
    for name, kcal in expected_kcal.items():
        assert rows[name]["kcal"] == pytest.approx(kcal, abs=1)

    assert 30 <= rows["chicken soup"]["kcal"] <= 60
    assert rows["tomato soup"]["kcal"] == pytest.approx(30, abs=5)
    assert rows["pea soup"]["kcal"] == pytest.approx(60, abs=5)
    assert rows["mushroom soup"]["kcal"] == pytest.approx(30, abs=5)
    assert rows["lentil soup"]["kcal"] == pytest.approx(60, abs=5)
    assert rows["fish soup"]["kcal"] == pytest.approx(40, abs=5)
    assert rows["soup"]["kcal"] == pytest.approx(40, abs=5)
    assert rows["stew"]["kcal"] == pytest.approx(90, abs=5)
    assert rows["vegetable stew"]["kcal"] == pytest.approx(40, abs=5)


def test_macro_energy_is_compatible_with_stated_kcal():
    alcohol_exceptions = {"beer", "wine", "vodka", "brandy"}
    failures = []
    for row in bundled_rows():
        if row["name"] in alcohol_exceptions:
            continue
        macro_kcal = 4 * row["protein"] + 9 * row["fat"] + 4 * row["carbs"]
        if row["kcal"] == 0:
            compatible = macro_kcal == 0
        elif row["kcal"] < 10:
            compatible = abs(row["kcal"] - macro_kcal) <= 2
        else:
            compatible = abs(row["kcal"] - macro_kcal) / row["kcal"] <= 0.2
        if not compatible:
            failures.append((row["name"], row["kcal"], round(macro_kcal, 2)))
    assert failures == []


def test_oil_water_and_placeholder_invariants():
    rows = bundled_rows()
    oils = [
        row
        for row in rows
        if row["name"].casefold().startswith("oil,")
        or row["name"].casefold().endswith(" oil")
    ]
    assert oils
    assert all(row["kcal"] >= 850 for row in oils)

    water = next(row for row in rows if row["name"] == "water")
    assert (water["kcal"], water["protein"], water["fat"], water["carbs"]) == (0, 0, 0, 0)

    justified_157 = {
        "pasta, cooked",
        "pasta, cooked, enriched, with added salt",
        "pasta, cooked, unenriched, with added salt",
        "potato salad with egg",
    }
    rows_at_157 = {row["name"] for row in rows if row["kcal"] == 157}
    assert rows_at_157 <= justified_157


def test_offline_database_update_is_byte_deterministic(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "foods.sqlite"
    copyfile(root / "nomnomcli" / "data" / "foods.sqlite", database)
    command = [
        sys.executable,
        str(root / "scripts" / "build_mini_db.py"),
        "--output",
        str(database),
        "--update-existing",
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    first = database.read_bytes()
    subprocess.run(command, check=True, capture_output=True, text=True)
    assert database.read_bytes() == first


def test_offline_seed_contains_no_known_placeholder_profile():
    root = Path(__file__).resolve().parents[1]
    rows = json.loads((root / "scripts" / "synonym_foods.json").read_text())
    placeholders = [
        row[0]
        for row in rows
        if row[1] == 157 and row[2:5] == [12.6, 9.79, 4.57]
    ]
    assert placeholders == []
