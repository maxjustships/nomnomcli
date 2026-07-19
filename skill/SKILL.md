---
name: nomnomcli
description: >-
  Runtime calorie and nutrition tracking. Use when the user asks to track food,
  calculate calories or macros, import a recipe, or review daily/weekly totals.
---

# nomnomcli

Use `nomnom` as the only source of nutrition numbers. Never estimate calories,
macros, weights, or serving conversions in the agent context.

## Install

If `nomnom --help` is unavailable, ask permission and run:

```sh
curl -sL https://raw.githubusercontent.com/maxjustships/nomnomcli/main/install.sh | sh
```

## Log free text

1. Preserve every food and quantity the user supplied.
2. Run `nomnom log --parse "FOOD QUANTITY, FOOD QUANTITY" --json`.
3. Show returned canonical names, grams, confidence, totals, `alternatives`, and
   every `assumptions` entry.
4. Ask the user to confirm the resolution before relying on it.

Successful logs are stored immediately. Do not silently correct or rerun one;
tell the user before creating a replacement entry.

Supported dish prefixes split only named ingredients. Never add oil or another
missing ingredient. Size words are parser syntax; piece grams must come from the
resolved food record. If the record has no piece weight, ask for grams.

## Direct food flow

When the user gives one clear food and a measured weight:

```sh
nomnom log --food "chickpeas, cooked" --grams 150 --json
```

Always use the human's weight.

## Unknown-food workflow: OFF → USDA → add → error

The CLI automatically checks exact cache, cache search, then Open Food Facts.
For an unresolved food:

1. Let OFF run. For `off_low_confidence`, show its `candidate` and
   `alternatives`; do not accept one without the user's explicit choice.
2. Let USDA run only when `NOMNOM_USDA_KEY` is configured. For
   `usda_key_required`, offer the free-key setup URL returned in `details` and
   ask the user to set the environment variable.
3. If the user has verified label values, manually pin them:

   ```sh
   nomnom add --name NAME --brand BRAND --kcal KCAL \
     --protein PROTEIN --fat FAT --carbs CARBS --piece-grams GRAMS --json
   ```

   Omit `--piece-grams` when the label does not provide a serving weight.
4. If OFF, USDA, and a verified manual pin cannot resolve the food, report the
   structured error. Never substitute a similar food or invent values.

Other error handling:

- `quantity_required`: ask for grams, millilitres, or a supported piece count.
- `piece_weight_unknown`: ask for grams, then retry with `--food --grams`.
- `openfoodfacts_unavailable` / `usda_unavailable`: say that nothing was
  estimated; offer retry or a verified manual pin.

## Stats

```sh
nomnom stats today --json
nomnom stats week --json
```

Summarize only returned values.

## Recipes

```sh
nomnom recipe add "https://example.com/recipe" --servings 4 --json
nomnom recipe log "Recipe name" --portions 1.5 --json
```

Show resolved ingredients and servings. If any ingredient fails, ask for
clarification; never complete recipe math yourself.

## Hard rule

If `nomnom` cannot produce a nutrition value, say it is unresolved. Never
estimate nutrition in the agent context.
