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

Before the first food log, run setup in the user's interactive terminal, then verify readiness:

```sh
nomnom setup
nomnom doctor --json
```

Explain only actionable results. Open Food Facts is keyless. USDA signup is at
<https://fdc.nal.usda.gov/api-key-signup.html>; setup validates before writing the key to the
owner-only XDG user config (`0600`). Credentials stay local and must never enter the repository,
database, shell history, agent transcript, or logs. `NOMNOM_USDA_KEY` is the non-interactive option
and overrides stored config.

## Log free text

1. Preserve every food and quantity the user supplied.
2. Translate each item to the language-agnostic contract: food name + quantity +
   unit + optional modifiers. Translate language, not nutrition.
3. Run `nomnom log --parse "FOOD QUANTITY UNIT, FOOD QUANTITY UNIT" --json`.
4. Show returned canonical names, grams, confidence, totals, `alternatives`, and
   every `assumptions` entry.
5. Ask the user to confirm the resolution before relying on it.

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

## Exact package capture

When an exact packaged food is needed, do not substitute a generic food or ask the human to look up
label numbers manually. Ask for the barcode first, or request a clear package photo when the barcode
is unavailable or incomplete in Open Food Facts.

```sh
nomnom capture barcode "BARCODE" --json
```

Barcode capture uses the OFF v2 product endpoint only. If it returns `invalid_barcode`,
`barcode_not_found`, or `barcode_nutrition_incomplete`, request a package photo. Read the product
name, brand, per-100 g kcal/protein/fat/carbs, and optional serving grams from the supplied image,
then run:

```sh
nomnom capture label --name NAME --brand BRAND \
  --kcal KCAL --protein PROTEIN --fat FAT --carbs CARBS \
  --serving-grams GRAMS --source-note "image:LOCAL_REFERENCE" --json
```

Omit `--brand` or `--serving-grams` only when the label does not provide them. `--source-note` is
always required and must be a nonempty local/opaque reference to the supplied image or barcode.
Vision/OCR remains agent-side: never pass the photo to nomnom, and never store image content or
invent a missing value. A successful capture returns `resolution_mode=exact_product`, source id,
source note, and provenance. Use its exact returned `name` for an alias or later log.

## User aliases

When the user wants a durable phrase for an exact food already in their local
cache:

```sh
nomnom alias add "USER PHRASE" "EXACT CACHED FOOD NAME" --json
```

Aliases are user-database records, never packaged translations. They resolve
only to exact local cache names and must not invent, approximate, or remotely
substitute a target.

## Unknown-food workflow: OFF → safe USDA proxy → capture → error

The CLI automatically checks exact user alias, exact cache, cache search, then
Open Food Facts.
For an unresolved food:

1. Let OFF run. For `off_low_confidence`, show its `candidate` and
   `alternatives`; do not accept one without the user's explicit choice.
2. Let USDA run only when setup or `NOMNOM_USDA_KEY` has configured it. The default
   `allow_for_unbranded` policy accepts only unbranded generic records with an FDC id, complete
   validated nutrition, sufficient confidence, and full query-token coverage. Always show returned
   `assumptions`. Never treat a branded or SKU-like query as a generic proxy. For
   `usda_key_required`, offer `nomnom setup` and the free-key URL returned in
   `details`. Use the environment only for non-interactive/CI operation.
3. On `generic_proxy_confirmation_required`, show the candidate and ask; do not change policy or
   write anything without the user's choice. On `exact_resolution_required`, ask for the package
   barcode or photo and use the exact capture flow above.
4. If OFF, USDA, and source-backed capture cannot resolve the food, report the
   structured error. Never substitute a similar food or invent values.

Other error handling:

- `quantity_required`: ask for grams, millilitres, or a supported piece count.
- `piece_weight_unknown`: ask for grams, then retry with `--food --grams`.
- `usda_low_confidence` / `usda_invalid_nutrition`: show the structured details,
  ask for a more specific name or verified label, and never accept/cache the weak result.
- `openfoodfacts_unavailable` / `usda_unavailable`: say that nothing was
  estimated; offer retry or a verified manual pin.

Size assumptions must show the returned provider serving field and value. Exact
human grams always override provider serving data, including per-piece input.

## Provider contract

OFF free-text search intentionally uses direct `requests` calls to the official
legacy v1 endpoint `https://world.openfoodfacts.org/cgi/search.pl` with
`search_terms`, `search_simple=1`, `action=process`, `json=1`, `page_size`,
supported response fields, and a descriptive User-Agent. API v2 is only for
structured filters or product/barcode data: never send it free-text
`search_terms`, and never use its unfiltered rows as fallback results. Retryable
429/5xx failures use bounded backoff, including bounded numeric `Retry-After`;
exhausted v1 failures are retryable `openfoodfacts_unavailable` errors.

Use `nomnom doctor --json` when diagnosing resolution. OFF
`product_lookup_reachable` means only that the v2 product-by-barcode endpoint
answered. OFF `full_text_search_ready` means the same v1 CGI capability used by
free-text resolution returned a valid product-list payload. Product reachability
must never be presented as full-text readiness. `configured` means OFF needs no
credential; USDA retains `configured`, `reachable`, and `key_source`. Never expose
a credential value.

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
