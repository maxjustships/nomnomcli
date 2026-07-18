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
4. Ask the user to confirm that the resolution and weights are correct before
   treating or narrating the entry as final.

The v0.1 CLI stores successful logs immediately, so do not silently change or
rerun a successful entry. Clearly tell the user before any corrective re-log.

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
  `nomnom search "query" --json`, then retry with the selected name.
- `quantity_required`: ask for grams, millilitres, or a supported piece count.
- `piece_weight_unknown`: ask for grams, then retry using `--food --grams`.
- Any network/API error: explain that nothing was estimated and ask whether to
  retry or choose an offline database match.

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
