# nomnomcli

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![CI](https://github.com/maxjustships/nomnomcli/actions/workflows/ci.yml/badge.svg)](https://github.com/maxjustships/nomnomcli/actions/workflows/ci.yml)

**nomnom stores nothing about food; it computes what you feed it.**

`nomnomcli` is an agent-first nutrition ledger. Version 0.4 ships zero food records: no food
database, synonym corpus, or piece-weight table is hidden in the package. It resolves food at
runtime, performs nutrition arithmetic in code, and stores successful logs plus a user-owned cache
in SQLite. There is no LLM in the program and no invented nutrition fallback.

```mermaid
flowchart LR
    A[Human or agent] -->|food and quantity| N[nomnom CLI]
    N --> L[(user food aliases)]
    N --> C[(user food cache)]
    N -->|free-text search| O[Open Food Facts API]
    N -->|when key is configured| U[USDA FoodData Central API]
    A -->|barcode or extracted label facts| N
    N -->|resolved JSON or structured error| A
```

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/maxjustships/nomnomcli/main/install.sh | sh
```

This creates or updates a user-level `nomnom` command in `$HOME/.local/bin`. The installer tries
`uv tool install` first, then pipx, then a non-virtualenv Python 3.11+ user-site install. Every
installer selection, invocation, and executable lookup runs in a target-user sanitized environment:
inherited agent `UV_TOOL_*`, `PIPX_*`, and XDG tool-location overrides are ignored, and uv/pipx are
explicitly directed to target-home defaults. It verifies the actual executable, `nomnom --version`,
and `nomnom doctor --json` in that sanitized user/system-only environment. Bootstrap verification
uses `$HOME/.config`; every `NOMNOM_*` override is ignored. It never opens the meal database, cache,
or aliases.

For machine-readable agent output:

```sh
curl -fsSL https://raw.githubusercontent.com/maxjustships/nomnomcli/main/install.sh \
  | sh -s -- --status-json
```

The structured `status` is `installed_base_ready`, `installed_and_ready`,
`installed_path_repair_needed`, or `error`. A healthy no-token install is
`installed_base_ready`; `installed_and_ready` is reserved for configured, reachable USDA enhanced
coverage. JSON also reports `generic_coverage` as `base` or `enhanced` and an
`optional_usda_setup` action when relevant. PATH repair remains the top-level status while retaining
those capability fields. No credential value is emitted. `--dry-run` remains available.

Check the optional generic-food connection without a prompt:

```sh
nomnom setup --status --json
```

Without a key it reports `status: base_ready` and `generic_coverage: base`; base cache, aliases,
OFF barcode/full-text, and source-backed label capture are ready. USDA provides optional broader no-photo generic/raw-food coverage. A configured and reachable key reports `status: connected` and
`generic_coverage: enhanced`. Run `nomnom setup` only when that broader coverage is wanted or a
specific food cannot be safely resolved. Setup validates the key before saving and never opens a
browser by itself.

USDA credentials are local user configuration, never repository or database content. The default
path is `$XDG_CONFIG_HOME/nomnomcli/config.toml` or `~/.config/nomnomcli/config.toml`, written with
owner-only `0600` permissions. `NOMNOM_USDA_KEY` is the non-interactive/CI option and takes
precedence over the stored key. Avoid putting it in commands, logs, or checked-in environment
files.

## Resolve and log food

```sh
nomnom log --parse "rice 150 g, eggs 2 pieces" --json
nomnom log --food "chickpeas, cooked" --grams 120 --json
```

For a remembered meal from a prior local calendar day, pass an explicit ISO date to either form:

```sh
nomnom log --parse "rice 150 g, eggs 2 pieces" --date 2026-07-20 --json
nomnom log --food "chickpeas, cooked" --grams 120 --date 2026-07-20 --json
```

`--date` accepts only `YYYY-MM-DD`; it never parses a time or a date from the food text. The date
is interpreted in the user's local timezone and stored deterministically at local noon on that
day. Successful log JSON includes the effective offset-aware `logged_at` and `local_date`, whether
or not `--date` was supplied. Without `--date`, logging keeps its existing current-local-time
behavior. Malformed, impossible, and future dates are rejected without a database write; today is
allowed. Use this CLI path for remembered meals—never edit the SQLite database directly.

Resolution is deterministic and ordered:

1. exact phrase in the user's alias table, pointing to an exact local cache name;
2. exact match in the user's `food_cache`;
3. token-overlap search in that cache;
4. an exact Open Food Facts product only when the input explicitly matches its brand/SKU;
5. a safe USDA FoodData Central Foundation/SR Legacy generic proxy, when a setup key or
   `NOMNOM_USDA_KEY` is configured;
6. a strictly matching Open Food Facts generic proxy, including a labelled branded candidate only
   when its returned product name/type is safe for the unbranded input;
7. actionable JSON error—never a guessed food.

Open Food Facts candidates need complete normalized query-token coverage from the returned product
name, a matching food type/category, a source identity/barcode, and complete positive finite kcal,
protein, fat, and carbs. An exact product requires a user-supplied barcode, an explicitly matched
brand/SKU, or an exact local pin/alias. Candidate confidence never establishes exact identity. A
safe branded OFF candidate used for unbranded text is always a `generic_proxy`, retains its source,
brand, barcode, and explicit assumption, and remains subject to the configured proxy policy. An
unsafe candidate returns `food_needs_source`. Rejected results are neither cached nor logged, and a
generic-proxy cache entry cannot satisfy a later branded query.

### Read-only semantic resolution planning

An agent can dry-run a bounded semantic reformulation before any logging command. The exact raw
`--food` phrase must also appear byte-for-byte as `original` in the v1 intent:

```sh
nomnom resolve --food "курица сырокопченая" --intent-json '{
  "version": 1,
  "original": "курица сырокопченая",
  "brand_intent": false,
  "candidates": [
    {"query": "smoked chicken", "relation": "same_form"},
    {
      "query": "chicken breast roasted",
      "relation": "generic_fallback",
      "assumption": "Smoked deli poultry is approximated by generic roasted chicken breast nutrition."
    }
  ]
}' --json
```

The v1 object has exactly `version`, `original`, `brand_intent`, and `candidates`. There may be at
most three candidates; every normalized `query` must be nonempty and unique. Relations are only
`lexical_equivalent`, `same_form`, and `generic_fallback`; a fallback requires a nonempty
`assumption`. Food/language inference stays agent-side—nomnom ships no translation, synonym, or
nutrition dataset and calls no LLM.

`resolve` tries the untouched raw phrase first. Only when that fails does it validate all semantic
candidates through the existing local/provider identity gates. Selection is deterministic:
relation priority, then unbranded USDA Foundation/SR Legacy quality over a safe OFF proxy, then
provider confidence, then normalized query. A semantic candidate can produce only a fully
validated `generic_proxy`, never `exact_product`. Mixed-species results, weak provider candidates,
and brand/SKU/barcode attempts are refused; `brand_intent:false` cannot weaken identity detected in
the raw phrase or provider response.

Success JSON includes `would_write:false`, raw `original`, `retrieval_query`, `intent_version`, raw
or semantic origin, provider source/id/data type/confidence/mode/alternatives, and candidate
index/relation/assumption when applied. Semantic plans set `requires_confirmation:true`: show the
plan and ask before taking any later action. Refusals are structured and offer clarification or
photo/barcode/label capture. Phase A does not integrate with `log`, add a semantic policy, or persist
anything. It takes an in-memory snapshot through a read-only connection to an existing user
database; if none exists, it plans against an ephemeral empty cache and does not create the database
path. Cache, logs, aliases, recipes, config, and all user records remain unchanged.

Successful API results are cached in the user's database, so the same food can resolve locally
later. Existing cache records, logs, recipes, and aliases are preserved when v0.4 opens the
database.
`nomnom search QUERY` searches this user cache; it is not a packaged food catalog.

Open Food Facts free-text search goes directly through the official legacy v1 endpoint,
`https://world.openfoodfacts.org/cgi/search.pl`, with `search_terms`, `search_simple=1`,
`action=process`, `json=1`, `page_size`, the supported response `fields`, and a descriptive
nomnomcli User-Agent. API v2 search is structured/filter-only: nomnom never sends free-text
`search_terms` to v2 and never falls back to unfiltered v2 catalog rows. Direct `requests` calls are
intentional because this small provider contract remains explicit and replay-testable.

Both OFF capabilities use bounded backoff for HTTP 429 and 5xx responses and safely honor a
numeric, bounded `Retry-After`. If v1 remains unavailable after retries, the OFF client raises the
typed retryable error `openfoodfacts_unavailable`; the no-key resolver preserves it inside
`food_needs_source.provider_error`. It never silently changes endpoint or returns unrelated
products. Product normalization and the token/category confidence checks still apply to every v1
candidate.

### Optional USDA enhancement

Check first, then run the one-time guided connection only if needed:

```sh
nomnom setup --status --json
nomnom setup
nomnom doctor --json
```

Get a free key at the official signup page
<https://fdc.nal.usda.gov/api-key-signup.html>. For non-interactive/CI use only, set it in the
environment:

```sh
export NOMNOM_USDA_KEY="your-key"
```

Without a key, a food that OFF cannot safely resolve returns `food_needs_source`, not a provider-key
failure. Its first-screen actions offer a package photo, barcode, source-backed `capture label`, and
the user's local cache/aliases. USDA appears separately as an optional enhancement for broader
no-photo generic/raw-food coverage. The nested `provider_error` preserves OFF candidate,
alternatives, retryability, and other technical diagnostics. Nothing unsafe is cached or logged.

When enabled, USDA search requires complete positive kcal/protein/fat/carbs, scores query token
overlap together with data type and category, prefers Foundation and SR Legacy, and enforces a
confidence floor. Weak matches return `usda_low_confidence` with candidate alternatives and are
never cached.

The default generic policy is `allow_for_unbranded`. A USDA result becomes a generic proxy only
when it is an unbranded Foundation or SR Legacy record with an FDC id and every
normalized query token is covered by its name. Brand/SKU-like or unmatched input and branded USDA
records return `exact_resolution_required` without cache or log writes. Accepted proxies expose
`resolution_mode=generic_proxy`, `source=usda`, the FDC `source_id`, `provenance=usda`, confidence,
and an explicit assumption in log JSON.

Choose a stricter policy in the user config:

```toml
[resolution]
generic_proxy_policy = "ask" # or "exact_only"
```

`NOMNOM_GENERIC_PROXY_POLICY` overrides the file. `ask` returns
`generic_proxy_confirmation_required` with the candidate but writes nothing; `exact_only` requires
barcode or package-label capture. Supported values are `allow_for_unbranded`, `ask`, and
`exact_only`.

Set `NOMNOM_OFFLINE=1` to prevent all remote food lookup. Set `NOMNOM_DISABLE_OFF=1` to skip OFF
while retaining USDA when its key is configured.

## Capture an exact packaged product

When an exact packaged product is needed, use its barcode or ask the user for a package photo. A
barcode capture calls only the Open Food Facts v2 product endpoint; it never sends free text:

```sh
nomnom capture barcode "0123456789012" --json
```

If the barcode is absent or OFF lacks complete core nutrition, the agent reads the supplied label
photo and passes the extracted per-100 g facts to the CLI:

```sh
nomnom capture label \
  --name "chicken pastrami" --brand "Example" \
  --kcal 110 --protein 20 --fat 2 --carbs 3 \
  --serving-grams 75 \
  --source-note "image:sha256:LOCAL_REFERENCE" --json
```

`--source-note` is required. Use a nonempty local or opaque image/barcode reference that lets the
user trace the facts without putting the image itself in SQLite. The CLI has no OCR or vision
dependency, never receives or stores the photo, never estimates missing macros, and rejects
non-finite/negative values or a non-positive serving weight without writing. Both capture paths
persist `resolution_mode=exact_product`, source identity, provenance, and the normalized nutrition
facts; the canonical name can then be used in an alias and logged offline.

### Legacy manual pin

`nomnom add` remains available for existing manual workflows. For a new packaged product, prefer
the source-backed capture commands above. Use only verified per-100 g label values:

```sh
nomnom add \
  --name "whole-grain bread" --brand "Example Bakery" \
  --kcal 250 --protein 9 --fat 4 --carbs 45 \
  --piece-grams 40 --json
```

The optional `--piece-grams` is the only manual piece-weight input. It makes later piece counts
work from the cached record.

### User food aliases

Aliases are explicit user-owned mappings stored only in the same user SQLite database as the food
cache. Their targets must be exact canonical names already present in that cache; creating or using
an alias never performs a remote target lookup. Alias matching is exact after case and whitespace
normalization, so an alias does not match unrelated longer food names.

```sh
nomnom alias add "хлеб harry's" "harry's american sandwich — Harry's" --json
nomnom alias list --json
nomnom alias remove "хлеб harry's" --json
```

Add or resolve the canonical food first. A missing target returns `alias_target_not_found`; adding
an existing phrase returns `alias_exists`; removing a missing phrase returns `alias_not_found`.

## Canonical agent input contract

The canonical shape supplied to nomnom is **food name + quantity + unit + optional modifiers**.
For example: `egg 3 pieces`, `rice 150 g`, or `bread 2 pieces at 40 g`. Quantity and unit are
required; modifiers may express a fraction, size, or explicit per-piece mass.

An agent translates the user's language into this contract before invoking nomnom. Translation may
choose a canonical food name already known to the user cache or an explicit user alias. Nutrition
resolution is a separate deterministic step: alias → local cache → exact intent or generic
provider proxy → error.
The agent must not translate by inventing nutrition values or silently substituting another food.

## Quantities, sizes, and dishes

The parser accepts kilograms, grams, millilitres, pieces, fractions, and explicit per-piece grams.
English and Russian size words such as `small` and `небольшой` remain valid syntax, but a size word
does not make nomnom guess a weight. By default, piece grams come only from explicit user input or
serving data on the resolved cached/pinned/API food record. Assumptions identify the provider,
source field, and returned value. When serving data is absent, the default `strict` portion policy
keeps the existing `piece_weight_unknown` response and writes no log. Explicit grams always win,
including `3 pieces FOOD at 38g` → `114g`.

```sh
nomnom log --parse "bread 2 pieces at 40g" --json
nomnom log --parse "яичница из 3 небольших яиц" --json
```

Supported dish prefixes split only the ingredients the user stated. nomnom never silently adds oil
or another ingredient. Millilitres use a resolved density when available and otherwise retain the
documented 1 g/ml conversion.

### Opt-in external portion estimates

An external agent may supply masses for unresolved counts, fractions, and size descriptions. This
is opt-in: use `--portion-policy estimate` together with inline `--portion-estimates` JSON. nomnom
does not contain an LLM, generate a mass, bundle portion weights, or treat the supplied mass as
measured or source-backed. It uses each supplied central `grams` value in the existing deterministic
nutrition calculator; the lower/upper range is provenance only and is not used to calculate a
nutrition interval.

The payload has exactly one top-level `items` array. Every entry has exactly these fields:

- `item_index`: zero-based position after nomnom splits the original `--parse` text;
- `input`: the exact trimmed item phrase from that text, matched byte-for-byte;
- `grams`, `lower_grams`, `upper_grams`: finite nonnegative numbers satisfying
  `lower_grams <= grams <= upper_grams`;
- `confidence`: finite number from 0 through 1;
- `method`: the literal string `agent_estimate`;
- `assumption`: a nonempty human-readable explanation.

For example:

```sh
nomnom log --parse \
  "3 small fried eggs, half small tomato, half small onion, whole wheat bread 180 g, milk 110 g, 15 dates" \
  --portion-policy estimate \
  --portion-estimates '{"items":[
    {"item_index":0,"input":"3 small fried eggs","grams":135,"lower_grams":120,"upper_grams":150,"confidence":0.72,"method":"agent_estimate","assumption":"Three small fried eggs estimated at 45 g each."},
    {"item_index":1,"input":"half small tomato","grams":35,"lower_grams":25,"upper_grams":45,"confidence":0.65,"method":"agent_estimate","assumption":"Half of a small tomato estimated at 35 g."},
    {"item_index":2,"input":"half small onion","grams":30,"lower_grams":20,"upper_grams":40,"confidence":0.63,"method":"agent_estimate","assumption":"Half of a small onion estimated at 30 g."},
    {"item_index":5,"input":"15 dates","grams":120,"lower_grams":90,"upper_grams":150,"confidence":0.58,"method":"agent_estimate","assumption":"Fifteen dates estimated at 8 g each."}
  ]}' --json
```

Every unresolved fuzzy item must have exactly one matching entry. Missing, extra, duplicate, or
non-exact mappings and malformed/invalid values reject the complete meal without a log write;
entries for explicit gram items are also rejected. Only inline JSON is supported. `ask` returns a
structured `portion_estimate_required` response with the exact index/input and writes nothing.
`strict` remains the default. Set a persistent default in user config or override it in the
environment:

```toml
[resolution]
portion_policy = "ask" # or "estimate"; default is "strict"
```

`NOMNOM_PORTION_POLICY` accepts `strict`, `ask`, or `estimate`; the CLI flag has highest precedence.
Estimated log items persist `approximate=true`, `portion_provenance=agent_estimate`, and the full
`portion_estimate` object next to food-resolution provenance. Log JSON and date stats expose these
fields. Human output gives one correction prompt toward scale grams, a photo, or a barcode. Existing
logs without these additive fields remain readable.

### Adding a new language

Provide an agent-side translator that emits the canonical contract and, when desired, create
user-specific food-name mappings with `nomnom alias add`. Food translations are user data, not
package data.

Parser syntax aliases for ordinary units, fractions, sizes, per-piece markers, dish prefixes, and
conjunctions are declarative tables in `nomnomcli/parser.py`. Add reviewed forms to those tables and
their tests; parser code changes are not required for ordinary unit aliases. A new language must
still provide quantity/unit forms unambiguously, and its agent translator remains responsible for
food names.

## Errors and output

Add `--json` for stable machine-readable output. User-correctable failures are written to stderr as
an `error` object and exit with status 2. Important codes include:

- `food_needs_source`: use the returned photo, barcode, label-capture, or local-cache path; inspect
  nested `provider_error` for OFF diagnostics. USDA is an explicitly optional enhancement.
- `off_low_confidence`: retained as nested technical detail when OFF candidates fail strict safety
  checks.
- `usda_low_confidence`: inspect the FDC candidate/data type/category and retry more specifically;
  no near match was cached.
- `usda_invalid_nutrition`: every USDA candidate lacked one or more complete positive core values.
- `generic_proxy_confirmation_required`: show the named provider candidate and ask before changing the
  configured policy; nothing was cached or logged.
- `exact_resolution_required`: request the barcode or a package photo for source-backed capture.
- `invalid_barcode` / `barcode_not_found` / `barcode_nutrition_incomplete`: correct the barcode or
  request a package photo; failed captures write nothing.
- `invalid_source_note` / `invalid_nutrition`: correct the extracted label facts; failed captures
  write nothing.
- `piece_weight_unknown`: ask for grams or add a verified `--piece-grams` value.
- `portion_estimate_required` / `portion_estimate_missing`: supply exactly matched external estimate
  metadata or use explicit grams; nothing is partially logged.
- `portion_estimates_malformed` / `portion_estimate_invalid` /
  `portion_estimate_mismatch`: correct the complete inline payload and retry.
- `alias_target_not_found`: add/resolve the exact cached target or remove the stale alias.
- `openfoodfacts_unavailable` / `usda_unavailable`: retry later or use a manual label.

Provider-unavailable errors include a `retryable` boolean. In `nomnom doctor --json`, OFF reports:

- `product_lookup_reachable`: the v2 product-by-barcode endpoint answered after bounded retries;
  this says nothing about free-text search.
- `full_text_search_ready`: the same v1 CGI capability used by runtime free-text resolution
  answered with a valid product-list payload; when false, OFF free-text resolution is unavailable.

`configured` means OFF needs no credential. USDA retains `configured`, `reachable`, and
`key_source`. Doctor never includes credential values.

Successful logs are stored immediately. Agents should show the returned names, grams, confidence,
alternatives, and assumptions before treating the resolution as confirmed.

## Stats and recipes

```sh
nomnom stats today --json
nomnom stats week --json
nomnom stats date 2026-07-20 --json
nomnom recipe add "https://example.com/recipe" --servings 4 --json
nomnom recipe log "Recipe name" --portions 1.5 --json
```

`stats date` uses the same user-local calendar-day boundary as `log --date`: local midnight is
inclusive and the next local midnight is exclusive. Existing `today` and `week` behavior is
unchanged.

Recipe ingredients use the same runtime resolver. An unresolved ingredient fails the whole import
instead of storing partial nutrition.

User data defaults to `~/.local/share/nomnomcli/nomnom.sqlite3`. Override it with
`NOMNOM_DB_PATH`. Schema v4 upgrades preserve cached foods, logs, recipes, and aliases in place and
add resolution mode, source identity/note, provenance, and assumption fields to the food cache.

## Agent skill and development

The repository agent workflow is [`skill/SKILL.md`](skill/SKILL.md). It teaches agents to use
nomnom's JSON, accept only safe generic proxies, request a barcode/package photo for exact products,
capture extracted label facts with a source note, and never estimate nutrition in their own
context.

```sh
python -m pip install -e '.[dev]'
PYTHONPATH=. pytest -q
ruff check .
```

All API tests use payloads under `tests/fixtures/` and mocked HTTP; the test suite never requires
network access.

## License

GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
