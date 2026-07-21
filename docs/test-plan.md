# Test Plan

## Issue #33 Phase A Possessive-Brand P2 Validation
- In scope: terminal ASCII/curly possessive-s brand identity, both query/brand directions, provider evidence, raw-cache evidence, exact branded local pins, disjoint semantic generic refusal, nonmatching brands, ordinary food controls, and exact source preservation.
- Out of scope: general tokenizer changes, static brand data, broader punctuation/inflection rules, schema/policy changes, Phase B persistence/application, live providers, push, or PR operations.
- Fixtures: byte-audited temporary SQLite sources with an available cached semantic generic candidate, synthetic OFF candidates, raw legacy cache rows, and exact local branded pins.

### Critical Scenarios
- Original `Acme's`, provider/raw brand `Acme`, and cached semantic `chicken` refuse with `exact_resolution_required`, `would_write:false`, and unchanged source state.
- Original `Campbell`, provider/raw brand `Campbell’s`, and cached semantic `chicken` produce the same structured no-write refusal.
- Matching `exact_product` pins accept both possessive directions through exact brand matching.
- Unrelated provider/raw brands and existing ordinary food expressions remain unprotected and can use their safe plans.

### Acceptance Gates
- [x] Both provider and raw-cache directional regressions observed RED before production changes — 4 failures; 11 nonmatching, ordinary-food, and exact-pin controls green.
- [x] Targeted semantic/food/CLI tests pass — 134 passed.
- [x] Full `PYTHONPATH=. pytest -q` passes — 279 passed.
- [x] `ruff check .` and `git diff --check` pass.
- [x] One conventional local commit contains only the scoped P2 fix and execution records; nothing is pushed and no PR is created.

### Command Matrix
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py -k 'possessive_brand or nonmatching_provider_brand or nonmatching_raw_cache_brand or ordinary_food_expression'
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_foods.py tests/test_cli.py
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

## Issue #33 Phase A Snapshot-Integrity and Explicit-SKU P2 Validation
- In scope: `SKUABC123` exact intent, existing barcode/`ABC-12345` behavior, ordinary food and `vitamin B12` controls, bounded stable copying of main/journal/WAL/SHM, files appearing/disappearing, structured ongoing-write refusal, and exact source preservation.
- Out of scope: SQLite writer coordination/locking, source-side SQLite opens, Phase B application/persistence, schema/policy changes, live providers, push, or PR operations.
- Fixtures: a cached disjoint semantic generic candidate; current-schema exact local pin; deterministic copy hook that removes a source sidecar during the first attempt; deterministic permanently changing fingerprint; existing empty/legacy/WAL/hot-journal fixtures.

### Critical Scenarios
- Original `SKUABC123`, `brand_intent:false`, failed literal resolution, and cached semantic candidate `chicken` returns structured `exact_resolution_required`, `would_write:false`, with no writes; normal food expressions and `vitamin B12` remain eligible for safe semantic planning.
- Removing a source sidecar during the complete copy window invalidates and discards that private attempt; a later stable attempt may return a consistent exact plan, never a mixed plan or uncaught SQLite error.
- A fingerprint that changes on every bounded attempt returns `database_snapshot_unstable`, `would_write:false`, no plan, and leaves source files unchanged by resolution.
- Existing empty, legacy, pending-WAL, and hot rollback-journal snapshots retain their source-state preservation and private recovery/migration behavior.

### Acceptance Gates
- [x] Requested explicit-SKU and concurrent-copy regressions observed RED before production changes — 3 failures; 7 controls green.
- [x] Targeted semantic/database/food/CLI tests pass — 138 passed; focused preservation matrix 15 passed and database suite 9 passed.
- [x] Full `PYTHONPATH=. pytest -q` passes — 274 passed.
- [x] `ruff check .` and `git diff --check` pass.
- [x] Disposable CLI smoke returns `would_write:false` and preserves every source filename and SHA-256.
- [x] One conventional local commit contains only the scoped P2 fixes and execution records; nothing is pushed and no PR is created.

### Command Matrix
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py -k 'skuabc123 or snapshot_copy or snapshot_unstable or ordinary_food_expression or pending_wal or rollback_journal'
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_db.py tests/test_foods.py tests/test_cli.py
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

## Issue #33 Phase A Alphanumeric-SKU P2 Validation
- In scope: `SKU12345`/`ABC-12345`-style exact intent, existing numeric 4+ identifiers, Cyrillic originals with translated candidates, ordinary percentage/count/nutrient controls, matching exact local pins, and exact source immutability.
- Out of scope: parser grammar changes, static SKU/brand dictionaries, schema/policy/log changes, live providers, push, or PR operations.
- Fixtures: a byte-audited current-schema SQLite source with a cached disjoint semantic generic candidate, parameterized ordinary expressions, and matching local `exact_product` pins.

### Critical Scenarios
- Original `курица SKU12345`, `brand_intent:false`, failed literal resolution, and cached semantic candidate `chicken` refuses with structured `exact_resolution_required`, `would_write:false`, and unchanged source bytes/schema/counts/directory entries.
- Joined and hyphen/underscore alphanumeric codes are classified conservatively; standalone numeric 4+ barcode/SKU behavior remains protected.
- `milk 3%`, `3 eggs`, and `vitamin B12` can still use declared safe semantic candidates and are not classified as SKU exact intent.
- A matching local `exact_product` pin for an alphanumeric-SKU original still returns the original raw read-only plan.

### Acceptance Gates
- [x] Requested alphanumeric-SKU regression observed RED before production changes — 3 failures; 8 ordinary/numeric/hyphen/exact-pin controls green.
- [x] Targeted semantic/food/CLI tests pass — 126 passed.
- [x] Full `PYTHONPATH=. pytest -q` passes — 271 passed.
- [x] `ruff check .` and `git diff --check` pass.
- [x] One conventional local commit contains only the scoped P2 fix and execution records; nothing is pushed and no PR is created.

### Command Matrix
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py -k 'alphanumeric_sku or ordinary_food_expression or exact_local_barcode_or_pin'
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_foods.py tests/test_cli.py
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

## Issue #33 Phase A Raw-Brand Boundary Validation
- In scope: matching brand metadata on raw local/migrated legacy cache results, non-exact generic planning, matching exact local pins/barcodes, nonmatching raw brands, raw-first behavior, and source immutability.
- Out of scope: provider ordering changes, schema/policy/log changes, static brand data, live providers, push, or PR operations.
- Fixtures: synthetic `Acme chicken` cache rows with `brand=Acme`, a matching `exact_product` pin, a disjoint cached candidate, and byte-audited temporary SQLite state.

### Critical Scenarios
- Original `Acme chicken`, `brand_intent:false`, and a raw migrated `legacy` cache hit carrying brand `Acme` refuses with `exact_resolution_required` before a non-exact raw plan can return; source files remain identical.
- A matching local `exact_product` pin/barcode continues to return a raw read-only plan through `_raw_record_satisfies_exact_intent`.
- A raw row whose brand does not match the original does not falsely create hard exact intent and retains ordinary raw-first planning behavior.

### Acceptance Gates
- [x] Matching-brand raw-cache regression observed RED; four exact-pin/barcode and nonmatching-brand controls remained green.
- [x] Targeted semantic/food/CLI tests pass — 118 passed.
- [x] Full `PYTHONPATH=. pytest -q` passes — 263 passed.
- [x] `ruff check .` and `git diff --check` pass.
- [x] One conventional local commit contains only the scoped fix and execution records; nothing is pushed and no PR is created.

### Command Matrix
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py -k 'raw_cache_brand or exact_local_barcode_or_pin'
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_foods.py tests/test_cli.py
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

## Issue #33 Phase A Exact-Intent Boundary Follow-up Validation
- In scope: raw-cache dropped-token specificity, matching OFF brand evidence across USDA failure/not-found, nonmatching provider-brand control behavior, actual exact local pins/barcodes, ordinary raw-first behavior, and Phase A no-write guarantees.
- Out of scope: Phase B plan/log application, schema or policy changes, static brand/synonym datasets, live providers, push, or PR operations.
- Fixtures: synthetic legacy/generic raw cache rows, synthetic OFF branded candidates, configured failing USDA, exact local pins/barcodes, and byte-audited temporary SQLite sources.

### Critical Scenarios
- Original `Acme chicken`, raw generic cached original, and semantic `chicken` refuses as `exact_resolution_required` with `would_write:false` before the raw plan can return; source state is unchanged.
- Original brand-only `Acme`, OFF product brand `Acme`, configured USDA failure/not-found, and semantic `chicken` refuses as `exact_resolution_required` with no writes.
- An unrelated OFF brand for an ordinary non-brand original does not create exact intent and does not falsely block a safe generic plan.
- Ordinary raw-first resolution and matching local `exact_product` pins/barcodes continue to return read-only plans.

### Acceptance Gates
- [x] Both focused bypass regressions observed RED before production changes; nonmatching-brand control remained green.
- [x] Targeted semantic/food/CLI tests pass — 116 passed.
- [x] Full `PYTHONPATH=. pytest -q` passes — 261 passed.
- [x] `ruff check .` and `git diff --check` pass.
- [x] Disposable CLI smoke returns `would_write:false` and preserves exact database bytes, schema/counts, and directory entries.
- [x] One conventional local commit contains only the scoped Phase A follow-up; nothing is pushed and no PR is created.

### Command Matrix
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py -k 'raw_cache_dropped_token or off_brand_match_survives_usda_failure or nonmatching_provider_brand'
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_foods.py tests/test_cli.py
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

## Issue #33 Phase A Final Safety Findings Validation
- In scope: hot DELETE-mode rollback journal recovery in a private snapshot, byte/name preservation of source main/journal state, existing WAL no-side-file behavior, provider-evidenced brand-only exact intent, non-brand behavior, and Phase A no-write guarantees.
- Out of scope: Phase B plan/log application, schema or policy changes, static brand/synonym datasets, live providers, push, or PR operations.
- Fixtures: an abruptly exited DELETE-mode writer with a small cache and enough dirty updates to prove an uncommitted page spilled into the main file; synthetic OFF brand evidence plus a disjoint cached semantic generic candidate.

### Critical Scenarios
- The immutable source main file visibly contains an uncommitted dirty marker while a hot matching `-journal` exists; `nomnom resolve` opens only copied files, recovers the committed row, and leaves all source bytes and entries identical.
- Existing pending-WAL variants still expose committed WAL state without creating or changing source side files.
- Original `Acme`, payload `brand_intent:false`, OFF candidate brand `Acme`, and semantic candidate `chicken` refuses as `exact_resolution_required` with `would_write:false` and no source mutation.
- A provider candidate brand not contained in an ordinary non-brand original does not independently set exact intent; existing semantic refusal/selection behavior remains unchanged.

### Acceptance Gates
- [x] Both focused regressions observed RED before production changes — rollback returned the spilled uncommitted row and brand-only input returned a semantic plan.
- [x] Targeted semantic/database/food/CLI tests pass — 122 passed.
- [x] Full `PYTHONPATH=. pytest -q` passes — 258 passed.
- [x] `ruff check .` and `git diff --check` pass.
- [x] Disposable source-state smoke preserves exact main/journal hashes and directory entries; both existing pending-WAL variants pass without source side-file changes.
- [x] One conventional local commit contains only the scoped fixes; nothing is pushed and no PR is created.

### Command Matrix
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py -k 'rollback_journal or brand_only or pending_wal'
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_db.py tests/test_foods.py tests/test_cli.py
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

## Issue #33 Phase A WAL-Safe Snapshot Validation
- In scope: byte-copy-first source isolation, pending WAL visibility without source SHM creation, exact source-directory preservation, read-only-directory behavior, empty/v1/v2 compatibility, in-memory migration, and private temporary cleanup.
- Out of scope: Phase B plan application, schema or semantic-policy changes, live providers, concurrent-write consistency guarantees beyond an already committed pending WAL, push, or PR operations.
- Fixtures: temporary current-schema WAL databases with a committed cache row left by an abruptly exited writer, deliberately unlinked source SHM where supported, chmod-restricted source directories, and existing empty/v1/v2 sources.

### Critical Scenarios
- Resolve sees a food record present only in a pending WAL after the main database and existing WAL are copied to private storage.
- Resolve leaves source main/WAL/SHM names and bytes exactly unchanged and does not recreate a deliberately absent source SHM.
- A read-only source directory returns a successful plan or structured `NomnomError`, never an uncaught SQLite I/O failure.
- Existing empty/v1/v2 inputs still initialize/migrate only in private memory and preserve exact source state.

### Acceptance Gates
- [x] Focused WAL/read-only-directory regression observed RED before production changes — uncaught `sqlite3.OperationalError`.
- [x] Targeted semantic/database/CLI tests pass — 70 passed; both absent/existing SHM WAL variants pass.
- [x] Full `PYTHONPATH=. pytest -q` passes — 255 passed.
- [x] `ruff check .` and `git diff --check` pass.
- [x] Disposable CLI WAL smoke preserves exact source sibling names/bytes and creates no source SHM.
- [x] One conventional local commit contains the scoped fix; nothing is pushed and no PR is created.

### Command Matrix
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py -k 'wal or read_only_directory'
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_db.py tests/test_cli.py
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

## Issue #33 Phase A Final P2 Validation
- In scope: exact-intent guarding for every raw alias/exact/cache/search/provider plan return, a migrated legacy/non-exact SKU cache CLI regression, preserved raw-first behavior for ordinary input, preserved exact local barcode/pin behavior, and source-state immutability.
- Out of scope: Phase B plan application, new semantic policy/config/log integration, schema changes, live provider traffic, push, or PR operations.
- Fixture: a v2 SQLite source whose matching `lookup_query` migrates in the private snapshot to `resolution_mode=legacy`; source bytes, schema, version, table counts, and directory contents are captured before the CLI call.

### Critical Scenarios
- `nomnom resolve --food 'chicken 12345'` cannot return a plan from the matching migrated legacy row; it returns structured `exact_resolution_required` with `would_write: false`.
- The source database/cache/log/alias/recipe state and side-file set remain identical after refusal.
- Exact local barcode and explicit pin/alias records still return raw `exact_product` plans.
- Ordinary non-SKU input still uses the original raw result before semantic candidates.

### Acceptance Gates
- [x] Legacy/non-exact cache CLI regression observed RED before production changes — 1 failed, 2 exact-path checks passed.
- [x] Targeted semantic/food tests pass — 77 passed.
- [x] Full `PYTHONPATH=. pytest -q` passes — 253 passed.
- [x] `ruff check .` and `git diff --check` pass.
- [x] Scoped diff/status audit passes and one conventional local commit exists; nothing is pushed and no PR is created.

### Command Matrix
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

## Issue #33 Phase A Review-Fix Validation
- In scope: existing empty and supported v1/v2 database compatibility without source mutation, provider-independent explicit-brand protection, reopened safe USDA proxy ordering, whitespace-original validation before cache access, existing raw-first/proxy-only/#29 protections, and disposable CLI smoke.
- Out of scope: semantic plan application, semantic policy/config, schema changes to user databases, static brand/synonym/translation datasets, live provider traffic, and PR/push operations.
- Fixtures: byte-audited temporary SQLite sources, representative legacy rows, synthetic cached USDA/OFF proxies, and monkeypatched providers only.

### Critical Scenarios
- Existing empty and v1/v2 sources produce a structured plan or structured Nomnom error without uncaught SQLite failures; source bytes, schema, version, and row counts remain identical.
- `Acme chicken` with `brand_intent: false`, OFF disabled/unavailable, and candidate `chicken` refuses with `exact_resolution_required`, no generic plan, and no writes.
- A persisted/reopened safe USDA generic proxy ranks before a safe OFF proxy for the same relation even though `provider_data_type` is not stored.
- Whitespace-only `--food` and intent `original` fail as `invalid_resolution_intent` before a pinned unrelated cache row can be queried or planned.

### Acceptance Gates
- [x] Focused regressions observed RED before production changes — 6 expected failures.
- [x] Focused semantic/database/food/CLI tests pass — 114 passed.
- [x] Full `PYTHONPATH=. pytest -q` passes — 250 passed.
- [x] `ruff check .` and `git diff --check` pass.
- [x] Disposable CLI success/refusal smoke preserves database bytes/schema/counts and creates no side files.
- [x] One conventional follow-up commit exists; nothing is pushed and no PR is created.

### Command Matrix
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_db.py tests/test_foods.py tests/test_cli.py
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

## Issue #33 Phase A Validation
- In scope: intent v1 parsing/validation, original-first non-persisting resolution, bounded semantic retrieval, existing provider/identity checks, proxy-only candidate results, deterministic cross-candidate ranking, structured CLI JSON, benchmark cases, README, and agent skill.
- Out of scope: applying plans to logs, `semantic_policy`, `log --resolution-intents`, schema/config changes, LLM/API integration, embedded food/synonym/translation/weight data, live traffic, and user databases.
- Fixtures: temporary SQLite databases plus synthetic mocked USDA/OFF foods; no live providers or personal data.

### Issue #33 Phase A Critical Scenarios
- Raw original safe resolution wins and reports no semantic candidate index.
- Russian `курица сырокопченая` transparently plans a `generic_fallback` to roasted chicken; `куриная пастрома` follows a safe semantic route.
- Mixed-meat smoked sausage and unsafe/weak candidates refuse; unbranded roasted chicken breast succeeds as a generic proxy.
- Barcode, SKU, and explicit-brand originals require exact capture even when the payload says `brand_intent: false`.
- USDA Foundation/SR Legacy generic quality ranks above a safe OFF proxy after relation priority; confidence and normalized query break later ties deterministically.

### Issue #33 Phase A Negative / Edge Cases
- Malformed JSON, wrong/missing version, original mismatch, non-boolean brand intent, more than three candidates, duplicate/blank query, invalid relation, or missing/blank fallback assumption returns a structured failure.
- Semantic candidate provider matches that would be exact products, branded USDA rows, incomplete/weak/unrelated OFF rows, or token/category mismatches are rejected.
- Success and refusal preserve counts for `food_cache`, `log_entries`, `food_aliases`, and `recipes`.

### Issue #33 Phase A Acceptance Gates
- [x] Focused semantic/repository/CLI tests pass — 136 passed.
- [x] Existing issue #29 and #31 regression coverage passes.
- [x] Full `PYTHONPATH=. pytest -q` passes — 244 passed.
- [x] `ruff check .` and `git diff --check` pass.
- [x] Disposable database CLI success/refusal smoke proves `would_write: false`, unchanged cache/log/alias/recipe counts, and an identical SQLite digest.
- [x] One scoped conventional commit exists; nothing is pushed and no PR is created.

### Issue #33 Phase A Command Matrix
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_foods.py tests/test_usda.py tests/test_off.py tests/test_cli.py tests/test_db.py
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

## Issue #31 Validation
- In scope: `strict|ask|estimate` policy precedence, exact inline-JSON schema/mapping, fuzzy descriptor/fraction/bare-count parsing, all-or-nothing validation and writes, portion provenance in log/stats/text, explicit grams, old logs, docs, and agent guidance.
- Fixtures: temporary SQLite databases and monkeypatched deterministic generic provider foods only; no live traffic, user database, bundled weights, or repository food data.
- Exact acceptance literal: `3 small fried eggs, half small tomato, half small onion, whole wheat bread 180 g, milk 110 g, 15 dates`.
- Every fuzzy estimate entry must contain exact `item_index` and `input`, finite nonnegative `grams`, `lower_grams`, `upper_grams`, confidence in `0..1`, `method: agent_estimate`, and a nonempty assumption.

### Issue #31 Negative / Edge Cases
- Default strict behavior remains `piece_weight_unknown` and produces no log write.
- Malformed JSON, missing/extra/duplicate/mismatched entries, fuzzy estimate attached to explicit grams, invalid method/assumption, non-finite/negative values, invalid range ordering, and confidence outside `0..1` all fail atomically.
- `ask` exposes exact unresolved phrase identifiers and correction routes without applying estimates.
- Explicit grams and per-piece grams stay non-fuzzy; legacy item JSON without portion fields remains readable.

### Issue #31 Acceptance Gates
- [x] Focused tests observed RED before production changes — 16 expected failures, 1 pass.
- [x] Focused parser/config/CLI/database tests pass — 114 passed.
- [x] Full `PYTHONPATH=. pytest -q` passes — 224 passed.
- [x] `ruff check .` and `git diff --check` pass.
- [x] Disposable exact-breakfast CLI smoke passes with four estimated items and two explicit-gram items.
- [x] One scoped conventional commit exists; base remains `055e3d2`; nothing is pushed.

### Issue #31 Command Matrix
```sh
PYTHONPATH=. pytest -q tests/test_portions.py tests/test_parser.py tests/test_cli.py tests/test_config.py tests/test_db.py
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

## Issue #29 Validation
- In scope: resolver intent, OFF safe generic proxy semantics, USDA request/ranking provenance, exact barcode/brand/pin/alias paths, cache isolation, generic policy writes, CLI/API JSON, and literal translated inputs.
- Fixtures: mocked OFF and USDA payloads only, temporary SQLite user databases, no live traffic or personal data.
- Critical negative cases: HSN soy isolate, arbitrary cream-cheese barcode, Menguy's peanuts, branded USDA outranking attempts, unsafe branded queries, and rejected-candidate no-write behavior.
- Literal smoke inputs: `milk 3% 625 ml`, `soy protein isolate 30 g`, `chicken pastrami 150 g`, `whole wheat bread 140 g`, `cream cheese 40 g`, and `peanuts 55 g`; every success must be `generic_proxy`, and unsafe resolution must be structured.

### Issue #29 Acceptance Gates
- [x] Focused tests observed RED before production changes.
- [x] Focused resolver/provider/CLI/docs tests pass (114 tests).
- [x] Full `PYTHONPATH=. pytest -q` passes (204 tests).
- [x] `ruff check .` and `git diff --check` pass.
- [x] Fresh temp-data-dir literal mocked-provider smoke proves modes/provenance and no unsafe writes.
- [x] Scoped conventional commit exists; worktree is clean; nothing is pushed.

### Issue #29 Command Matrix
```sh
PYTHONPATH=. pytest -q tests/test_foods.py tests/test_usda.py tests/test_off.py tests/test_cli.py
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

## Issue #27 Source
- Task: Validate safe backdated logging and local-date-scoped stats.
- Plan file: `docs/plans.md`
- Status file: `docs/status.md`
- Last updated: 2026-07-21

## Issue #27 Validation Scope
- In scope: parsed/direct `--date`, strict ISO calendar-date validation, future rejection, deterministic local noon, additive log JSON fields, exact local-day stats, old today/week and no-date compatibility, docs, skill, and checkout CLI smoke.
- Out of scope: implicit date/time text parsing, schema changes, editing user data/aliases, recipe backdating, live providers, or personal data.

## Issue #27 Environment / Fixtures
- Use temporary databases with synthetic cached food only.
- Set `TZ=Asia/Almaty` and use `time.tzset()` where practical so expected `2026-07-20T12:00:00+05:00` and day boundaries are deterministic.
- Use injected `now` values for database tests and a non-future literal date for CLI tests.

## Issue #27 Test Levels

### Unit / Integration
- Parse exact `YYYY-MM-DD`; reject malformed, impossible, and future dates with structured actionable errors and zero log writes.
- Persist parsed and direct logs at local noon and return effective `logged_at` and `local_date`.
- Query a half-open local-day interval that excludes both adjacent local days.
- Preserve default no-date timestamp behavior and today/week stats.

### End-to-End / Smoke
- Exercise the checkout-installed `nomnom` command against a disposable database using the exact literal parsed log, direct log, and date stats forms.

## Issue #27 Acceptance Gates
- [x] Focused behavior tests witnessed RED before implementation.
- [x] Focused tests pass under controlled TZ — 40 passed.
- [x] `PYTHONPATH=. pytest -q` passes — 189 passed.
- [x] `ruff check .` and `git diff --check` pass.
- [x] Checkout import/executable proof and disposable literal CLI smoke pass.
- [x] Scoped diff/status audit passed; ready for the scoped commit and pull request.

## Issue #23 Source
- Task: Validate safe no-key base mode and optional USDA enhancement UX.
- Plan file: `docs/plans.md`
- Status file: `docs/status.md`
- Last updated: 2026-07-21

## Issue #23 Validation Scope
- In scope: setup/doctor capability JSON and text, installer status/human output, issue #22 agent isolation, strict OFF exact/generic identity and provenance, no-key source-needed errors, README, and agent skill.
- Out of scope: live provider traffic, public installs, bundled food data, model-derived nutrition, paid proxies, telemetry, or secret collection.

## Issue #23 Fixtures and Network Rules
- OFF and USDA behavior is injected or monkeypatched with synthetic local responses only.
- The fresh installer smoke uses a temporary HOME, temporary tool bins, the checkout under review, and local provider stubs; it must not fetch a public package.

## Issue #23 Test Levels

### Unit
- Setup capability state transitions and optional next action.
- OFF identity classification plus existing nutrient, token, type/category, and confidence guardrails.

### Integration
- No-key high-confidence OFF resolution caches truthful mode/source identity/provenance.
- Weak/wrong/unavailable OFF without USDA returns actionable `food_needs_source` without cache/log writes.
- Installer preserves sanitized environment isolation while reporting base/enhanced capability.

### End-to-End / Smoke
- Fresh temp user install resolves checkout code and reports `installed_base_ready`, setup `base_ready`, and one safe no-key unresolved-food flow.
- Configured/reachable local USDA stub reports connected/enhanced and installer `installed_and_ready`.

## Issue #23 Negative / Edge Cases
- Brand/SKU input never accepts a generic proxy.
- Pine nuts never resolve to an unrelated cheese result.
- OFF unavailability never surfaces raw `usda_key_required` as the first-screen user error.
- Login PATH repair remains the installer status even when base or enhanced capabilities are otherwise healthy.

## Issue #23 Acceptance Gates
- [x] Every relevant production behavior has a focused test witnessed RED before implementation.
- [x] `pytest -q` imports the checkout and passes.
- [x] `ruff check .`
- [x] Fresh disposable checkout-local installer smoke passes without public network/install.
- [x] `git diff --check` and scoped diff audit pass.
- [x] One local conventional commit; no push or PR.

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
