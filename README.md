# nomnomcli

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![CI](https://github.com/maxjustships/nomnomcli/actions/workflows/ci.yml/badge.svg)](https://github.com/maxjustships/nomnomcli/actions/workflows/ci.yml)

**Precise calorie tracking for agents—nutrition math belongs in code, not in a prompt.**

`nomnomcli` is an offline-first nutrition ledger for agent workflows. A person can say
“я съел борщ 300г и два куска хлеба”; their agent translates that into a `nomnom` command,
then narrates the deterministic JSON. Food matching, unit conversion, macro arithmetic,
and persistence all happen inside the CLI against SQLite. There is no LLM in the program.

## Install

Agent-friendly one-liner:

```sh
curl -sL https://raw.githubusercontent.com/maxjustships/nomnomcli/main/install.sh | sh
```

The installer requires Python 3.11+, prefers `pipx`, falls back to user-site `pip`, and installs
the Hermes skill when `~/.hermes` exists. Preview every action without changing anything:

```sh
curl -sL https://raw.githubusercontent.com/maxjustships/nomnomcli/main/install.sh | sh -s -- --dry-run
```

From source:

```sh
git clone https://github.com/maxjustships/nomnomcli
cd nomnomcli
python3 -m pip install -e .
nomnom --help
```

## Use it

Human-readable tables are the default. Add `--json` to any command for stable machine output.

### Log free text

```sh
nomnom log --parse "борщ 300г, хлеб 2 куска, гречка 150 г" --json
```

```json
{
  "items": [
    {"carbs": 19.2, "fat": 6.3, "grams": 300.0, "kcal": 165.0, "match_confidence": 0.98, "name": "borscht", "protein": 7.5},
    {"carbs": 25.86, "fat": 2.1, "grams": 60.0, "kcal": 151.2, "match_confidence": 0.98, "name": "bread, wheat", "protein": 7.47},
    {"carbs": 29.91, "fat": 0.93, "grams": 150.0, "kcal": 138.0, "match_confidence": 0.98, "name": "buckwheat groats, roasted, cooked", "protein": 5.07}
  ],
  "log_id": 1,
  "totals": {"carbs": 74.97, "fat": 9.33, "kcal": 454.2, "protein": 20.04}
}
```

Supported quantity units are kilograms, grams (`g`, `grams`, `г`, `гр`, `грамм`),
millilitres (`ml`, `мл`), and pieces (`pieces`, `pcs`, `шт`, `куска`). Piece conversion only
works for foods with a deterministic bundled piece weight. Millilitres use a bundled density
when available and otherwise the documented v0.1 water-equivalent default of 1 g/ml.

Direct logging is useful after the human clarifies an unresolved item:

```sh
nomnom log --food "buckwheat" --grams 150 --json
```

Unknown foods fail with a non-zero exit and a JSON error; the CLI never substitutes invented
nutrition values.

### Stats and search

```sh
nomnom stats today
nomnom stats week --json
nomnom search "творог" --json
```

Stats include totals and each stored meal. User data defaults to
`~/.local/share/nomnomcli/nomnom.sqlite3`; set `NOMNOM_DB_PATH` to choose another database.

### Recipes

`recipe add` is the only normal command that fetches an arbitrary URL. It parses a
schema.org `Recipe` JSON-LD block with the standard library, resolves each ingredient through
the same food database, and stores deterministic per-serving nutrition.

```sh
nomnom recipe add "https://example.com/buckwheat-recipe" --servings 4 --json
nomnom recipe log "Buckwheat and Eggs" --portions 1.5 --json
```

Ingredients need an explicit supported quantity and unit. If one cannot be resolved, the
entire import fails clearly instead of saving a partial recipe.

## Agent skill

The Hermes-format skill lives at [`skill/SKILL.md`](skill/SKILL.md). The installer copies it to
`~/.hermes/skills/nomnomcli/SKILL.md` when Hermes is present. To install it manually:

```sh
mkdir -p ~/.hermes/skills/nomnomcli
cp skill/SKILL.md ~/.hermes/skills/nomnomcli/SKILL.md
```

The skill teaches agents to call the CLI, show resolved names and weights for confirmation,
clarify unresolved foods, and never estimate nutrition in their context.

## How precise is it?

The arithmetic is exact for the selected database row and quantity; the real-world input is
still an estimate. Brand, recipe, cooking loss, portion measurement, and natural food variation
can all matter more than decimal places.

- The bundled sub-100 KB mini database contains 431 common foods. Most rows are selected from USDA
  FoodData Central SR Legacy; common regional prepared dishes such as borscht, plov, and Olivier
  salad use clearly labelled representative per-100g profiles.
- The Russian layer contains more than 200 everyday aliases. A synonym chooses a canonical food;
  it does not claim that every homemade version has identical nutrition.
- Set `NOMNOM_USDA_KEY` to opt into FoodData Central fallback for an otherwise uncached food.
  Successful results are cached in the user database. With no key, all food lookup is offline.
- Network access never happens during ordinary log, search, stats, or recipe-log commands.

For best results, weigh the edible portion and use a specific food description. Treat typical
dish rows as transparent defaults and add a real recipe when ingredient-level precision matters.

## Design decisions

- **`argparse`, not Click:** keeps the runtime dependency list to `requests` only.
- **Stdlib JSON-LD parsing, not `recipe-scrapers`:** schema.org recipes are sufficient for v0.1;
  unsupported or malformed sites fail explicitly instead of adding a large parser dependency.
- **Two SQLite databases:** shipped foods are immutable package data; user logs, recipes, and USDA
  cache remain in a writable local database.
- **Comma-separated parser:** v0.1 deliberately accepts constrained phrases rather than pretending
  to understand arbitrary prose. Agents should normalize speech into explicit item phrases.
- **Immediate successful logs:** the agent shows the returned resolution for confirmation, but v0.1
  does not implement a pending/confirm transaction state.

## Development

```sh
python -m pip install -e '.[dev]'
pytest
ruff check .
```

Regenerate the bundled database from the USDA API:

```sh
NOMNOM_USDA_KEY=your-key python scripts/build_mini_db.py
```

Maintainers can also pass `--source-json` with the official SR Legacy JSON download for a
rate-limit-free build. CI runs pytest and Ruff on Python 3.11 and 3.12.

## License

GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
