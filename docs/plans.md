# Plans

## v0.2 Source
- Task: Ship nomnomcli v0.2 resolving GitHub issues #1, #2, and #3.
- Canonical input: User-provided release brief for size parsing, Open Food Facts, and data quality.
- Repo context: Existing v0.1 Python 3.11 CLI and bundled/user SQLite databases.
- Last updated: 2026-07-19

## v0.2 Assumptions
- Size-based weights are transparent deterministic estimates and never imply cooking oil.
- Named-brand input must resolve from the user cache or Open Food Facts; a bundled generic row is not an acceptable substitute.
- Tests never make live Open Food Facts or USDA requests.

## v0.2 Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M5 | Size descriptors, fractions, dishes, and explicit per-piece grams | M4 | [x] |
| M6 | Branded Open Food Facts resolution and manual cache command | M5 | [x] |
| M7 | Deterministic bundled-data repair and quality gates | M6 | [x] |
| M8 | Documentation, versioning, release validation, and commit | M7 | [x] |

## M5. Size descriptors, fractions, dishes, and explicit per-piece grams `[x]`
### Goal
- RU/EN descriptor phrases and decomposed dishes resolve deterministically with visible assumptions.

### Tasks
- [x] Add focused failing parser and CLI tests for descriptors, fractions, grammar, dish prefixes, and `N pieces at X g`.
- [x] Add the packaged size-weight table and minimal parser/model/output support.
- [x] Validate the exact issue phrase with a deterministic cached branded product fixture.

### Definition of Done
- Required phrases produce correct grams, no implicit oil, additive JSON assumptions, and human-readable assumptions.

### Validation
```sh
pytest -q tests/test_parser.py tests/test_cli.py
```

### Known Risks
- Russian inflection and conjunction splitting must remain deliberately bounded and deterministic.

### Stop-and-Fix Rule
- Keep each focused test red until its matching minimal behavior is implemented, and repair regressions before M6.

## M6. Branded Open Food Facts resolution and manual cache command `[x]`
### Goal
- Named products resolve through cached/manual or mocked OFF data without generic substitution.

### Tasks
- [x] Add failing OFF success/error/ambiguity/cache and CLI-add tests.
- [x] Implement the OFF v2 client, branded normalization, alternatives, cache migration, and resolution priority.
- [x] Implement and validate `nomnom add` arguments, output, and error behavior.

### Definition of Done
- HTTP/network/malformed responses fail deterministically; successful products and manual entries work offline after caching.

### Validation
```sh
pytest -q tests/test_off.py tests/test_foods.py tests/test_cli.py
```

### Known Risks
- OFF nutrient keys vary; normalization must accept only finite numeric per-100g values.

### Stop-and-Fix Rule
- No test may access the live OFF service; fix cache and error-contract failures before M7.

## M7. Deterministic bundled-data repair and quality gates `[x]`
### Goal
- The bundled database has no placeholder nutrition profiles and is reproducibly built.

### Tasks
- [x] Add failing bundled-data quality tests.
- [x] Add reviewed deterministic overrides to the existing database builder and regenerate `foods.sqlite`.
- [x] Verify energy/macro compatibility, oil/water invariants, alcohol exceptions, and absence of unjustified 157 kcal rows.

### Definition of Done
- The regenerated bundled database passes the explicit quality audit and remains at least 300 foods.

### Validation
```sh
python scripts/build_mini_db.py --update-existing
pytest -q tests/test_data_quality.py
```

### Known Risks
- Alcoholic beverages require an explicit ethanol-aware exception to the 4/9/4 calculation.

### Stop-and-Fix Rule
- Treat any unexplained placeholder or large energy mismatch as a release blocker.

## M8. Documentation, versioning, release validation, and commit `[x]`
### Goal
- v0.2 is documented, fully validated, clean, and committed locally.

### Tasks
- [x] Update README, repository skill, and both version declarations to 0.2.0.
- [x] Run the complete test/lint gates and isolated exact smoke scenario.
- [x] Inspect the final diff and generated files, then create a coherent conventional commit.

### Definition of Done
- All requested gates pass, smoke JSON is captured, no junk remains, and no push/PR occurs.

### Validation
```sh
pytest
ruff check .
NOMNOM_DB_PATH=/tmp/nomnomcli-v02-smoke.sqlite nomnom log --parse "яичница из 3 небольших яиц, половины небольшого томата и половины средней луковицы, хлеб harry's 2 куска по 40г" --json
git status --short
```

### Known Risks
- The smoke brand must be pinned into the isolated cache first so validation is network-independent.

### Stop-and-Fix Rule
- Do not commit until every release gate and exact smoke command passes.

## Source
- Task: Build the complete nomnomcli v0.1 agent-first nutrition CLI.
- Canonical input: `.task-brief.md`
- Repo context: New Python package in the repository root.
- Last updated: 2026-07-18

## Assumptions
- `argparse` is preferable to a CLI framework so `requests` remains the only runtime dependency.
- Parsed logs are persisted immediately; agent-side confirmation means narrating/checking the deterministic CLI result before relying on it, since v0.1 has no pending-log state.
- Common piece and millilitre conversions are deterministic defaults documented in the README.

## Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M1 | Package, schemas, and bundled data | - | [x] |
| M2 | Resolution, parsing, nutrition, and persistence | M1 | [x] |
| M3 | CLI, recipes, installer, skill, and docs | M2 | [x] |
| M4 | Acceptance verification and release commit | M3 | [x] |

## M1. Package, schemas, and bundled data `[x]`
### Goal
- The project installs as a Python 3.11+ package and ships its offline food data.

### Tasks
- [x] Add package metadata, entry point, license, ignore rules, and CI.
- [x] Add bundled SQLite food data and Russian synonyms.
- [x] Add a maintainer database regeneration script.

### Definition of Done
- Editable install succeeds and package data is available through `importlib.resources`.

### Validation
```sh
python -m pip install -e .
nomnom --help
```

### Known Risks
- The aspirational 300–500 item dataset may require live USDA curation beyond an offline implementation run.

### Stop-and-Fix Rule
- If validation fails, fix the failure before moving to M2.

## M2. Resolution, parsing, nutrition, and persistence `[x]`
### Goal
- Food input resolves deterministically and logs accurate nutrition to SQLite.

### Tasks
- [x] Implement food lookup, RU synonyms, USDA fallback/cache, and confidence.
- [x] Implement free-text quantity parsing and nutrition arithmetic.
- [x] Implement user database logs, stats, and recipes.
- [x] Add focused unit/integration tests.

### Definition of Done
- Russian/English inputs, grams/pieces/ml, error paths, and aggregation pass tests.

### Validation
```sh
pytest -q
```

### Known Risks
- Free text is deliberately constrained to comma-separated item phrases in v0.1.

### Stop-and-Fix Rule
- If validation fails, fix the failure before moving to M3.

## M3. CLI, recipes, installer, skill, and docs `[x]`
### Goal
- Humans and agents can install and operate every v0.1 command.

### Tasks
- [x] Implement all argparse command trees and JSON/pretty output.
- [x] Parse schema.org Recipe JSON-LD and support recipe logging.
- [x] Add dry-run capable installer and Hermes skill.
- [x] Add complete README examples and design decisions.

### Definition of Done
- Core log/stats/recipe/search flows and installer dry run are reproducible.

### Validation
```sh
nomnom log --parse "борщ 300г, хлеб 2 куска, гречка 150 г" --json
nomnom stats today --json
sh install.sh --dry-run
```

### Known Risks
- Recipe ingredient prose varies widely; unresolved ingredients must fail explicitly.

### Stop-and-Fix Rule
- If validation fails, fix the failure before moving to M4.

## M4. Acceptance verification and release commit `[x]`
### Goal
- All acceptance gates are green and the repository has one release commit.

### Tasks
- [x] Run pytest and ruff.
- [x] Run installation and CLI smoke checks in an isolated user database.
- [x] Audit tracked files and create the specified conventional commit.

### Definition of Done
- Tests/lint pass, no unintended files remain, and HEAD is the requested single commit.

### Validation
```sh
pytest -q
ruff check .
git status --short
git log -1 --oneline
```

### Known Risks
- Tooling availability may require installing development dependencies locally.

### Stop-and-Fix Rule
- Do not commit until all required checks pass.
