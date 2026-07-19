# nomnomcli

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![CI](https://github.com/maxjustships/nomnomcli/actions/workflows/ci.yml/badge.svg)](https://github.com/maxjustships/nomnomcli/actions/workflows/ci.yml)

**Precise calorie tracking for agents—nutrition math belongs in code, not in a prompt.**

`nomnomcli` is an offline-first nutrition ledger for agent workflows. A person can describe
a meal in their own language; their agent translates that into a `nomnom` command, then
narrates the deterministic JSON. Food matching, unit conversion, macro arithmetic, and
persistence all happen inside the CLI against SQLite. There is no LLM in the program.

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
nomnom log --parse "borscht 300g, bread 2 pieces, cooked buckwheat 150g" --json
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

Supported quantity units include kilograms, grams (`g`, `grams`), millilitres (`ml`),
and pieces (`piece`, `pieces`, `pc`, `pcs`). The parser also ships language-specific aliases
and accepts localized unit forms; agents may translate natural-language input into these stable
commands. Piece conversion only works for foods with a deterministic bundled piece weight.
Millilitres use a bundled density when available and otherwise the documented water-equivalent
default of 1 g/ml. An explicit per-piece weight always wins, so both `bread 2 pieces at 40g`
and `egg 3 pieces at 50g` multiply the supplied count by the supplied grams.

Size descriptors and fractions use the packaged deterministic table below. Built-in English
forms include `small`, `medium`, and `large`; language-specific aliases (including Russian
inflections) are supported by the parser without making a particular language the public API.
Fractions include `half`, `1/2`, and `quarter`.

| Food | Small | Medium | Large |
| --- | ---: | ---: | ---: |
| Egg | 45 g | 55 g | 65 g |
| Tomato | 60 g | 100 g | 150 g |
| Onion | 50 g | 80 g | 120 g |
| Apple | 149 g | 182 g | 223 g |
| Banana | 101 g | 118 g | 136 g |
| Orange | 96 g | 131 g | 184 g |
| Potato | 130 g | 173 g | 299 g |
| Carrot | 50 g | 61 g | 72 g |
| Cucumber | 150 g | 200 g | 280 g |
| Pepper | 74 g | 119 g | 164 g |

These are transparent portion assumptions, not measured weights. JSON adds `assumed`,
`assumption`, and a top-level `assumptions` list only where relevant; human-readable output prints
the same assumptions. Supported dish prefixes are intentionally data-driven; the current
built-ins include omelette, salad, and porridge equivalents. The CLI calculates only ingredients
that were stated and never silently adds oil.

Direct logging is useful after the human clarifies an unresolved item:

```sh
nomnom log --food "buckwheat" --grams 150 --json
```

Unknown foods fail with a non-zero exit and a JSON error; the CLI never substitutes invented
nutrition values.

### Branded products and offline pinning

Resolution order is exact local data, local search, Open Food Facts, then an actionable error
(with the existing opt-in USDA fallback retained when `NOMNOM_USDA_KEY` is set). A named brand is
never silently replaced by a bundled generic food. OFF uses its v2 search endpoint with a
10-second timeout; successful per-100g results are cached in the user database with source,
brand, and barcode. If OFF returns several relevant products, the first result follows OFF's
relevance order and JSON includes the remaining `alternatives` additively.

Network, HTTP, and malformed-response failures return stable error JSON without estimating
nutrition. Set `NOMNOM_OFFLINE=1` to disable all remote fallback, or
`NOMNOM_DISABLE_OFF=1` to disable OFF while retaining an explicitly configured USDA fallback.
Pin the values from a product label to make a branded product available offline:

```sh
nomnom add \
  --name "whole-grain bread" --brand "Example Bakery" \
  --kcal 250 --protein 9 --fat 4 --carbs 45 \
  --piece-grams 40 --json
nomnom log --parse "whole-grain bread Example Bakery 2 pieces" --json
```

All nutrition arguments to `nomnom add` are per 100 g. `--piece-grams` is optional; supplied
values must be finite and non-negative, while a piece weight must be greater than zero.

### Stats and search

```sh
nomnom stats today
nomnom stats week --json
nomnom search "cottage cheese" --json
```

Stats include totals and each stored meal. User data defaults to
`~/.local/share/nomnomcli/nomnom.sqlite3`; set `NOMNOM_DB_PATH` to choose another database.

### Upgrading

User database schema migrations run automatically when `nomnom` opens the database. Existing
logs, cached foods, and recipes are upgraded in place and are never reset or recreated.

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
- Open Food Facts is the default fallback for an otherwise unresolved log/direct-food query.
  Its product data is licensed by OFF and normalized from the returned per-100g nutriments.
- Set `NOMNOM_USDA_KEY` to retain the opt-in FoodData Central fallback. Successful remote results
  are cached in the user database. Search, stats, and recipe-log commands remain local-only;
  recipe import fetches its requested URL.
- The descriptor table is a reviewed set of USDA-average-like edible-piece weights stored in
  `nomnomcli/data/piece_weights.json`. Bundled regional dishes and the v0.2 replacement profiles
  are explicitly labelled typical/USDA-like reference values rather than fabricated USDA IDs.

For best results, weigh the edible portion and use a specific food description. Treat typical
dish rows as transparent defaults and add a real recipe when ingredient-level precision matters.

## Design decisions

- **`argparse`, not Click:** keeps the runtime dependency list to `requests` only.
- **Stdlib JSON-LD parsing, not `recipe-scrapers`:** schema.org recipes are sufficient for v0.1;
  unsupported or malformed sites fail explicitly instead of adding a large parser dependency.
- **Two SQLite databases:** shipped foods are immutable package data; user logs, recipes, and USDA
  cache remain in a writable local database.
- **Constrained parser:** v0.2 accepts explicit comma-separated phrases plus documented dish
  prefixes, conjunctions, size descriptors, fractions, and per-piece grams rather than pretending
  to understand arbitrary prose.
- **Immediate successful logs:** the agent shows the returned resolution for confirmation, but v0.2
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
rate-limit-free build. Apply the checked-in v0.2 corrections deterministically to the tracked
431-food corpus without network access:

```sh
python scripts/build_mini_db.py --update-existing
```

The reviewed overrides live in `scripts/food_overrides.json`; the generated package database is
`nomnomcli/data/foods.sqlite`. CI runs pytest and Ruff on Python 3.11 and 3.12.

## License

GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
