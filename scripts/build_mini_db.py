#!/usr/bin/env python3
"""Regenerate the bundled mini database from USDA FoodData Central.

Maintainers run:
    NOMNOM_USDA_KEY=... python scripts/build_mini_db.py

The hand-curated dish rows supply common prepared foods that are not represented by
a single standard USDA item. USDA search results fill the rest of the 300-item target.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "nomnomcli" / "data" / "foods.sqlite"
SYNONYM_SEED = ROOT / "scripts" / "synonym_foods.json"
CURATED_OVERRIDES = ROOT / "scripts" / "food_overrides.json"

SCHEMA = """
DROP TABLE IF EXISTS foods;
CREATE TABLE foods (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    kcal REAL NOT NULL,
    protein REAL NOT NULL,
    fat REAL NOT NULL,
    carbs REAL NOT NULL,
    piece_grams REAL,
    density_g_ml REAL,
    source TEXT NOT NULL,
    fdc_id INTEGER
);
CREATE INDEX idx_foods_name ON foods(name COLLATE NOCASE);
"""

# name, kcal, protein, fat, carbs, piece grams, density g/ml, source, fdc id
# USDA-derived rows use SR Legacy values. Prepared dishes are labelled separately.
SEED_FOODS = [
    ("borscht", 55.0, 2.5, 2.1, 6.4, 350.0, 1.0, "typical prepared dish", None),
    ("plov", 180.0, 6.0, 7.0, 24.0, 250.0, None, "typical prepared dish", None),
    ("olivier salad", 198.0, 5.5, 16.0, 7.5, 180.0, None, "typical prepared dish", None),
    ("syrniki", 220.0, 14.0, 10.0, 18.0, 60.0, None, "typical prepared dish", None),
    ("pelmeni, cooked", 275.0, 12.0, 14.0, 25.0, 15.0, None, "typical prepared dish", None),
    ("vareniki, potato, cooked", 178.0, 4.4, 3.5, 32.0, 25.0, None, "typical prepared dish", None),
    ("blini", 227.0, 6.1, 9.2, 30.0, 45.0, None, "typical prepared dish", None),
    ("okroshka", 72.0, 3.5, 4.2, 5.0, 350.0, 1.0, "typical prepared dish", None),
    ("shchi", 42.0, 1.6, 2.1, 4.2, 350.0, 1.0, "typical prepared dish", None),
    ("solyanka", 69.0, 5.2, 4.6, 2.1, 350.0, 1.0, "typical prepared dish", None),
    ("beef stroganoff", 193.0, 13.0, 13.5, 5.5, 250.0, None, "typical prepared dish", None),
    ("cutlet, meat", 245.0, 16.0, 17.0, 8.0, 80.0, None, "typical prepared dish", None),
    (
        "mashed potatoes with milk",
        100.0,
        2.1,
        3.7,
        15.0,
        200.0,
        None,
        "typical prepared dish",
        None,
    ),
    (
        "buckwheat groats, roasted, cooked",
        92.0,
        3.38,
        0.62,
        19.94,
        None,
        None,
        "USDA SR Legacy",
        170686,
    ),
    (
        "bread, wheat",
        252.0,
        12.45,
        3.5,
        43.1,
        30.0,
        None,
        "USDA SR Legacy",
        172686,
    ),
    ("bread, rye", 259.0, 8.5, 3.3, 48.3, 30.0, None, "USDA SR Legacy", 172684),
    (
        "rice, white, long-grain, cooked",
        130.0,
        2.69,
        0.28,
        28.17,
        None,
        None,
        "USDA SR Legacy",
        168878,
    ),
    ("oatmeal, cooked", 71.0, 2.54, 1.52, 12.0, None, None, "USDA SR Legacy", 173904),
    ("pasta, cooked", 157.0, 5.8, 0.93, 30.9, None, None, "USDA SR Legacy", 168927),
    ("potatoes, boiled", 87.0, 1.87, 0.1, 20.13, 150.0, None, "USDA SR Legacy", 170438),
    ("chicken breast, roasted", 165.0, 31.02, 3.57, 0.0, 120.0, None, "USDA SR Legacy", 171477),
    ("beef, ground, cooked", 250.0, 25.93, 15.41, 0.0, None, None, "USDA SR Legacy", 174036),
    ("pork, cooked", 242.0, 27.32, 13.92, 0.0, None, None, "USDA SR Legacy", 167820),
    ("salmon, cooked", 206.0, 22.1, 12.35, 0.0, 140.0, None, "USDA SR Legacy", 175168),
    ("tuna, canned in water", 116.0, 25.51, 0.82, 0.0, None, None, "USDA SR Legacy", 175159),
    ("egg, whole, boiled", 155.0, 12.58, 10.61, 1.12, 50.0, None, "USDA SR Legacy", 173424),
    (
        "soy protein isolate",
        370.0,
        90.0,
        1.5,
        3.0,
        None,
        None,
        "user-specified/curated",
        None,
    ),
    ("milk, 3%", 60.0, 2.9, 3.0, 4.7, None, 1.03, "user-specified/curated", None),
    ("milk, whole", 61.0, 3.15, 3.25, 4.8, None, 1.03, "USDA SR Legacy", 171265),
    ("kefir, plain", 43.0, 3.79, 1.02, 4.77, None, 1.03, "USDA-derived", None),
    ("cottage cheese, 4% milkfat", 98.0, 11.12, 4.3, 3.38, None, None, "USDA SR Legacy", 172179),
    ("yogurt, plain, whole milk", 61.0, 3.47, 3.25, 4.66, 125.0, 1.03, "USDA SR Legacy", 171284),
    ("cheese, cheddar", 403.0, 22.87, 33.31, 3.37, 25.0, None, "USDA SR Legacy", 173414),
    ("butter", 717.0, 0.85, 81.11, 0.06, 10.0, None, "USDA SR Legacy", 173410),
    ("olive oil", 884.0, 0.0, 100.0, 0.0, 14.0, 0.91, "USDA SR Legacy", 171413),
    ("apple, raw, with skin", 52.0, 0.26, 0.17, 13.81, 182.0, None, "USDA SR Legacy", 171688),
    ("banana, raw", 89.0, 1.09, 0.33, 22.84, 118.0, None, "USDA SR Legacy", 173944),
    ("orange, raw", 47.0, 0.94, 0.12, 11.75, 131.0, None, "USDA SR Legacy", 169097),
    ("tomato, raw", 18.0, 0.88, 0.2, 3.89, 123.0, None, "USDA SR Legacy", 170457),
    ("cucumber, with peel, raw", 15.0, 0.65, 0.11, 3.63, 200.0, None, "USDA SR Legacy", 168409),
    ("carrots, raw", 41.0, 0.93, 0.24, 9.58, 61.0, None, "USDA SR Legacy", 170393),
    ("cabbage, raw", 25.0, 1.28, 0.1, 5.8, None, None, "USDA SR Legacy", 169975),
    ("onion, raw", 40.0, 1.1, 0.1, 9.34, 110.0, None, "USDA SR Legacy", 170000),
    ("avocado, raw", 160.0, 2.0, 14.66, 8.53, 150.0, None, "USDA SR Legacy", 171705),
    ("lentils, cooked", 116.0, 9.02, 0.38, 20.13, None, None, "USDA SR Legacy", 172421),
    ("chickpeas, cooked", 164.0, 8.86, 2.59, 27.42, None, None, "USDA SR Legacy", 173757),
    ("beans, kidney, cooked", 127.0, 8.67, 0.5, 22.8, None, None, "USDA SR Legacy", 173744),
    ("almonds", 579.0, 21.15, 49.93, 21.55, 1.2, None, "USDA SR Legacy", 170567),
    ("walnuts", 654.0, 15.23, 65.21, 13.71, 4.0, None, "USDA SR Legacy", 170187),
    ("sugar", 387.0, 0.0, 0.0, 99.98, 4.0, None, "USDA SR Legacy", 169655),
    ("honey", 304.0, 0.3, 0.0, 82.4, 21.0, 1.42, "USDA SR Legacy", 169640),
    ("coffee, brewed", 1.0, 0.12, 0.02, 0.0, None, 1.0, "USDA SR Legacy", 171890),
    ("tea, brewed", 1.0, 0.0, 0.0, 0.3, None, 1.0, "USDA SR Legacy", 171917),
]

COMMON_QUERIES = [
    "rice cooked",
    "rice brown",
    "oats",
    "barley cooked",
    "millet cooked",
    "quinoa cooked",
    "pasta cooked",
    "bread",
    "flour",
    "breakfast cereal",
    "potato",
    "sweet potato",
    "chicken cooked",
    "turkey cooked",
    "beef cooked",
    "pork cooked",
    "lamb cooked",
    "liver cooked",
    "salmon cooked",
    "tuna",
    "cod cooked",
    "shrimp cooked",
    "sardines",
    "egg cooked",
    "milk",
    "yogurt plain",
    "cheese",
    "cottage cheese",
    "cream",
    "butter",
    "beans cooked",
    "lentils cooked",
    "chickpeas cooked",
    "peas cooked",
    "tofu",
    "apple raw",
    "banana raw",
    "orange raw",
    "pear raw",
    "grapes raw",
    "berries raw",
    "peach raw",
    "plum raw",
    "melon raw",
    "pineapple raw",
    "mango raw",
    "tomato raw",
    "cucumber raw",
    "carrot raw",
    "cabbage raw",
    "broccoli cooked",
    "cauliflower cooked",
    "spinach cooked",
    "onion raw",
    "pepper raw",
    "mushrooms cooked",
    "avocado raw",
    "corn cooked",
    "beets cooked",
    "zucchini cooked",
    "eggplant cooked",
    "almonds",
    "walnuts",
    "peanuts",
    "sunflower seeds",
    "pumpkin seeds",
    "olive oil",
    "sugar",
    "honey",
    "chocolate",
    "jam",
    "coffee brewed",
    "tea brewed",
]


def nutrient_value(record: dict, nutrient_name: str) -> float:
    for nutrient in record.get("foodNutrients", []):
        detail = nutrient.get("nutrient", {})
        name = nutrient.get("nutrientName") or detail.get("name", "")
        unit = nutrient.get("unitName") or detail.get("unitName", "")
        if name.casefold() == nutrient_name.casefold():
            if nutrient_name == "Energy" and unit.casefold() not in {"kcal", ""}:
                continue
            return float(nutrient.get("value", nutrient.get("amount", 0)) or 0)
    return 0.0


def record_to_row(record: dict) -> tuple | None:
    kcal = nutrient_value(record, "Energy")
    if kcal <= 0:
        return None
    return (
        record["description"].casefold(),
        kcal,
        nutrient_value(record, "Protein"),
        nutrient_value(record, "Total lipid (fat)"),
        nutrient_value(record, "Carbohydrate, by difference"),
        None,
        None,
        f"USDA FDC {record.get('dataType', 'SR Legacy')}".strip(),
        record.get("fdcId"),
    )


def fetch_usda_foods(api_key: str, target: int) -> list[tuple]:
    rows = []
    session = requests.Session()
    # Broad queries keep rebuilds well below FDC rate limits; the curated rows above
    # ensure exact canonical names for the CLI's primary resolution vocabulary.
    for query in ("raw", "cooked", "bread"):
        for attempt in range(3):
            response = session.get(
                "https://api.nal.usda.gov/fdc/v1/foods/search",
                params={
                    "api_key": api_key,
                    "query": query,
                    "dataType": "SR Legacy",
                    "pageSize": 200,
                },
                timeout=30,
            )
            if response.status_code != 429 or attempt == 2:
                break
            time.sleep(2**attempt)
        response.raise_for_status()
        for record in response.json().get("foods", []):
            row = record_to_row(record)
            if row:
                rows.append(row)
        if len({row[0] for row in [*SEED_FOODS, *rows]}) >= target:
            break
    return rows


def load_usda_download(source: Path, target: int) -> list[tuple]:
    """Select a common-food subset from the official SR Legacy JSON download."""
    payload = json.loads(source.read_text())
    records = payload.get("SRLegacyFoods") or payload.get("FoundationFoods") or []
    selected: dict[str, tuple] = {}
    for query in COMMON_QUERIES:
        tokens = query.casefold().split()
        matches = [
            record
            for record in records
            if all(token in record.get("description", "").casefold() for token in tokens)
        ]
        matches.sort(key=lambda record: (len(record.get("description", "")), record["description"]))
        for record in matches[:8]:
            row = record_to_row(record)
            if row:
                selected.setdefault(row[0], row)
            names = {row[0].casefold() for row in SEED_FOODS} | set(selected)
            if len(names) >= target:
                return list(selected.values())
    return list(selected.values())


def synonym_rows_from_download(source: Path) -> tuple[list[tuple], list[str]]:
    """Create stable canonical rows for every synonym target from SR Legacy."""
    payload = json.loads(source.read_text())
    records = payload.get("SRLegacyFoods") or payload.get("FoundationFoods") or []
    synonyms = json.loads((ROOT / "nomnomcli" / "data" / "synonyms_ru.json").read_text())
    seeded_names = {row[0].casefold() for row in SEED_FOODS}
    rows = []
    unresolved = []
    ignored_tokens = {"cooked", "raw", "whole", "plain", "with", "in"}
    for target in sorted(set(synonyms.values()), key=str.casefold):
        if target.casefold() in seeded_names:
            continue
        tokens = [
            token.rstrip("s")
            for token in re.findall(r"[a-z]+", target.casefold())
            if token not in ignored_tokens
        ]

        def matches(record: dict, required_tokens: list[str] = tokens) -> bool:
            words = [
                word.rstrip("s") for word in re.findall(r"[a-z]+", record["description"].casefold())
            ]
            return all(
                any(word.startswith(token) or token.startswith(word) for word in words)
                for token in required_tokens
            )

        candidates = [record for record in records if matches(record)]
        desired_states = {state for state in ("raw", "cooked") if state in target.casefold()}
        candidates.sort(
            key=lambda record: (
                -sum(state in record["description"].casefold() for state in desired_states),
                len(record["description"]),
                record["description"],
            )
        )
        matched_record = next((record for record in candidates if record_to_row(record)), None)
        if not matched_record:
            unresolved.append(target)
            continue
        row = record_to_row(matched_record)
        assert row is not None
        source_name = matched_record["description"].replace("\n", " ")
        rows.append((target, *row[1:7], f"{row[7]} (canonicalized from {source_name})", row[8]))
    return rows, unresolved


def load_synonym_seed() -> list[tuple]:
    if not SYNONYM_SEED.exists():
        return []
    return [tuple(row) for row in json.loads(SYNONYM_SEED.read_text())]


def load_curated_overrides() -> list[tuple]:
    """Load reviewed v0.2 profiles that replace known bad canonicalized rows."""
    source = "USDA-like reference profile (v0.2 curated)"
    return [
        (*tuple(row), source, None)
        for row in json.loads(CURATED_OVERRIDES.read_text(encoding="utf-8"))
    ]


def load_existing_database(path: Path) -> list[tuple]:
    """Read the tracked corpus before applying deterministic offline corrections."""
    if not path.exists():
        return []
    with sqlite3.connect(path) as connection:
        return connection.execute(
            """SELECT name, kcal, protein, fat, carbs, piece_grams, density_g_ml, source, fdc_id
            FROM foods"""
        ).fetchall()


def build_database(output: Path, rows: list[tuple]) -> int:
    unique = {row[0].casefold(): row for row in rows}
    # Curated rows win so synonyms and deterministic piece weights remain stable.
    unique.update({row[0].casefold(): row for row in SEED_FOODS})
    # Reviewed overrides win over both imported data and the legacy synonym seed.
    unique.update({row[0].casefold(): row for row in load_curated_overrides()})
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False
    ) as handle:
        temporary_output = Path(handle.name)
    try:
        with sqlite3.connect(temporary_output) as connection:
            connection.executescript(SCHEMA)
            connection.executemany(
                "INSERT INTO foods VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                sorted(unique.values(), key=lambda row: row[0].casefold()),
            )
        temporary_output.chmod(0o644)
        os.replace(temporary_output, output)
    finally:
        temporary_output.unlink(missing_ok=True)
    return len(unique)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--target", type=int, default=300)
    parser.add_argument(
        "--source-json", type=Path, help="use an official downloaded FDC JSON archive payload"
    )
    parser.add_argument(
        "--export-synonym-seed",
        type=Path,
        help="with --source-json, export canonical synonym rows for maintainer review",
    )
    parser.add_argument(
        "--seed-only", action="store_true", help="build only curated rows (for offline development)"
    )
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="apply curated corrections to the existing bundled corpus without network access",
    )
    args = parser.parse_args()
    rows = []
    if args.update_existing:
        rows = load_existing_database(args.output)
        if not rows:
            print(f"existing database is required: {args.output}", file=sys.stderr)
            return 2
    elif args.source_json:
        rows = load_usda_download(args.source_json, args.target)
        synonym_rows, unresolved = synonym_rows_from_download(args.source_json)
        rows.extend(synonym_rows)
        if args.export_synonym_seed:
            args.export_synonym_seed.write_text(
                json.dumps(synonym_rows, ensure_ascii=False, indent=2) + "\n"
            )
        if unresolved:
            print("unresolved synonym targets: " + ", ".join(unresolved), file=sys.stderr)
    elif not args.seed_only:
        api_key = os.getenv("NOMNOM_USDA_KEY")
        if not api_key:
            print("NOMNOM_USDA_KEY is required (or use --seed-only)", file=sys.stderr)
            return 2
        rows = fetch_usda_foods(api_key, args.target)
    rows.extend(load_synonym_seed())
    count = build_database(args.output, rows)
    print(f"wrote {count} foods to {args.output} ({args.output.stat().st_size} bytes)")
    if not args.seed_only and count < args.target:
        print(f"warning: target was {args.target}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
