# Test Plan

## Issue #19 Source
- Task: Validate the v0.4 zero-friction source-backed capture slice.
- Plan file: `docs/plans.md`
- Status file: `docs/status.md`
- Last updated: 2026-07-21

## Issue #19 Validation Scope
- In scope: default/config/env proxy policy, generic USDA eligibility and visible assumptions, branded/SKU denial, OFF v2 barcode lookup, package-label capture, aliases/log replay, v3-to-v4 preservation, docs/skill, and isolated fresh-DB CLI smoke.
- Out of scope: LLM/OCR/cloud-vision dependencies, live API traffic, real/personal photos, repository nutrition records, and macro estimation.

## Issue #19 Fixtures and Network Rules
- Provider responses are mocked synthetic OFF/USDA payloads only; barcode assertions inspect the exact v2 product URL and absence of free-text parameters.
- Package-label tests pass synthetic agent-extracted numbers and opaque image/barcode reference tokens; no image is stored or committed.

## Issue #19 Test Levels

### Unit
- Policy precedence/default/invalid values; barcode syntax and complete nutrients; generic data type/brand/query-token safety; finite non-negative label values and positive serving grams.

### Integration
- Automatic unbranded USDA proxy caches and logs `generic_proxy`, canonical name, `source=usda`, FDC `source_id`, confidence, and explicit assumption.
- `ask`, `exact_only`, and branded inputs return structured actions without cache/log writes.
- Exact OFF and package-label captures preserve source, source id/note, provenance, mode, and later alias/log behavior.
- Explicit v3-to-v4 migration preserves cache, logs, recipes, and aliases while legacy rows remain readable.

### End-to-End / Smoke
- A clean temp database runs help/version, capture label, alias creation, offline log, and invalid structured capture input.

## Issue #19 Negative / Edge Cases
- Invalid barcode and OFF missing/zero core nutrition are never cached.
- Blank/missing source note, negative/non-finite nutrition, and non-positive serving grams are structured failures without writes.
- Returned branded USDA records, generic records with unmatched query tokens, and any explicit SKU never become generic proxies.

## Issue #19 Acceptance Gates
- [x] Focused tests witnessed RED before implementation.
- [x] `pytest -q` — 155 passed.
- [x] `ruff check .` — clean.
- [x] Literal isolated temp-DB smoke passes.
- [x] `git diff --check` and scoped diff audit pass.
- [x] One local conventional commit; no push or PR.

## Issue #17 Source
- Task: Validate the OFF full-text provider contract from GitHub issue #17.
- Plan file: `docs/plans.md`
- Status file: `docs/status.md`
- Last updated: 2026-07-21

## Issue #17 Validation Scope
- In scope: v1 CGI URL and parameters, query-specific mocked results, no v2 free-text fallback, bounded 503/429 retry including `Retry-After`, split OFF doctor readiness, existing confidence filtering, README, setup output, and agent skill.
- Out of scope: live OFF/USDA traffic, bundled food data, aliases, nutrition facts, or unrelated resolver behavior.

## Issue #17 Fixtures and Network Rules
- Every HTTP response is injected or monkeypatched; tests must be deterministic and replayable offline.
- Distinct terms map to distinct mocked v1 payloads so forwarding semantics are observable.

## Issue #17 Acceptance Gates
- [x] Focused contract tests observed RED before runtime implementation.
- [x] `pytest -q tests/test_off.py tests/test_foods.py tests/test_config.py tests/test_cli.py tests/test_install.py` — 62 passed.
- [x] `pytest -q` — 126 passed.
- [x] `ruff check .` — clean.
- [x] `git diff --check` — clean.
- [x] Scoped conventional commit created locally; no push or PR.

## Issue #17 Negative / Edge Cases
- v1 503 exhausts bounded retries and raises retryable `openfoodfacts_unavailable` without any v2 request.
- A valid but unrelated v1 candidate remains rejected as `off_low_confidence` and is not cached.
- Product/barcode HTTP reachability cannot make doctor report full-text resolution ready.

## v0.2 Source
- Task: Validate nomnomcli v0.2 issues #1, #2, and #3.
- Plan file: `docs/plans.md`
- Status file: `docs/status.md`
- Last updated: 2026-07-19

## v0.2 Validation Scope
- In scope: RU/EN sizes and fractions, Russian food inflection, dish decomposition, explicit per-piece grams, assumption contracts, OFF v2 normalization/failures/cache/ambiguity, manual branded cache entries, bundled database quality, version/docs/skill, isolated CLI smoke.
- Out of scope: live OFF/USDA availability and broad natural-language parsing beyond documented deterministic forms.

## v0.2 Fixtures and Network Rules
- Package fixture: `piece_weights.json`; database fixture: regenerated bundled `foods.sqlite`; mutable state: pytest temp databases.
- All OFF HTTP outcomes are mocked: success, 503, malformed JSON, ambiguous products, and no results.
- The exact branded smoke uses `nomnom add` in `/tmp/nomnomcli-v02-smoke.sqlite` before logging, so it is offline and reproducible.

## v0.2 Test Levels

### Unit
- Descriptor morphology, half/quarter fractions, default and explicit counts, exact size-table weights.
- OFF URL/params/timeout, nutrient normalization, barcode/source, deterministic alternatives.
- Data rows satisfy 4P+9F+4C within tolerance, with explicit ethanol treatment for alcohol.

### Integration
- Dish prefixes split ingredients and never add oil; JSON/text assumptions remain additive.
- Cached/manual branded products outrank network and generic rows; OFF successes persist in user cache.
- `nomnom add` validates positive nutrition/piece values and supports subsequent parsing offline.

### End-to-End / Smoke
- Exact Russian dish plus Harry's bread phrase in a dedicated `/tmp` database.
- Generic `хлеб 2 куска по 40г` explicit-weight phrase.

## v0.2 Negative / Edge Cases
- OFF network error, HTTP 503, malformed payload, missing/invalid products, ambiguity, and offline cached fallback.
- Named brand not found must return actionable add/search suggestions without generic substitution.
- Zero/negative add values and missing required CLI arguments fail with stable JSON where argparse permits.
- No unjustified placeholder kcal=157 rows; oil and water invariants are exact.

## v0.2 Acceptance Gates
- [x] Focused red/green test runs retained in the audit log.
- [x] `python scripts/build_mini_db.py --update-existing`
- [x] `pytest`
- [x] `ruff check .`
- [x] Exact isolated smoke commands and JSON inspection.
- [x] Clean diff/junk audit and local conventional commit.

## v0.2 Command Matrix
```sh
pytest -q tests/test_parser.py tests/test_cli.py
pytest -q tests/test_off.py tests/test_foods.py tests/test_cli.py
python scripts/build_mini_db.py --update-existing
pytest -q tests/test_data_quality.py
pytest
ruff check .
```

## v0.2 Open Risks
- Some legacy non-placeholder rows may reveal unrelated macro/energy inconsistencies; only safe, data-quality-scoped corrections belong in this release.

## Source
- Task: Validate nomnomcli v0.1 against its acceptance brief.
- Plan file: `docs/plans.md`
- Status file: `docs/status.md`
- Repo context: Python CLI, bundled SQLite data, local user SQLite state.
- Last updated: 2026-07-18

## Validation Scope
- In scope: parsing, lookup/synonyms, nutrition math, persistence/stats, recipe import/logging, output/error contracts, packaging, installer, skill, lint.
- Out of scope: live USDA and arbitrary public recipe-site compatibility; network behavior is mocked.

## Environment / Fixtures
- Data fixtures: bundled mini DB, temporary user databases, schema.org Recipe HTML.
- External dependencies: no live services; HTTP and USDA requests are mocked.
- Setup assumptions: Python 3.11+, pytest and ruff available.

## Test Levels

### Unit
- Quantity parsing across RU/EN grams, pieces, and ml.
- Exact nutrition calculations and synonym/food matching.
- JSON-LD extraction and ingredient parsing.

### Integration
- SQLite log/stat aggregation, recipe storage/logging, USDA cache, CLI JSON errors.

### End-to-End / Smoke
- Editable install, help, mixed Russian log, today stats, recipe fixture, installer dry run.

## Negative / Edge Cases
- Unknown foods, invalid quantities, malformed recipe JSON-LD, missing recipes, and unavailable URL fetches.
- Empty stats periods and fractional recipe portions.

## Acceptance Gates
- [x] `python -m pip install -e .`
- [x] `pytest -q`
- [x] `ruff check .`
- [x] Exact mixed Russian log/stats acceptance scenario.
- [x] `sh install.sh --dry-run`
- [x] Hermes skill frontmatter exists and file is at most 200 lines.

## Release / Demo Readiness
- [x] Core scenario works end to end.
- [x] Primary regression checks are green.
- [x] No blocker-level known issue remains.
- [x] Demo steps are reproducible.

## Command Matrix
```sh
python -m pip install -e .
pytest -q
ruff check .
NOMNOM_DB_PATH="$(mktemp)" nomnom log --parse "борщ 300г, хлеб 2 куска, гречка 150 г" --json
sh install.sh --dry-run
```

## Open Risks
- Typical prepared-dish values remain representative estimates, explicitly documented in README and source metadata.

## Deferred Coverage
- Live USDA API contract tests and broad web recipe corpus tests.
