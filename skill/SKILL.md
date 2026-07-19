---
name: nomnomcli
description: >-
  Deterministic calorie and nutrition tracking. Use when the user asks to
  "трекать калории", "посчитай калории", "что я сегодня ел", log food,
  import a recipe, or review daily/weekly macros.
---

# nomnomcli

Use `nomnom` as the only source of nutrition numbers. Never estimate calories,
macros, weights, or serving conversions in the agent context.

## Install

If `nomnom --help` is unavailable, ask permission and run:

```sh
curl -sL https://raw.githubusercontent.com/maxjustships/nomnomcli/main/install.sh | sh
```

## Log free text: parse, show, confirm

1. Convert the user's foods into a comma-separated string while preserving the
   quantities they supplied.
2. Run `nomnom log --parse "борщ 300г, хлеб 2 куска" --json`.
3. Show the resolved canonical names, grams, and totals returned by the CLI.
4. Show every returned `assumptions` entry (for example, `small egg = 45g`) and
   any branded `alternatives` before asking the user to confirm the resolution.

The v0.2 CLI stores successful logs immediately, so do not silently change or
rerun a successful entry. Clearly tell the user before any corrective re-log.

Supported dish prefixes (`яичница из`, `омлет из`, `салат из`, `каша из`) are
decomposed into the ingredients the user named. Never add oil or another missing
ingredient. Size/fraction weights are CLI assumptions, not measured amounts.

## Direct food flow

When the user gives one unambiguous food and a weight, or after clarification:

```sh
nomnom log --food "buckwheat" --grams 150 --json
```

Always use the human's weight. Do not invent grams for a serving.

## Unresolved input

The CLI exits non-zero and returns a JSON `error` object. Read its `code`,
`message`, and `details`.

- `food_not_found`: ask what exact food/product they meant. Search with
  `nomnom search "query" --json`, then retry with the selected name. For a
  branded product, offer to pin label values using `nomnom add --name NAME
  --brand BRAND --kcal ... --protein ... --fat ... --carbs ...`.
- `quantity_required`: ask for grams, millilitres, or a supported piece count.
- `piece_weight_unknown`: ask for grams, then retry using `--food --grams`.
- Any Open Food Facts/USDA error: explain that nothing was estimated and ask
  whether to retry or pin the product-label values with `nomnom add`.

Do not replace an unresolved food with a merely similar food without explicit
human approval.

## Stats

Use machine output and summarize only returned values:

```sh
nomnom stats today --json
nomnom stats week --json
```

## Recipes

Import a schema.org recipe from a URL, show its resolution, and ask the human to
check ingredients and servings:

```sh
nomnom recipe add "https://example.com/recipe" --json
nomnom recipe add "https://example.com/recipe" --servings 4 --json
```

Then log an eaten amount by stored recipe name:

```sh
nomnom recipe log "Recipe name" --portions 1.5 --json
```

If an ingredient cannot be resolved, ask for clarification. Never complete
recipe math yourself.

## Hard rule

If `nomnom` cannot produce a nutrition value, say that the value is unresolved.
Never estimate nutrition in the agent context.
