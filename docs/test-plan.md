# Test Plan

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
