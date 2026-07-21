---
name: nomnomcli
description: >-
  Runtime calorie and nutrition tracking. Use when the user asks to track food,
  calculate calories or macros, import a recipe, or review daily/weekly totals.
---

# nomnomcli

Use `nomnom` as the only source of nutrition numbers. Never estimate calories, macros, or food composition. Portion mass may be externally estimated only through the contract below.

## Mandatory install protocol

This protocol is required whenever `nomnom` is unavailable. Ask permission, then run the single user-level bootstrap and parse its JSON:

```sh
curl -fsSL https://raw.githubusercontent.com/maxjustships/nomnomcli/main/install.sh \
  | sh -s -- --status-json
```

Never run `pip install -e` (or any editable install) inside a Hermes/agent virtualenv, never run a package installer there, or make an agent-private executable the user's command. The bootstrap selects uv tool, pipx, or a non-venv Python 3.11+ user site itself.

Follow this exact sequence:

1. Parse installer `status`, `executable`, `version`, `generic_coverage`, `optional_usda_setup`, `error`, and `path_repair`. Accept `installed_base_ready` and `installed_and_ready` as complete; base needs no USDA key. For `installed_path_repair_needed`, give its repair command and do not claim completion; for `error`, explain its action.
2. Derive the executable directory, verify `nomnom --version`, and run `nomnom doctor --json` with a sanitized user/system-only environment containing it plus ordinary locations such as `~/.local/bin`, `~/bin`, `/usr/local/bin`, `/usr/bin`, `/bin`, `/opt/homebrew/bin`, and `/opt/local/bin`.
   For bootstrap verification set `XDG_CONFIG_HOME=$HOME/.config`, clear every `NOMNOM_*` override, and exclude agent XDG roots, credentials, database paths, Hermes, Codex, the project, temporary directories, and virtualenvs. Parse doctor JSON; never infer readiness from exit status or human text.
3. Treat `installed_base_ready` as success, continue the task, and say: "Base tracking is ready without a USDA key." Do not ask for setup after a successful base install. Offer `nomnom setup` only for broader no-photo generic/raw-food coverage or after `food_needs_source`; never open a browser or run interactive setup automatically.
4. Agents must never type, receive, echo, or persist a USDA key or other secret, or ask for it in chat. Secret entry belongs only in the user's terminal through `nomnom setup`, which links to <https://fdc.nal.usda.gov/api-key-signup.html>, validates it, and stores owner-only XDG config (`0600`).
5. Base mode uses aliases/cache, strict OFF full text, exact OFF barcode, and package-photo label capture. Use `nomnom setup --status --json` only when capability status is needed: `base_ready` works; `connected` adds USDA-enhanced coverage.

## Log free text

1. Preserve every food and quantity the user supplied.
2. Translate each item to food name + quantity + unit + optional modifiers; translate language,
   not nutrition.
3. Run `nomnom log --parse "FOOD QUANTITY UNIT, FOOD QUANTITY UNIT" --json`.
   For a remembered prior local day, append `--date YYYY-MM-DD`; never infer a date or time.
4. Show returned names, grams, confidence, totals, alternatives, assumptions, and date fields.
5. Ask the user to confirm the resolution before relying on it.

Successful logs are stored immediately. Do not silently correct or rerun one;
tell the user before creating a replacement entry. Never read, edit, or manipulate SQLite directly;
use `nomnom log --date` for remembered meals and the CLI for all user data operations.

Supported dish prefixes split only named ingredients; never add a missing ingredient. Size words
are parser syntax. Default `strict` behavior asks for grams when no piece weight exists.

## External fuzzy portions

Prefer human scale grams, photo, or barcode. Otherwise an agent may explicitly estimate a diary
count/fraction/size, but never call it measured, exact, or source-backed. Run `nomnom log --parse
TEXT --portion-policy estimate --portion-estimates JSON --json`. JSON is `{"items":[...]}` with one
entry per unresolved fuzzy item and none for explicit grams. Each requires zero-based `item_index`,
exact trimmed `input`, finite nonnegative central/lower/upper grams (lower <= central <= upper),
confidence 0..1, `method:"agent_estimate"`, and nonempty `assumption`. Never fuzzy-match or generate
nutrition ranges. Invalid or incomplete input rejects the whole log. Show returned portion fields
and correction prompt. `ask` writes nothing; `strict` is default.

## Read-only semantic resolution plan

When literal unbranded text cannot resolve safely, infer at most three retrieval candidates without inventing nutrition. Run `nomnom resolve --food RAW --intent-json JSON --json` before logging. JSON v1 has exactly `version:1`, byte-exact `original`, boolean `brand_intent`, and `candidates`; each candidate has a nonempty unique `query`, relation `lexical_equivalent | same_form | generic_fallback`, and a nonempty fallback `assumption`. Add no translations, aliases, nutrition, weights, or hidden candidates.

The CLI tries RAW first and ranks validated candidates by relation, safe provider quality, provider confidence, then normalized query. Semantic output is only `generic_proxy`. Show original/retrieval query, candidate index/relation, assumptions, provider provenance/alternatives, and `requires_confirmation`; ask before later action when true. Never pass candidates to `log`: Phase A is planning only and `would_write` is false.

Never use `brand_intent:false` to erase a brand/SKU/barcode or accept an exact, mixed-species, weak, or first-result proxy. On `semantic_exact_capture_required`, capture exactly. On `semantic_resolution_refused`, preserve diagnostics and ask one concise clarification or request photo/barcode.

## Direct food flow

When the user gives one clear food and a measured weight:

```sh
nomnom log --food "chickpeas, cooked" --grams 150 --json
```

Always use the human's weight.

## Exact package capture

For an exact packaged food, do not substitute or ask the human to look up label numbers. Ask for the
barcode first, or request a clear package photo when it is unavailable/incomplete in OFF.

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

## Unknown-food workflow: cache → exact intent / generic proxy → source request

The CLI automatically checks exact user alias, exact cache, and safe cache search before providers.
For an unresolved food:

1. `exact_product` requires a user barcode, an explicitly matched/confirmed brand or SKU, or an
   exact local pin/alias. Provider confidence never makes an arbitrary branded result `exact_product`.
2. For unbranded input, prefer USDA Foundation/SR Legacy when configured. The default
   `allow_for_unbranded` policy accepts only non-branded records with an FDC id, complete
   validated nutrition, sufficient confidence, and full query-token coverage. Always show returned
   assumptions. A strictly name/type-matching OFF record may instead be a `generic_proxy`; if its
   source candidate is branded, show that brand, barcode, source, and explicit assumption.
3. On `generic_proxy_confirmation_required`, show the candidate and ask; do not change policy or
   write anything without the user's choice. On `exact_resolution_required`, ask for the package
   barcode or photo and use the exact capture flow above.
4. On `food_needs_source`, preserve nested provider diagnostics and offer the returned package-photo,
   barcode, `capture label`, and exact local-cache paths first. Offer the returned USDA action only
   as an optional broader-coverage enhancement. Never substitute a similar food or invent values.

Other error handling:

- `quantity_required`: ask for grams, millilitres, or a supported piece count.
- `piece_weight_unknown`: ask for grams, or use the explicit external fuzzy-portion flow.
- `usda_low_confidence` / `usda_invalid_nutrition`: show the structured details,
  ask for a more specific name or verified label, and never accept/cache the weak result.
- Nested `openfoodfacts_unavailable` or direct `usda_unavailable`: say that nothing was estimated;
  use the returned safe source actions or offer retry.

Size assumptions must show the returned provider serving field and value. Exact
human grams always override provider serving data, including per-piece input.

## Provider contract

OFF free-text uses the official legacy v1 endpoint with `search_terms`, `search_simple=1`,
`action=process`, JSON, page size, supported fields, and a descriptive User-Agent. API v2 is only
for structured/product data: never send free text or use unfiltered fallback rows. Retryable
429/5xx failures use bounded backoff; exhausted v1 raises `openfoodfacts_unavailable`.

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
nomnom stats date YYYY-MM-DD --json
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

If `nomnom` cannot produce nutrition, say it is unresolved; never estimate it in agent context.
