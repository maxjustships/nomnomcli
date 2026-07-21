# Architecture

nomnomcli is a deterministic nutrition engine with a runtime-only food-data boundary. The source
tree defines validation, resolution, arithmetic, persistence, and CLI contracts; it does not ship a
food catalog.

`AGENTS.md` is the authoritative coding-agent contract. This document explains that contract for
maintainers and agents without expanding product scope.

## Runtime-only data boundary

Git, source distributions, wheels, installers, and agent skills must contain no bundled production
food records, nutrition data, static food aliases, seed database, generic food corpus, runtime
cache, static food synonym/translation corpus, static portion/weight corpus, or provider
credentials. Deleted or historical data paths are not valid inputs.

The only durable food state is mutable, user-owned SQLite content created through normal CLI use:
cache entries, explicit aliases, logs, and recipes. It is private runtime data, not repository
content. Tests use temporary databases and intentionally tiny synthetic fixtures; installers and
agents never open or modify a user's database.

## Resolution and provenance

Resolution is ordered and deterministic:

1. exact user alias to an exact cached name;
2. exact user-cache name;
3. safe user-cache search;
4. runtime Open Food Facts or configured USDA lookup;
5. explicit barcode or source-backed package-label capture;
6. actionable structured error.

Every accepted runtime result retains its resolution mode and source evidence. Relevant output and
cache records keep provider/source identity, provenance, confidence, and explicit assumptions.
Rejected, incomplete, unsafe, or unconfirmed results are not cached or logged.

The two identity modes have different guarantees:

- `exact_product` requires a barcode, source-backed label capture, explicit brand/SKU match, or
  exact user pin/alias. Ranking or confidence cannot establish exact identity.
- `generic_proxy` is allowed only for unbranded intent under the configured policy and provider
  safety checks. Its proxy status and provenance remain visible.

A branded or SKU-specific request must resolve exactly or request exact capture. The resolver must
never silently substitute a generic food or similar product, and a cached generic proxy must not
later satisfy branded intent.

## Responsibility boundaries

The CLI owns deterministic parsing, contract validation, provider safety checks, provenance,
nutrition arithmetic, policy enforcement, persistence, and structured errors. Provider clients
only fetch and normalize runtime source responses; they are not packaged catalogs.

An external agent may translate language into the canonical CLI input and may read a supplied
package image. It may propose fuzzy gram estimates only through the existing validated estimate
contract. Such estimates are explicitly approximate and never provide nutrition facts.

An agent/LLM is not part of the CLI runtime. It must not invent nutrition, silently choose a
different food, bypass confirmation, access SQLite directly, or introduce an embedded model,
credential, prompt corpus, API, or retrieval corpus.

Semantic-retrieval Phase A is read-only proposal work. It may define structured candidates for a
separately approved validated CLI contract, but it does not select nutrition, mutate cache/logs or
aliases, access user SQLite, or change current resolution. Plans or experiments do not authorize a
runtime feature.

## Change boundary and non-goals

Changes require explicit scope and tests. A new feature, provider, source, dependency, schema,
migration, log/output behavior, resolution policy, or privacy rule is outside the current
architecture unless an approved issue says otherwise.

The following are non-goals:

- offline coverage through bundled or generated production food data;
- packaged aliases, translations, synonyms, serving weights, or portion assumptions;
- LLM-driven nutrition, identity, provider selection, or persistence inside nomnom;
- silent generic substitution for branded/SKU intent;
- repository tools that inspect, migrate, seed, copy, or repair real user databases;
- treating `docs/plans.md`, `docs/status.md`, or `docs/test-plan.md` as current architecture.

For implementation decisions, the authority order is `AGENTS.md`, this document, then `README.md`
and `skill/SKILL.md`. Historical plan/status/test-plan material is context only.
