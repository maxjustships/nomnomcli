from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from nomnomcli import __version__
from nomnomcli.db import connect, get_stats, store_log
from nomnomcli.errors import NomnomError
from nomnomcli.foods import FoodRepository
from nomnomcli.models import scale_food, total_items
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

    log = commands.add_parser("log", help="resolve and store food")
    form = log.add_mutually_exclusive_group(required=True)
    form.add_argument("--parse", metavar="TEXT", help="comma-separated food phrases")
    form.add_argument("--food", metavar="NAME", help="food name for direct logging")
    log.add_argument("--grams", type=float, help="grams for --food")
    log.add_argument("--json", action="store_true", help="machine-readable JSON output")

    stats = commands.add_parser("stats", help="show nutrition totals")
    stats.add_argument("period", choices=("today", "week"))
    stats.add_argument("--json", action="store_true", help="machine-readable JSON output")

    search = commands.add_parser("search", help="search the offline food database")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--json", action="store_true", help="machine-readable JSON output")

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
    with connect() as connection:
        repository = FoodRepository(connection)
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
