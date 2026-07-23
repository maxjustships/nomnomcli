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
Rejected or unsafe source results are not cached or logged as resolved nutrition. An agent intake
may explicitly journal an unresolved exact item as `pending_capture`; that item retains raw input
and an actionable photo/barcode state, contributes no invented nutrition, and makes the meal and
period totals explicitly incomplete.

Local identity is established only by an exact normalized cache name, an explicit user alias, an
exact barcode, or existing explicit source-backed identity that satisfies the same exact-product or
generic-proxy safety rules. `lookup_query` is retrieval metadata, never identity proof. A legacy or
fuzzy record that fails this contract may be shown as a search candidate, but it cannot be logged
automatically; resolution continues to a runtime provider or an actionable error.

Identity modes have different guarantees:

- `exact_product` requires a barcode, source-backed label capture, explicit brand/SKU match, or
  exact user pin/alias. Ranking or confidence cannot establish exact identity.
- `generic_proxy` is allowed only for unbranded intent under the configured policy and provider
  safety checks, or for the explicitly validated profile-specific branded fallback below. Its proxy
  status and provenance remain visible.
- `probable_product` is a provider text match for a branded request without barcode/label evidence.
  It remains approximate, never becomes `exact_product`, and carries source and assumption.

Semantic food type is the absolute floor in every profile. `practical` estimates fuzzy portions
through an explicit agent estimate and, after real text discovery finds no usable brand candidate,
permits an explicit source-backed same-type branded generic fallback. `balanced` is the recommended
new-user default and requires an explicit material-risk disposition for that fallback. `exact`
requires measured/explicit fuzzy portions and exact brand evidence. No profile permits a different
food type: never silently substitute one. No profile permits silent fallback or reuse of a generic
proxy as later branded identity.

`resolution.generic_proxy_policy` remains compatible. Explicit environment or stored legacy policy
values override profile defaults for generic proxy confirmation; an existing installation with no
stored accuracy profile retains the historical strict portion default. Once a profile is explicitly
stored, `practical` and `balanced` default fuzzy portions to `estimate`, while `exact` uses `strict`.

Journal correction is reversible through `nomnom log remove LOG_ID --confirm --json`. The CLI
validates the identifier and confirmation, then transactionally removes only that log record; user
operations never require direct SQLite edits.

## Responsibility boundaries

The CLI owns deterministic parsing, contract validation, provider safety checks, provenance,
nutrition arithmetic, policy enforcement, persistence, and structured errors. Provider clients
only fetch and normalize runtime source responses; they are not packaged catalogs.

Raw voice, text, or photo is the primary user interface. A surrounding system translates or
captures that input through validated CLI paths rather than demanding manual nutrition lookup or
database operation; this principle does not add an orchestration runtime to the CLI.

The approved agent-first runtime contract has two CLI phases:

1. `nomnom agent candidates --input ... --json` queries runtime providers without opening SQLite.
   It returns deterministically ordered source-backed identity metadata, provider/search status, a
   canonical SHA-256 discovery receipt, and opaque `off:BARCODE` or `usda:FDC_ID` references, never
   nutrition facts for the agent to copy into a plan.
   `agent_selection_eligible` identifies source-unbranded generic records that an external agent
   may assess semantically; `pending_capture_required` and `identity_rejected` are not selectable.
2. `nomnom agent intake --plan ... --json` accepts a strict version-2 plan containing the active
   accuracy profile and only raw item
   input, quantity or the existing external portion estimate, and exactly one direct source ref,
   external selection, or explicit pending-capture state. A selection contains only a source ref,
   `relation=semantic_equivalent`, `relation=probable_brand_match`, or the distinct
   `relation=branded_same_type_generic`, plus required relation-specific evidence and a
   human-readable assumption. The CLI re-runs discovery for branded relations, verifies the
   input/profile-bound receipt and candidate eligibility, re-fetches the
   exact ref, validates source integrity and complete finite nutrition, applies generic policy,
   calculates totals, and writes one journal event.

Discovery never reads or writes the user cache. Commit never trusts cached nutrition, a
`searched=true` assertion, or agent
ranking: a source reference is re-fetched through its provider adapter. An accepted selection must
be a source-unbranded generic record and is journaled as `selection_mode=agent_generic`,
`resolution_mode=generic_proxy`, and `provenance=agent_selected`, with raw input, canonical source
name/ref, relation, assumption, accuracy profile, receipt, and deterministic search/provider status.
The older version-1 plan and direct `source_ref` form retain strict compatibility and literal
identity matching. A same-type branded fallback is `selection_mode=agent_branded_generic_fallback`
and remains `generic_proxy`; a text-only brand match is
`selection_mode=agent_probable_brand_match` and `probable_product`. Neither becomes exact without
barcode/label evidence. Pending output includes stable event/item identifiers so correction remains
an explicit remove-and-replace flow.

An external agent may translate language, choose among eligible source identity metadata, and read
a supplied package image. Semantic choice remains outside the CLI; the CLI owns provider fetch,
nutrition validation, arithmetic, policy, and persistence. The agent may propose fuzzy gram
estimates only through the existing validated estimate contract. Such estimates are explicitly
approximate and never provide nutrition facts.

An agent/LLM is not part of the CLI runtime. It must not invent nutrition, silently choose a
different food, bypass confirmation, access SQLite directly, or introduce an embedded model,
credential, prompt corpus, API, or retrieval corpus.

Semantic-retrieval Phase A remains read-only proposal work outside this approved, validated agent
intake contract. It does not mutate cache/logs or aliases, access user SQLite, or change current
resolution. Plans or experiments do not authorize additional runtime behavior.

## Change boundary and non-goals

Changes require explicit scope and tests. A new feature, provider, source, dependency, schema,
migration, log/output behavior, resolution policy, or privacy rule is outside the current
architecture unless an approved issue says otherwise.

The following are non-goals:

- offline coverage through bundled or generated production food data;
- packaged aliases, translations, synonyms, serving weights, or portion assumptions;
- LLM-driven nutrition, identity, provider selection, or persistence inside nomnom;
- silent generic substitution for branded/SKU intent;
- loading the eval-only 100-case corpus or frozen provider responses from production code;
- repository tools that inspect, migrate, seed, copy, or repair real user databases;
- treating `docs/plans.md`, `docs/status.md`, or `docs/test-plan.md` as current architecture.

For implementation decisions, the authority order is `AGENTS.md`, this document, then `README.md`
and `skill/SKILL.md`. Historical plan/status/test-plan material is context only.
