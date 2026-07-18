# Plans

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
