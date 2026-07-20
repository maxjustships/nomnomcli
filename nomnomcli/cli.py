from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence

from nomnomcli import __version__
from nomnomcli.db import connect, get_stats, store_log
from nomnomcli.errors import NomnomError
from nomnomcli.foods import FoodRepository
from nomnomcli.models import scale_food, total_items
from nomnomcli.onboarding import doctor_report, setup_providers
from nomnomcli.parser import parse_free_text
from nomnomcli.recipes import fetch_recipe, recipe_portion, save_recipe


def _json_output(payload: dict | list) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def _nutrition_line(totals: dict) -> str:
    return (
        f"{totals['kcal']:.2f} kcal | "
        f"P {totals['protein']:.2f} g | F {totals['fat']:.2f} g | C {totals['carbs']:.2f} g"
    )


def _print_log(result: dict, as_json: bool) -> None:
    if as_json:
        print(_json_output(result))
        return
    print("Logged:")
    for item in result["items"]:
        print(f"  {item['name']:<38} {item['grams']:>8.2f} g  {item['kcal']:>8.2f} kcal")
    if result.get("assumptions"):
        print("Assumptions:")
        for assumption in result["assumptions"]:
            print(f"  - {assumption}")
    print(f"Total: {_nutrition_line(result['totals'])}")


def _print_stats(result: dict, as_json: bool) -> None:
    if as_json:
        print(_json_output(result))
        return
    print(f"Nutrition for {result['period']} (from {result['from']}):")
    if not result["meals"]:
        print("  No meals logged.")
    for meal in result["meals"]:
        label = meal["label"] or ", ".join(item["name"] for item in meal["items"])
        print(f"  {meal['logged_at']}  {label}  {_nutrition_line(meal['totals'])}")
    print(f"Total: {_nutrition_line(result['totals'])}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nomnom", description="Deterministic, agent-first nutrition tracking"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("setup", help="configure and validate nutrition providers")

    doctor = commands.add_parser("doctor", help="probe provider readiness")
    doctor.add_argument("--json", action="store_true", help="machine-readable JSON output")

    log = commands.add_parser("log", help="resolve and store food")
    form = log.add_mutually_exclusive_group(required=True)
    form.add_argument("--parse", metavar="TEXT", help="comma-separated food phrases")
    form.add_argument("--food", metavar="NAME", help="food name for direct logging")
    log.add_argument("--grams", type=float, help="grams for --food")
    log.add_argument("--json", action="store_true", help="machine-readable JSON output")

    stats = commands.add_parser("stats", help="show nutrition totals")
    stats.add_argument("period", choices=("today", "week"))
    stats.add_argument("--json", action="store_true", help="machine-readable JSON output")

    search = commands.add_parser("search", help="search the user food cache")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--json", action="store_true", help="machine-readable JSON output")

    add = commands.add_parser("add", help="pin a branded product in the user cache")
    add.add_argument("--name", required=True)
    add.add_argument("--brand", required=True)
    add.add_argument("--kcal", type=float, required=True)
    add.add_argument("--protein", type=float, required=True)
    add.add_argument("--fat", type=float, required=True)
    add.add_argument("--carbs", type=float, required=True)
    add.add_argument("--piece-grams", type=float)
    add.add_argument("--json", action="store_true", help="machine-readable JSON output")

    alias = commands.add_parser("alias", help="manage user food aliases")
    alias_commands = alias.add_subparsers(dest="alias_command", required=True)
    alias_add = alias_commands.add_parser("add", help="map a phrase to a cached food")
    alias_add.add_argument("phrase")
    alias_add.add_argument("canonical_food_name")
    alias_add.add_argument("--json", action="store_true", help="machine-readable JSON output")
    alias_list = alias_commands.add_parser("list", help="list user food aliases")
    alias_list.add_argument("--json", action="store_true", help="machine-readable JSON output")
    alias_remove = alias_commands.add_parser("remove", help="remove a user food alias")
    alias_remove.add_argument("phrase")
    alias_remove.add_argument("--json", action="store_true", help="machine-readable JSON output")

    recipe = commands.add_parser("recipe", help="import and log recipes")
    recipe_commands = recipe.add_subparsers(dest="recipe_command", required=True)
    recipe_add = recipe_commands.add_parser("add", help="import schema.org Recipe from a URL")
    recipe_add.add_argument("url")
    recipe_add.add_argument("--servings", type=float)
    recipe_add.add_argument("--json", action="store_true", help="machine-readable JSON output")
    recipe_log = recipe_commands.add_parser("log", help="log portions of a stored recipe")
    recipe_log.add_argument("name")
    recipe_log.add_argument("--portions", type=float, default=1.0)
    recipe_log.add_argument("--json", action="store_true", help="machine-readable JSON output")
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "setup":
        print("Open Food Facts: free, no account or key; branded packaged foods.")
        print("USDA FoodData Central: free API key; generic/raw foods and fallback.")
        print("USDA signup: https://fdc.nal.usda.gov/api-key-signup.html")
        result = setup_providers(interactive=sys.stdin.isatty())
        off_product_status = (
            "reachable"
            if result["providers"]["openfoodfacts"]["product_lookup_reachable"]
            else "unreachable"
        )
        off_search_status = (
            "ready"
            if result["providers"]["openfoodfacts"]["full_text_search_ready"]
            else "unavailable"
        )
        print(f"Open Food Facts product/barcode lookup (no key): {off_product_status}")
        print(f"Open Food Facts full-text resolution: {off_search_status}")
        print("Product reachability does not imply full-text readiness.")
        print(
            "USDA: reachable; key source "
            f"{result['providers']['usda']['key_source']}"
        )
        if result.get("config_path"):
            print(f"Saved secure provider config: {result['config_path']} (0600)")
        return 0

    if args.command == "doctor":
        result = doctor_report()
        if args.json:
            print(_json_output(result))
        else:
            for provider, status in result["providers"].items():
                if provider == "openfoodfacts":
                    product_state = (
                        "reachable" if status["product_lookup_reachable"] else "unreachable"
                    )
                    search_state = (
                        "ready" if status["full_text_search_ready"] else "unavailable"
                    )
                    print(f"openfoodfacts product/barcode lookup: {product_state}")
                    print(f"openfoodfacts full-text resolution: {search_state}")
                    continue
                state = "reachable" if status["reachable"] else "unreachable"
                print(f"{provider}: {state}")
        return 0

    with connect() as connection:
        repository = FoodRepository(connection)
        if args.command == "alias":
            if args.alias_command == "add":
                result = repository.add_alias(args.phrase, args.canonical_food_name)
                if args.json:
                    print(_json_output(result))
                else:
                    print(
                        f"Alias added: {result['phrase']} -> "
                        f"{result['canonical_food_name']}"
                    )
                return 0
            if args.alias_command == "list":
                result = repository.list_aliases()
                if args.json:
                    print(_json_output(result))
                elif result:
                    for alias in result:
                        print(f"{alias['phrase']} -> {alias['canonical_food_name']}")
                else:
                    print("No aliases.")
                return 0
            result = repository.remove_alias(args.phrase)
            if args.json:
                print(_json_output(result))
            else:
                print(f"Alias removed: {result['phrase']}")
            return 0

        if args.command == "add":
            nutrients = (args.kcal, args.protein, args.fat, args.carbs)
            if not args.name.strip() or not args.brand.strip():
                raise NomnomError("invalid_product", "Name and brand must not be empty")
            if any(not math.isfinite(value) or value < 0 for value in nutrients):
                raise NomnomError(
                    "invalid_nutrition", "Nutrition values must be finite and non-negative"
                )
            if args.piece_grams is not None and (
                not math.isfinite(args.piece_grams) or args.piece_grams <= 0
            ):
                raise NomnomError(
                    "invalid_piece_grams", "Piece grams must be finite and greater than zero"
                )
            food = repository.add_food(
                name=args.name,
                brand=args.brand,
                kcal=args.kcal,
                protein=args.protein,
                fat=args.fat,
                carbs=args.carbs,
                piece_grams=args.piece_grams,
            )
            result = {
                "name": food.name,
                "brand": food.brand,
                "source": food.source,
                "kcal_per_100g": round(food.kcal, 2),
                "protein_per_100g": round(food.protein, 2),
                "fat_per_100g": round(food.fat, 2),
                "carbs_per_100g": round(food.carbs, 2),
                "piece_grams": food.piece_grams,
            }
            if args.json:
                print(_json_output(result))
            else:
                print(f"Pinned: {food.name} ({food.kcal:.2f} kcal/100g)")
            return 0

        if args.command == "log":
            if args.food:
                if args.grams is None:
                    raise NomnomError("grams_required", "--grams is required with --food")
                if args.grams <= 0:
                    raise NomnomError("invalid_quantity", "Grams must be greater than zero")
                food, confidence = repository.resolve(args.food)
                resolved = [scale_food(food, args.grams, confidence)]
            else:
                if args.grams is not None:
                    raise NomnomError("invalid_arguments", "--grams can only be used with --food")
                resolved = parse_free_text(args.parse, repository)
            items = [item.to_dict() for item in resolved]
            totals = total_items(resolved)
            log_id = store_log(connection, items, totals)
            result = {"items": items, "totals": totals, "log_id": log_id}
            assumptions = [item["assumption"] for item in items if item.get("assumption")]
            if assumptions:
                result["assumptions"] = assumptions
            _print_log(result, args.json)
            return 0

        if args.command == "stats":
            _print_stats(get_stats(connection, args.period), args.json)
            return 0

        if args.command == "search":
            if args.limit <= 0:
                raise NomnomError("invalid_limit", "Limit must be greater than zero")
            foods = repository.search(args.query, args.limit)
            result = [
                {
                    "name": food.name,
                    "kcal_per_100g": round(food.kcal, 2),
                    "protein_per_100g": round(food.protein, 2),
                    "fat_per_100g": round(food.fat, 2),
                    "carbs_per_100g": round(food.carbs, 2),
                }
                for food in foods
            ]
            if args.json:
                print(_json_output(result))
            else:
                for food in result:
                    print(f"{food['name']:<45} {food['kcal_per_100g']:>8.2f} kcal/100g")
            return 0

        if args.recipe_command == "add":
            if args.servings is not None and args.servings <= 0:
                raise NomnomError("invalid_servings", "Servings must be greater than zero")
            result = fetch_recipe(args.url, repository, args.servings)
            save_recipe(connection, result)
            if args.json:
                print(_json_output(result))
            else:
                print(f"Saved recipe: {result['name']} ({result['servings']:.2f} servings)")
                print(f"Per serving: {_nutrition_line(result['per_serving'])}")
            return 0

        if args.recipe_command == "log":
            result = recipe_portion(connection, args.name, args.portions)
            result["log_id"] = store_log(
                connection,
                result["items"],
                result["totals"],
                kind="recipe",
                label=result["recipe"],
            )
            _print_log(result, args.json)
            return 0
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except NomnomError as exc:
        print(_json_output(exc.as_dict()), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        error = {"error": {"code": "interrupted", "message": "Interrupted"}}
        print(_json_output(error), file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
