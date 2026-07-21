# nomnomcli coding-agent contract

This file is the authoritative repository contract for coding agents. If another tracked document
conflicts with it, follow the hierarchy under **Document authority**.

## Architecture non-negotiables

- nomnom is a deterministic nutrition engine. Nutrition resolution and arithmetic stay in the CLI.
- The repository and package ship no bundled production food data, nutrition facts, static food
  aliases, seed database, generic food corpus, runtime cache, static synonym/translation corpus,
  static portion/weight corpus, or provider credentials.
- Production food data is resolved at runtime and may be cached only in the user's private SQLite
  database. Runtime cache content is user data, never a source asset or test fixture.
- Do not embed an LLM, model API, model client, prompt corpus, or retrieval corpus in the CLI.
- An external agent/LLM may propose structured semantic candidates or fuzzy gram estimates only
  through an explicitly approved, validated CLI contract. It never supplies nutrition facts.

## Approved resolution order

Preserve this order and its failure behavior:

1. exact user alias to an exact local-cache name;
2. exact local-cache match;
3. safe local-cache search;
4. Open Food Facts and, when configured, USDA runtime lookup;
5. explicit barcode capture or source-backed package photo/label capture;
6. actionable structured error.

Never add a hidden fallback, packaged lookup table, generated corpus, or invented value.

## Exact identity and generic proxies

- `exact_product` requires exact evidence: a barcode, source-backed label capture, explicit
  brand/SKU match, or exact user pin/alias. Confidence alone is not identity.
- Branded or SKU-specific input must resolve exactly or request capture. Never silently substitute
  a generic food, similar product, or unconfirmed provider result for a branded/SKU request.
- Unbranded input may use a source-backed `generic_proxy` only under the approved policy and safety
  checks. Keep provider, source identifier, provenance, confidence, and assumption visible.
- A generic proxy never becomes exact through caching, ranking, agent wording, or user-interface
  presentation, and must not satisfy a later branded query.

## Phase A boundary

Semantic-retrieval Phase A is read-only proposal work. Unless a scoped issue explicitly approves a
validated contract, it must not change runtime resolution or CLI behavior. It must never write
aliases, cache entries, logs, or user data; access user SQLite; add providers/dependencies/corpora;
or change schemas, migrations, policies, or provenance. Historical plans do not authorize it.

## User data and privacy

- User SQLite is mutable, private data. Coding agents, tests, installers, migrations under test, and
  repository scripts must never open or operate on a real user's database.
- Tests must use pytest temporary paths and synthetic, intentionally tiny fixtures. Install tests
  must prove they ignore inherited database-path overrides and do not touch the referenced file.
- Never hard-code or track a real user database path, database copy, runtime cache, credential,
  token, or secret. Generic documented defaults are not authorization to access them.
- Use public CLI commands for user operations. Do not advise direct SQLite edits.

## Scope and change control

- Preserve existing CLI behavior and features unless the approved task explicitly changes them.
- No new feature, provider, data source, dependency, schema change, migration, log/output behavior,
  resolution policy, or privacy policy without an explicit approved issue and scoped tests.
- Do not treat old plans, status notes, examples, comments, or deleted paths as implementation
  authority. Stop and request approval when scope is unclear.
- Keep changes cohesive. Do not opportunistically rewrite runtime code or historical documents.

## Testing and verification

- Tests may use only synthetic, minimal fixtures and mocked provider responses; never live provider
  traffic, production food records, personal data, or the default user database.
- Any approved behavior change needs focused positive, negative, no-write, provenance, and privacy
  tests. Architecture-only changes must strengthen `tests/test_data_quality.py` when enforceable.
- Before completion run the full suite, lint, and whitespace validation:

  ```sh
  PYTHONPATH=. pytest -q
  ruff check .
  git diff --check
  ```

- Review the complete diff and repository status. Do not push, publish, or create a PR unless the
  task explicitly authorizes it.

## Document authority

1. `AGENTS.md` — normative coding-agent contract.
2. `docs/ARCHITECTURE.md` — normative architecture explanation.
3. `README.md` and `skill/SKILL.md` — user and operational guidance; they must remain compatible.
4. `docs/plans.md`, `docs/status.md`, and `docs/test-plan.md` — historical execution records only.

Historical documents may describe retired bundled-data architectures. They are not authority for
current implementation and must not be used to revive removed data, inputs, or behavior.
