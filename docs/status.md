# Status

## Snapshot
- Current phase: issue #33 Phase A final P2 completed and ready for local commit
- Plan file: `docs/plans.md`
- Status: green
- Last updated: 2026-07-21

## Done
- Fixed the final P2 by applying one exact-intent validation boundary to every raw alias/exact/cache/search/provider result before returning a plan.
- Added a migrated v2 legacy SKU cache CLI regression proving structured `exact_resolution_required`, `would_write: false`, and byte/schema/count/log/side-file immutability; preserved exact local barcode/pin and non-SKU raw-first behavior.
- Recorded the regression RED, then passed 77 focused semantic/food tests, 253 full tests, Ruff, and diff checks.
- Resolved all independent Phase A blocking findings with an isolated in-memory migrated read-only snapshot, early whitespace-original validation, provider-independent conservative specificity protection, and safe reopened-USDA priority recovery.
- Added six focused regressions covering zero-byte/v1/v2 source preservation, offline explicit-brand refusal, persisted cache reopen ordering, and pre-cache whitespace rejection; recorded all six RED before implementation.
- Passed 114 focused tests, 250 full tests, Ruff, diff checks, and disposable subprocess CLI success/refusal smoke with identical database SHA-256, schema, counts, and no side files.
- Completed issue #33 Phase A with a strict external intent v1 module, original-first read-only resolution, generic-proxy-only semantic candidates, deterministic relation/provider/confidence/query ordering, and structured JSON plans/refusals.
- Added a query-only SQLite CLI path and persistence-disabled provider resolution; the mocked success/refusal smoke preserved all mutable table counts and the exact database digest.
- Passed 136 focused tests, 244 full tests, Ruff, diff checks, and the Russian fallback/mixed-meat disposable CLI smoke.
- Completed issue #31 with strict-by-default external portion policy, exact index-plus-input estimate mapping, full range/confidence/assumption validation, central-grams nutrition, and additive approximate provenance.
- Recorded the required RED run (16 expected failures, 1 strict-path pass), then passed 114 focused tests, 224 full tests, Ruff, diff checks, and the exact six-item checkout CLI smoke.
- Verified four breakfast items persist as `agent_estimate`, bread 180 g and milk 110 g remain non-approximate, date stats expose all portion fields, and the temporary smoke database is removed.
- Completed issue #29 with intent-aware exact identity, USDA Foundation/SR Legacy preference, strict OFF proxy type matching, branded-proxy provenance, and cache intent isolation.
- Recorded RED runs for 16 primary regressions plus two cache edges and missing-category evidence, then passed 114 focused tests, 204 full tests, and Ruff.
- Ran all six literal translated inputs against mocked providers in a fresh temporary data directory; all six were explicit `generic_proxy` rows with source, brand, barcode, and assumption.
- Completed issue #27 with strict local-date parsing, deterministic local-noon backdating for both log forms, additive timestamp/date JSON, exact date stats, no-write failures, and preserved no-date/today/week behavior.
- Documented `--date` for remembered meals and that humans/agents must never manipulate SQLite directly.
- Passed 189 tests, Ruff, diff checks, checkout import proof, and the clean disposable installed-CLI literal smoke.
- Fixed issue #17 with OFF v1-only full-text search, independent product/full-text probes, typed bounded 503 handling, deterministic contract coverage, and updated provider docs.
- Built the complete package, 431-food database, 258-entry Russian synonym layer, CLI, recipes, installer, skill, docs, CI, and tests.
- Passed 30 pytest tests and Ruff with no issues.
- Passed the exact mixed-Russian log/stats flow, fixture recipe import/log, and installer dry-run.
- Shipped deterministic RU/EN descriptor/fraction parsing, all four dish prefixes, explicit per-piece grams, and additive assumptions.
- Added mocked OFF v2 resolution with branded priority, alternatives, barcode/cache migration, clear failures, and `nomnom add`.
- Removed placeholder profiles from the offline seed and bundled 431-food database; byte-deterministic updates and data-quality gates pass.
- Passed 72 tests, Ruff, version 0.2.0, and the exact isolated v0.2 smoke; removed the `/tmp` smoke database.
- Completed v0.4 source-backed capture: safe default USDA generic proxies, exact OFF v2 barcode capture, agent-extracted label capture, durable provenance, and additive schema-v4 migration.
- Passed 155 tests, Ruff, diff audit, and the literal isolated schema-v4 capture/alias/offline-log/error smoke.
- Completed issue #23 no-key base mode: base/enhanced capability states, successful no-token installer status, strict truthful OFF exact/generic provenance, and actionable `food_needs_source` fallbacks.
- Passed 177 tests, Ruff, checkout-import guard, shell syntax, and the disposable checkout-built installer/provider-stub smoke.

## In Progress
- No implementation work pending.

## Next
- None; create the requested local conventional commit, then stop without pushing or opening a pull request.

## Decisions Made
- Final P2: enforce exact intent once at the raw planning boundary so alias, exact/cache/search, and provider returns share the same protection.
- Final P2: protected raw intent may pass only for a matching `exact_product`, including explicit local barcode/name/lookup pins and aliases.
- Issue #33 Phase A: original resolution always runs first, but through a dedicated non-persisting path that never calls `_cache_food`.
- Issue #33 Phase A: semantic candidates can produce only `generic_proxy`; original barcode/SKU/explicit-brand intent remains exact-capture-only regardless of supplied `brand_intent`.
- Issue #33 Phase A: rank across all accepted candidates by relation, generic USDA quality before safe OFF proxy, confidence, then normalized query.
- Issue #31: require zero-based `item_index` plus exact `input` in every estimate entry; never fuzzy-match estimate metadata to parsed foods.
- Issue #31: require central/lower/upper grams, confidence, literal `agent_estimate`, and a nonempty assumption for every unresolved fuzzy portion.
- Issue #31: keep log provenance inside additive item JSON so schema v4 and old log readability remain unchanged.
- Issue #29: resolution mode follows user identity intent plus source identity, never candidate confidence alone.
- Issue #29: generic USDA searches send the documented `dataType` array for Foundation and SR Legacy and rank eligible non-branded provenance ahead of branded payload rows.
- Issue #29: a branded OFF candidate needs product-name token coverage plus category/type evidence to serve only as a labelled generic proxy.
- Issue #27: reuse the existing offset-aware `logged_at` field; no migration is needed.
- Issue #27: explicit dates become local noon and stats use `[local midnight, next local midnight)` boundaries.
- Issue #23: a healthy no-key install is complete base coverage; USDA is only an optional enhancement for broader no-photo generic/raw-food resolution.
- Issue #23: PATH repair outranks base/enhanced installer completion status, but output must still describe the available coverage.
- Default generic policy is `allow_for_unbranded`; this explicit user decision supersedes issue #19's older `ask` default.
- Generic proxy safety requires a generic USDA type, no returned brand, an FDC id, complete validated core nutrition, accepted confidence, and full query-token coverage.
- Package photo extraction stays outside the dependency-free CLI; only extracted facts and a mandatory source note enter the user database.
- Route all OFF free text to legacy v1 `/cgi/search.pl`; never pass `search_terms` to v2.
- Report OFF product/barcode reachability separately from full-text resolution readiness.
- Use stdlib `argparse` — keeps runtime dependencies to `requests` only.
- Use SQLite for shipped foods and per-user mutable state — matches the offline-first contract.
- Reuse `scripts/build_mini_db.py --update-existing` for deterministic offline v0.2 data repair without shrinking the tracked USDA corpus.

## Assumptions In Force
- Issue #33 intent v1 is external bounded retrieval metadata only; it contains no nutrition, synonyms, translations, weights, model call, or persistence policy.
- Schema v4 is completed additively from the existing v3-to-v4 boundary and preserves every v3 table and row.
- Issue #17 tests use only mocked/replay transports and never live OFF traffic.
- Agent confirmation is an operating pattern, not a pending database transaction in v0.1.
- Named brands are never resolved to bundled generic foods; manual cache entries are the offline escape hatch.
- Descriptor weights are estimates that must be surfaced as assumptions in JSON and text.

## Commands
```sh
python -m pip install -e .
pytest -q
ruff check .
```

## Audit Log
| Date | Milestone | Files | Commands | Result | Next |
| --- | --- | --- | --- | --- | --- |
| 2026-07-21 | M37–M39 final P2 | raw-plan guard, migrated legacy SKU fixture, semantic regressions, docs | focused RED/GREEN; 77 focused; 253 full; Ruff; diff check | pass; source DB/cache/log/side files unchanged | local commit |
| 2026-07-21 | M34–M36 review fixes | read-only DB snapshot, semantic guards/ranking, regressions, docs | focused RED/GREEN; 114 focused; 250 full; Ruff; diff check; subprocess smoke | pass; exact DB digest/schema/counts unchanged | local commit |
| 2026-07-21 | M31–M33 | semantic contract/planner/CLI/read-only DB, benchmark, docs | focused/full pytest; Ruff; diff check; digest-preserving temp-DB smoke | 136 focused; 244 full; clean; success/refusal no writes | local commit |
| 2026-07-21 | Issue #33 preflight | issue comment, resolver/providers/CLI/DB/models/tests, planning docs | `gh issue view 33 --comments`; source/test inspection | Phase A boundary and mutation risk identified | M31 tests |
| 2026-07-18 | Preflight | `.task-brief.md`, planning docs | repository inspection | pass | M1 |
| 2026-07-18 | M1–M3 | package, data, tests, docs, skill, installer, CI | `pytest -q`; `ruff check .` | 30 pass; clean | M4 |
| 2026-07-18 | M4 smoke | isolated user DB and local recipe fixture | CLI acceptance commands; `sh install.sh --dry-run` | pass | commit |
| 2026-07-19 | v0.2 preflight | repo skill, architecture, tests, config, README, data builder | repository inspection; `git status --short` | clean baseline | M5 tests |
| 2026-07-19 | M5 | parser, piece weights, models, CLI, synonyms, tests | focused red/green parser and CLI runs | pass | M6 |
| 2026-07-19 | M6 | OFF client, food repository, cache migration, CLI add, tests | mocked OFF success/503/network/malformed/ambiguity/cache runs | pass | M7 |
| 2026-07-19 | M7 | data overrides, offline seed, bundled SQLite, builder, quality tests | `build_mini_db.py --update-existing`; deterministic hash audit | 431 rows; pass | M8 |
| 2026-07-19 | M8 | README, skill, version, planning docs | `pytest -q`; `ruff check .`; exact isolated smoke; diff/junk audit | 72 pass; clean | commit |
| 2026-07-21 | M9 | OFF, food confidence, doctor/setup contract tests | `PYTHONPATH=. pytest -q tests/test_off.py tests/test_foods.py tests/test_config.py tests/test_cli.py`; focused setup test | RED: missing product probe; RED: missing status explanation | M10 |
| 2026-07-21 | M10–M11 | OFF client, onboarding/CLI, README, skill, tests | focused pytest; full pytest; full Ruff | 62 pass; 126 pass; clean | M12 |
| 2026-07-21 | issue #19 preflight | issue, providers, resolver, schema, CLI, tests, docs, skill | `pytest -q`; repository inspection | 126 pass; clean baseline | M13 |
| 2026-07-21 | M13 | policy, proxy, capture, and migration acceptance tests | focused pytest; full local pytest | RED contracts and 4 partial-worktree failures recorded | M14 |
| 2026-07-21 | M14–M16 | config, resolver, OFF, schema, CLI, docs, skill, tests | `pytest -q`; `ruff check .`; `git diff --check`; literal temp-DB smoke | 155 pass; clean; smoke pass | local commit |
| 2026-07-21 | M17 | setup/status tests and onboarding/CLI | focused RED/GREEN pytest | RED captured; 9 setup tests pass | M18 |
| 2026-07-21 | M18 | installer statuses, capability JSON/human output, issue #22 isolation | focused RED/GREEN pytest | 10 installer tests pass before docs additions | M19 |
| 2026-07-21 | M19 | OFF identity/provenance and no-key source error | focused RED/GREEN pytest | 79 resolver/OFF/CLI/capture tests pass | M20 |
| 2026-07-21 | M20 | docs, import isolation, full suite, lint, disposable install | `pytest -q`; `ruff check .`; local offline installer smoke | 177 pass; clean; smoke pass | local commit |
| 2026-07-21 | issue #27 preflight | CLI, database, tests, docs, skill, planning records | baseline `pytest -q`; checkout import/executable inspection | 179 pass; clean baseline | M21 |
| 2026-07-21 | M21–M22 | CLI date tests and `nomnomcli/cli.py` | focused RED then GREEN pytest | 7 expected failures; then 7 pass | M23 |
| 2026-07-21 | M23 | database/CLI date stats tests and query implementation | focused RED then GREEN pytest | 2 expected failures; then 8 pass | M24 |
| 2026-07-21 | M24 | README, skill, changed code/tests, disposable installed checkout | focused/full pytest; Ruff; diff check; literal temp-DB smoke | 40/189 pass; clean; smoke 150 kcal | local commit |
| 2026-07-21 | M25 | resolver/provider regression tests | focused pytest | RED: 16 primary failures; 2 cache failures; 1 category-evidence failure | M26 |
| 2026-07-21 | M26–M27 | resolver, USDA, docs, skill, tests | `pytest -q`; `ruff check .`; temp-data mocked-provider smoke | 114 focused; 204 full; clean; 6/6 generic proxies | local commit |
| 2026-07-21 | M28 | issue #31 tests and planning records | targeted pytest before production edits | RED: 16 expected failures; 1 strict-path pass | M29 |
| 2026-07-21 | M29–M30 | portion validation/parser/model/CLI/stats, docs, skill, tests | focused/full pytest; Ruff; diff check; exact temp-DB checkout smoke | 114 focused; 224 full; clean; 4 estimates + 2 explicit grams | local commit |

## Smoke / Demo Checklist
- [x] Review-fix success and offline explicit-brand refusal subprocesses preserve exact SQLite digest/schema/counts and create no side files.
- [x] Issue #33 Russian fallback succeeds and mixed-meat refusal fails with unchanged cache/log/alias/recipe counts and identical SQLite digest.
- [x] Fresh temp DB: help/version, capture label, alias, log, and invalid structured capture error.
- [x] Russian mixed-item log works and persists.
- [x] Today stats reproduce logged totals.
- [x] Fixture recipe imports and logs.
- [x] Installer dry run prints safe actions.
- [x] Full pytest and ruff gates pass.
- [x] Exact v0.2 dish/brand phrase works from an isolated pinned cache.
- [x] OFF success/failure paths are covered without live traffic.
- [x] Bundled database passes v0.2 quality tests.
- [x] Version and documentation report 0.2.0 behavior.
- [x] OFF free text uses v1 with no unfiltered v2 fallback.
- [x] Doctor and setup distinguish product/barcode reachability from full-text readiness.
- [x] Version and documentation report v0.4 generic-proxy and source-backed capture behavior.
- [x] Fresh no-token checkout install reports `installed_base_ready` with base coverage.
- [x] Setup reports `base_ready/base` without USDA and `connected/enhanced` with the local USDA stub.
- [x] Safe no-key miss returns `food_needs_source` with photo/barcode/label/cache options and optional USDA.
- [x] Literal parsed/direct `2026-07-20` logs persist local noon and date stats return only that local day.
- [x] Issue #29 literal six-item temp-data smoke returns only explicit generic proxies with audited OFF candidate identity.
- [x] Issue #31 exact breakfast logs atomically with four explicit agent estimates and two unflagged explicit-gram items.
- [x] Issue #31 date stats preserve the four portion provenance objects and one concise correction route.
