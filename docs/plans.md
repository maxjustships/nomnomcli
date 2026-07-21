# Plans

## Issue #33 Phase A Possessive-Brand P2 Source
- Task: Normalize trailing ASCII and curly possessive-s brand variants for exact-intent evidence without changing ordinary name-token behavior.
- Canonical input: Final Phase A P2 requiring both possessive directions, provider/raw-cache/exact-brand consistency, disjoint semantic generic refusal, source immutability, retained controls, full validation, one local conventional commit, and no push/PR.
- Repo context: `_brand_matches_query`, `_provider_brand_evidence_matches_query`, raw-cache intent protection, exact local pins, semantic CLI regressions, and Phase A no-write guarantees.
- Last updated: 2026-07-21

## Issue #33 Phase A Possessive-Brand P2 Assumptions
- Brand identity alone may remove a terminal ASCII `'s` or curly `’s` from a token; `_name_tokens` and every non-brand comparison retain current behavior.
- The same brand-identity tokens must compare original queries against provider brands, raw cache brands, and exact branded candidates.
- Runtime evidence only is in scope; no static brand corpus, schema/policy changes, persistence, or Phase B application is introduced.

## Issue #33 Phase A Possessive-Brand P2 Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M58 | Freeze possessive-brand regressions and controls | M57 | [x] |
| M59 | Add narrow brand-identity token normalization | M58 | [x] |
| M60 | Run full gates, audit, and commit | M59 | [x] |

## M58. Freeze possessive-brand regressions and controls `[x]`
### Goal
- `Acme's` versus brand `Acme` and `Campbell` versus brand `Campbell’s` both refuse an available disjoint semantic generic plan, for provider and raw-cache evidence, without source writes.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py -k 'possessive_brand or nonmatching_provider_brand or nonmatching_raw_cache_brand or ordinary_food_expression'
```

### Stop-and-Fix Rule
- Do not edit production matching until both directional variants reproduce the bypass while nonmatching brands, ordinary foods, and exact local pins retain their established behavior.

## M59. Normalize possessives only for brand identity `[x]`
### Goal
- A dedicated brand tokenizer removes only terminal ASCII/curly possessive-s before existing comparison normalization, and all provider/raw/exact brand predicates use it consistently.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_foods.py tests/test_cli.py
```

### Stop-and-Fix Rule
- Any general-token change, false match for unrelated brands, exact-pin regression, semantic write, or unrelated resolver behavior change blocks M60.

## M60. Verify and commit the final Phase A P2 `[x]`
### Goal
- Full pytest, repository-wide Ruff, diff checks, and scoped audit pass before one conventional local commit with no push or PR.

### Validation
```sh
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

### Stop-and-Fix Rule
- Do not commit until all requested gates pass and the diff contains only the narrow normalization, regressions, and execution records.

## Issue #33 Phase A Snapshot-Integrity and Explicit-SKU P2 Source
- Task: Protect arbitrary digit-bearing explicit `SKU` markers and refuse semantic resolution from SQLite source files that do not remain stable across a complete private copy.
- Canonical input: Two independent-review P2 findings requiring `SKUABC123`, bounded main/journal/WAL/SHM fingerprint-and-copy retries, structured safe refusal under ongoing writes, deterministic concurrency regressions, full validation, a local conventional commit, and no push/PR.
- Repo context: `_query_has_sku`, `connect_read_only`, semantic CLI regressions, existing WAL/hot-journal/legacy/empty source preservation, README/skill guidance, and Phase A no-write guarantees.
- Last updated: 2026-07-21

## Issue #33 Phase A Snapshot-Integrity and Explicit-SKU P2 Assumptions
- An explicit standalone `sku` prefix followed immediately by alphanumeric, hyphen, or underscore content is exact intent when the complete marker contains at least one digit; existing standalone numeric 4+ and conservative `ABC-12345` detection remain unchanged.
- A copy is usable only when source main, `-journal`, `-wal`, and `-shm` existence/device/inode/size/mtime fingerprints are identical before and after copying every file that existed at the start of the attempt.
- Three private attempts are sufficient to tolerate a transient source-side transition while bounding resolver latency; continued churn returns `database_snapshot_unstable` with `would_write:false` and no plan.

## Issue #33 Phase A Snapshot-Integrity and Explicit-SKU P2 Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M55 | Freeze explicit-SKU and concurrent-copy regressions | M54 | [x] |
| M56 | Implement exact marker detection and stable private copies | M55 | [x] |
| M57 | Document, verify, smoke, audit, and commit | M56 | [x] |

## M55. Freeze both independent-review regressions `[x]`
### Goal
- `SKUABC123` refuses a cached semantic generic candidate, a sidecar transition during copying cannot produce a mixed plan, and permanently unstable fingerprints produce a structured no-write refusal.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py -k 'skuabc123 or snapshot_copy or snapshot_unstable'
```

### Stop-and-Fix Rule
- Do not change production behavior until the explicit marker bypass and unsafe/uncaught snapshot behavior are reproduced while ordinary food, `vitamin B12`, empty/legacy, WAL, and hot-journal controls retain their established expectations.

## M56. Detect explicit markers and require stable private SQLite copies `[x]`
### Goal
- `_query_has_sku` protects arbitrary allowed content after an explicit `sku` prefix when digit-bearing, and `connect_read_only` opens only a private snapshot whose complete source file set was stable across copying.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_db.py tests/test_foods.py tests/test_cli.py
```

### Stop-and-Fix Rule
- Any mixed-state plan, source-side SQLite open/write, uncaught concurrency error, false SKU positive for ordinary controls, or regression in empty/legacy/WAL/hot-journal recovery blocks M57.

## M57. Verify and commit both Phase A P2 fixes `[x]`
### Goal
- README and agent guidance state bounded fail-safe behavior under ongoing writes; targeted/full pytest, repository-wide Ruff, diff checks, disposable no-write smoke, and scoped audit pass before one conventional local commit with no push or PR.

### Validation
```sh
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

### Stop-and-Fix Rule
- Do not commit until all gates pass, the disposable smoke preserves exact source state, and the diff contains only both P2 fixes, regressions, docs, and execution records.

## Issue #33 Phase A Alphanumeric-SKU P2 Source
- Task: Treat common alphanumeric SKU tokens as exact intent during semantic planning without overblocking ordinary food quantities or nutrient terms.
- Canonical input: Final-review P2 requiring Cyrillic `SKU12345` refusal, source immutability, ordinary-food controls, exact local pin preservation, full validation, a local conventional commit, and no push/PR.
- Repo context: `_query_has_sku`, semantic CLI/repository regressions, exact local pin handling, and Phase A no-write guarantees.
- Last updated: 2026-07-21

## Issue #33 Phase A Alphanumeric-SKU P2 Assumptions
- Alphanumeric identifiers are standalone ASCII letter/digit tokens with optional internal hyphen/underscore separators; explicit `SKU` markers containing digits are protected, otherwise at least two letters and four digits are required. Standalone numeric 4+ detection remains unchanged.
- The letter/digit thresholds intentionally exclude ordinary expressions such as percentages, counted foods, `B12`, `D3`, and `omega-3` while covering `SKU12345`, `ABC-12345`, and comparable common codes.
- Existing matching local `exact_product` lookup pins remain the only valid non-provider escape hatch for protected SKU originals.

## Issue #33 Phase A Alphanumeric-SKU P2 Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M52 | Reproduce alphanumeric-SKU semantic bypass and freeze controls | M51 | [x] |
| M53 | Extend conservative SKU detection | M52 | [x] |
| M54 | Run full gates, audit, and commit | M53 | [x] |

## M52. Reproduce alphanumeric-SKU bypass and freeze controls `[x]`
### Goal
- Cyrillic `курица SKU12345` with `brand_intent:false` cannot accept a disjoint translated generic candidate, while normal food expressions and matching exact local pins retain current behavior.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py -k 'alphanumeric_sku or ordinary_food_expression or exact_local_barcode_or_pin'
```

### Stop-and-Fix Rule
- Do not change production detection until the requested bypass fails for the reviewed reason and ordinary-expression/exact-pin controls remain green.

## M53. Detect conservative alphanumeric SKU tokens `[x]`
### Goal
- `_query_has_sku` recognizes common joined/separated letter-digit identifiers and existing numeric codes without classifying short nutrient/portion forms as exact intent.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_foods.py tests/test_cli.py
```

### Stop-and-Fix Rule
- Any false block for the selected ordinary food controls, rejection of a matching exact local pin, or Phase A source mutation blocks M54.

## M54. Verify and commit the alphanumeric-SKU P2 `[x]`
### Goal
- Full pytest, repository-wide Ruff, diff checks, and a scoped audit pass before one conventional local commit with no push or PR.

### Validation
```sh
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

### Stop-and-Fix Rule
- Do not commit until all gates pass and the diff contains only the detector, regressions, and execution records.

## Issue #33 Phase A Raw-Brand Boundary Source
- Task: Treat a matching brand on raw local or migrated legacy cache results as hard exact intent at the central planning boundary.
- Canonical input: Final-review P2 with raw branded-cache refusal, exact local pin/barcode preservation, nonmatching-brand controls, full validation, local commit, and no push/PR.
- Repo context: `FoodRepository._protect_original_intent`, runtime brand-token matching, semantic CLI regressions, and Phase A no-write guarantees.
- Last updated: 2026-07-21

## Issue #33 Phase A Raw-Brand Boundary Assumptions
- Raw cache brand evidence uses the same token-normalizing helper as remote provider brand evidence; no static brand corpus or source mutation is introduced.
- A matching raw brand creates hard exact intent regardless of `legacy` or `generic_proxy` mode, but a matching `exact_product` local pin/barcode remains valid through `_raw_record_satisfies_exact_intent`.
- A nonmatching raw brand does not create hard exact intent, so existing ordinary raw-first behavior remains unchanged.

## Issue #33 Phase A Raw-Brand Boundary Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M49 | Reproduce raw branded-cache bypass and freeze controls | M48 | [x] |
| M50 | Add raw brand evidence to the central intent boundary | M49 | [x] |
| M51 | Run full gates, audit, and commit | M50 | [x] |

## M49. Reproduce raw branded-cache bypass and freeze controls `[x]`
### Goal
- Raw local/migrated cache rows branded `Acme` for original `Acme chicken` fail RED when non-exact, while matching exact pins and nonmatching brand rows keep their current behavior.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py -k 'raw_cache_brand or exact_local_barcode_or_pin'
```

### Stop-and-Fix Rule
- Do not change production behavior until the matching-brand regression fails for the reviewed early-return reason and both controls remain green.

## M50. Protect raw matching brands centrally `[x]`
### Goal
- `_protect_original_intent` treats a matching `raw_food.brand` as hard exact intent using the existing runtime brand-token helper, then delegates valid exact records to the existing exact-intent predicate.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_foods.py tests/test_cli.py
```

### Stop-and-Fix Rule
- Any false block for a nonmatching brand, rejection of a matching exact pin/barcode, source mutation, or unrelated Phase A behavior change blocks M51.

## M51. Verify and commit the raw-brand boundary fix `[x]`
### Goal
- Targeted and full pytest, repository-wide Ruff, diff checks, and scoped audit pass before one conventional local commit with no push or PR.

### Validation
```sh
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

### Stop-and-Fix Rule
- Do not commit until all gates pass and the diff contains only the raw-brand exact-intent fix, regressions, and execution records.

## Issue #33 Phase A Exact-Intent Boundary Follow-up Source
- Task: Fix raw-cache dropped-token and OFF-brand-evidence exact-intent bypasses without changing Phase A persistence or application behavior.
- Canonical input: Two independent-review P2 findings plus targeted/full pytest, Ruff, diff, no-write smoke, local commit, and no-push requirements.
- Repo context: `FoodRepository.plan_resolution`, non-persisting provider resolution evidence, semantic regressions, and Phase A execution records.
- Last updated: 2026-07-21

## Issue #33 Phase A Exact-Intent Boundary Follow-up Assumptions
- Dropped-token specificity is inferred from the original and its supplied semantic candidates before any raw result can be returned.
- Provider brand evidence is observational planner state: a candidate brand whose normalized tokens are contained in the original survives later provider errors, while an unrelated brand never creates exact intent.
- A protected original may still return an actual matching local `exact_product` pin, alias, or barcode; ordinary unprotected raw-first resolution remains unchanged.

## Issue #33 Phase A Exact-Intent Boundary Follow-up Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M46 | Reproduce both exact-intent ordering/evidence bypasses | M45 | [x] |
| M47 | Centralize original-intent inference and protection | M46 | [x] |
| M48 | Run full gates, no-write smoke, audit, and commit | M47 | [x] |

## M46. Reproduce both independent-review bypasses `[x]`
### Goal
- Focused regressions prove a raw generic cache hit cannot preempt dropped-token inference and OFF matching-brand evidence cannot be erased by a later USDA failure.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py -k 'raw_cache_dropped_token or off_brand_match_survives_usda_failure or nonmatching_provider_brand'
```

### Stop-and-Fix Rule
- Do not change production behavior until both bypass regressions fail for the reviewed reasons and the nonmatching-brand control remains green.

## M47. Centralize original-intent inference and protection `[x]`
### Goal
- One original-intent boundary combines declared brand/SKU intent, dropped-token specificity, and provider-observed matching-brand evidence before allowing either a raw plan or semantic candidates.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py
PYTHONPATH=. pytest -q tests/test_foods.py tests/test_cli.py
```

### Stop-and-Fix Rule
- Any regression to ordinary raw-first behavior, exact local pins/barcodes, provider ordering, nonmatching-brand behavior, or no-write guarantees blocks M48.

## M48. Verify and commit the Phase A follow-up `[x]`
### Goal
- Targeted and full pytest, Ruff, diff checks, a disposable no-write smoke, and scoped audit pass before one conventional local commit with no push or PR.

### Validation
```sh
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

### Stop-and-Fix Rule
- Do not commit until all gates pass and the smoke proves exact source bytes, schema/counts, and directory entries remain unchanged.

## Issue #33 Phase A Final Safety Findings Source
- Task: Preserve hot DELETE-mode rollback recovery in private read-only snapshots and recognize provider-evidenced brand-only originals as exact intent.
- Canonical input: Two final independent-review P2 findings plus the user's regression, full validation, disposable no-write smoke, local commit, and no-push requirements.
- Repo context: `connect_read_only`, provider-error exact-intent inference, semantic CLI regressions, documentation, and Phase A execution records.
- Last updated: 2026-07-21

## Issue #33 Phase A Final Safety Findings Assumptions
- A matching existing `-journal` is part of the SQLite source state just like an existing `-wal`/`-shm`; SQLite may recover or delete only the private copy.
- The rollback regression must prove dirty pages reached the source main file before the writer exited, while inspection of source state remains immutable and byte based.
- Brand-only inference uses the returned provider candidate's brand tokens as runtime evidence; it does not add a static brand corpus or change nonmatching non-brand behavior.

## Issue #33 Phase A Final Safety Findings Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M43 | Reproduce hot-journal loss and brand-only bypass | M42 | [x] |
| M44 | Preserve rollback recovery and exact brand intent | M43 | [x] |
| M45 | Run full gates, disposable no-write smoke, audit, and commit | M44 | [x] |

## M43. Reproduce both final safety findings `[x]`
### Goal
- Focused regressions demonstrate that omitting a hot rollback journal exposes dirty uncommitted source pages and that a provider candidate whose brand exactly matches the original can otherwise fall through to a disjoint semantic generic candidate.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py -k 'rollback_journal or brand_only'
```

### Stop-and-Fix Rule
- Do not change production behavior until both focused tests fail for the reviewed reasons and the rollback fixture proves a dirty page was spilled to the main database.

## M44. Copy rollback journals and protect brand-only originals `[x]`
### Goal
- `connect_read_only` copies an existing matching `-journal` into private storage before SQLite opens the copy, and provider-evidenced brand-token equality sets exact intent without static brand data.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_db.py tests/test_foods.py tests/test_cli.py
```

### Stop-and-Fix Rule
- Any lost committed state, source byte/name mutation, WAL side-file regression, non-brand false positive, or Phase A semantic application blocks M45.

## M45. Verify and commit final safety fixes `[x]`
### Goal
- Targeted and full pytest, Ruff, diff checks, a disposable source-state no-write smoke, and scoped audit pass before one conventional local commit with no push or PR.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

### Stop-and-Fix Rule
- Do not commit until all gates pass and the disposable smoke proves exact source main/journal bytes and directory entries remain unchanged.

## Issue #33 Phase A WAL-Safe Snapshot Source
- Task: Ensure read-only semantic resolution never opens the source SQLite database or creates source WAL/SHM side files while preserving valid WAL state.
- Canonical input: Final-review P2 plus the user's WAL regression, read-only-directory, compatibility, verification, smoke, local-commit, and no-push requirements.
- Repo context: `connect_read_only`, semantic CLI regressions, private temporary resources, and Phase A execution records.
- Last updated: 2026-07-21

## Issue #33 Phase A WAL-Safe Snapshot Assumptions
- The source database and any already-present `-wal`/`-shm` siblings can be copied as ordinary files without opening SQLite against the source path.
- SQLite may create, mutate, checkpoint, or remove sidecars only beside the uniquely owned private copy; the migrated working view remains in memory.
- Permission checks are best-effort under the test runner's effective user, but success or structured refusal must never degrade into a source-side SQLite I/O crash.

## Issue #33 Phase A WAL-Safe Snapshot Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M40 | Reproduce unsafe source opening with a pending WAL | M39 | [x] |
| M41 | Copy SQLite files before opening the private snapshot | M40 | [x] |
| M42 | Run full gates, WAL CLI smoke, audit, and commit | M41 | [x] |

## M40. Reproduce source SHM creation from a pending WAL `[x]`
### Goal
- A WAL-mode source with pending committed data and no visible `-shm` proves semantic resolve must preserve exact main/sidecar names and bytes, including continued SHM absence.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py -k 'wal or read_only_directory'
```

### Stop-and-Fix Rule
- Do not alter snapshot production code until the WAL regression exercises pending data and observes the unsafe source-open behavior where the platform reproduces it.

## M41. Copy SQLite files before opening the private snapshot `[x]`
### Goal
- `connect_read_only` copies the main database and existing WAL/SHM files into one private temporary directory, then opens, backs up, and migrates only private state.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_db.py tests/test_cli.py
```

### Stop-and-Fix Rule
- Any source file change, source sidecar creation, pending-WAL data loss, temporary-resource leak, or empty/v1/v2 compatibility regression blocks M42.

## M42. Verify and commit WAL-safe Phase A snapshot `[x]`
### Goal
- Focused and full pytest, Ruff, diff checks, a disposable WAL CLI smoke, and a scoped audit pass before one conventional local commit with no push or PR.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

### Stop-and-Fix Rule
- Do not commit until all gates pass and the disposable CLI smoke proves the source directory gains no files and loses or changes none.

## Issue #33 Phase A Final P2 Source
- Task: Prevent cached legacy/non-exact rows from bypassing SKU/barcode exact intent during read-only semantic planning.
- Canonical input: Independent Codex final P2 review finding plus the user's regression, audit, validation, local-commit, and no-push requirements.
- Repo context: `FoodRepository.plan_resolution`, all raw `_resolve` return routes, CLI read-only database snapshots, semantic regressions, and Phase A documentation.
- Last updated: 2026-07-21

## Issue #33 Phase A Final P2 Assumptions
- The guard belongs at the planning boundary after raw resolution so alias, exact cache, ranked cache, local search, and provider return routes cannot bypass it independently.
- A protected raw result is acceptable only when it is `exact_product` and the original query is bound to its barcode/brand, an exact local name or lookup pin, or an explicit local alias.
- Non-SKU/non-brand raw-first behavior and Phase A's read-only/no-policy/no-log boundary remain unchanged.

## Issue #33 Phase A Final P2 Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M37 | Reproduce legacy cache bypass and freeze valid exact paths | M36 | [x] |
| M38 | Apply one exact-intent guard across raw returns | M37 | [x] |
| M39 | Run full gates, audit, and commit | M38 | [x] |

## M37. Reproduce final P2 and freeze valid exact paths `[x]`
### Goal
- A migrated legacy/non-exact cache row matching `chicken 12345` fails through `nomnom resolve` with structured `exact_resolution_required`, `would_write: false`, and byte-identical source state, while exact local barcode/pin behavior remains accepted.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py -k 'legacy_non_exact or exact_local'
```

### Stop-and-Fix Rule
- Do not change production behavior until the legacy cache regression is observed RED.

## M38. Guard every raw plan return `[x]`
### Goal
- One planning-boundary predicate rejects protected original intent from every raw route unless the returned record is a matching `exact_product`.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_foods.py
```

### Stop-and-Fix Rule
- Any raw cache/search bypass, rejected exact barcode/pin, or changed non-SKU raw-first plan blocks M39.

## M39. Verify and commit final P2 `[x]`
### Goal
- Targeted tests, full pytest, Ruff, diff checks, and scoped audit pass before one conventional local commit with no push or PR.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

### Stop-and-Fix Rule
- Do not commit until every requested gate passes and the diff contains only the Phase A final P2 fix, tests, and execution records.

## Issue #33 Phase A Review-Fix Source
- Task: Resolve all blocking independent-review findings in the current Phase A semantic-resolution diff.
- Canonical input: User-supplied P1/P2 findings and required regressions, verification, smoke, local commit, and no-push constraints.
- Repo context: read-only database preparation, intent validation, exact-intent protection, cached-provider ranking, semantic tests, and Phase A documentation.
- Last updated: 2026-07-21

## Issue #33 Phase A Review-Fix Assumptions
- Supported legacy databases are the existing v1/v2 migration inputs; dry-run planning may migrate only an isolated in-memory copy and must leave the source bytes and logical contents untouched.
- With no embedded brand/synonym dataset, conservative lexical generic detection may approve semantic fallback only when every normalized original token remains represented by the candidate; token-dropping rewrites such as `Acme chicken` to `chicken` require exact resolution.
- A cached USDA `generic_proxy` with USDA provenance/FDC identity was safety-checked before persistence; when its transient data type is unavailable after reopen, it retains safe USDA-generic priority ahead of OFF but below a live Foundation result.

## Issue #33 Phase A Review-Fix Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M34 | Reproduce all blocking review findings | M33 | [x] |
| M35 | Implement non-mutating compatibility and semantic guards | M34 | [x] |
| M36 | Run full gates, disposable smoke, audit, and commit | M35 | [x] |

## M34. Reproduce blocking review findings `[x]`
### Goal
- Focused regressions fail for empty/legacy existing databases, offline explicit-brand bypass, reopened cached-USDA ordering, and whitespace intent before any cache access.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py -k 'empty or legacy or explicit_brand or reopened or whitespace'
```

### Stop-and-Fix Rule
- Do not change production behavior until each review finding has a focused failing assertion.

## M35. Implement review fixes `[x]`
### Goal
- Dry-run resolution uses an isolated migrated database view, rejects invalid originals before repository access, conservatively protects dropped-token exact intent without provider evidence, and ranks safe reopened USDA proxies ahead of OFF.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_db.py tests/test_foods.py tests/test_cli.py
```

### Stop-and-Fix Rule
- Any source database mutation, exact-intent bypass, unsafe semantic product acceptance, or issue #29 regression blocks final verification.

## M36. Verify and commit review fixes `[x]`
### Goal
- Full pytest, Ruff, diff checks, and disposable success/refusal/no-write CLI smoke pass before one conventional local follow-up commit.

### Validation
```sh
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

### Stop-and-Fix Rule
- Do not commit until all gates and byte/count/schema-preserving smoke checks pass.

## Issue #33 Phase A Source
- Task: Add read-only semantic resolution planning for bounded external-agent candidates.
- Canonical input: GitHub issue #33 latest decision-grade plan and the user's Phase A-only contract, benchmark, smoke, commit, and no-push requirements.
- Repo context: semantic contract validation, resolver/provider safety, CLI JSON, temporary SQLite state, README, and agent skill.
- Last updated: 2026-07-21

## Issue #33 Phase A Assumptions
- Intent JSON is one object containing `version`, `original`, `brand_intent`, and `candidates`; each candidate contains `query`, `relation`, and an `assumption` only when required by `generic_fallback`.
- The original query is evaluated first through a dedicated non-persisting resolver; semantic candidates are considered only after the original safely refuses.
- Provider candidates are collected and ranked across all bounded semantic queries before selection so relation, provider quality, confidence, and normalized query ordering are deterministic.
- Phase B log application, semantic policy configuration, stored resolution intent/provenance, and embedded semantic knowledge remain out of scope.

## Issue #33 Phase A Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M31 | Freeze intent, safety, ordering, and no-write contracts | M30 | [x] |
| M32 | Implement semantic planning module, repository path, and CLI | M31 | [x] |
| M33 | Document, validate, smoke, audit, and commit | M32 | [x] |

## M31. Freeze issue #33 Phase A contracts `[x]`
### Goal
- Focused tests specify strict intent v1 validation, original-first resolution, semantic proxy-only safety, deterministic ranking, exact-intent refusal, benchmark routes, and unchanged database counts.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_foods.py tests/test_cli.py
```

### Known Risks
- Calling the existing mutating `resolve()` for provider success would violate the dry-run guarantee even if the outer CLI later rolls back.

### Stop-and-Fix Rule
- Do not wire the CLI until tests prove both successful and refused plans leave cache, logs, aliases, and recipes unchanged.

## M32. Implement semantic planning module, repository path, and CLI `[x]`
### Goal
- `nomnom resolve --food TEXT --intent-json JSON --json` returns a structured, deterministic plan or failure with `would_write: false`, without any mutation-capable fallback.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_semantic.py tests/test_foods.py tests/test_usda.py tests/test_off.py tests/test_cli.py tests/test_db.py
```

### Stop-and-Fix Rule
- Any candidate `exact_product`, unsafe OFF/USDA acceptance, original barcode/brand bypass, weak/first-result selection, or database count change blocks documentation.

## M33. Document, validate, smoke, audit, and commit `[x]`
### Goal
- README and skill document only the dry-run agent workflow; full tests, Ruff, diff checks, disposable success/refusal smoke, scoped audit, and one conventional local commit pass.

### Validation
```sh
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

### Stop-and-Fix Rule
- Do not commit until the full suite and disposable database smoke prove zero cache/log/alias/recipe writes for both success and refusal.

## Issue #31 Source
- Task: Add opt-in externally agent-estimated fuzzy portions with explicit provenance.
- Canonical input: GitHub issue #31 latest product decision and the user's strict TDD, atomicity, smoke, commit, and no-push requirements.
- Repo context: free-text parsing, provider resolution, nutrition scaling, log JSON persistence, stats, config/CLI policy, README, and agent skill.
- Last updated: 2026-07-21

## Issue #31 Assumptions
- The estimate payload is inline JSON with an `items` array; each entry identifies one fuzzy phrase by both zero-based `item_index` and exact parser `input`, preventing similarity matching.
- Every estimate carries finite nonnegative `grams`, `lower_grams`, and `upper_grams`, confidence in `0..1`, the literal method `agent_estimate`, and a nonempty human-readable assumption; `lower_grams <= grams <= upper_grams`.
- Portion policy defaults to `strict`; `ask` returns an actionable structured request without writing, and `estimate` is the only policy that accepts a complete valid external payload.
- Existing `items_json` can carry additive portion provenance without a schema migration; nutrition continues to use only central `grams` through `scale_food`.

## Issue #31 Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M28 | Freeze fuzzy estimate, mapping, policy, and atomicity contracts | M27 | [x] |
| M29 | Implement external estimate parsing and additive provenance | M28 | [x] |
| M30 | Document, validate, smoke, audit, and commit | M29 | [x] |

## M28. Freeze issue #31 contracts `[x]`
### Goal
- Focused tests specify strict compatibility, exact all-or-nothing estimate mapping, full breakfast persistence/stats, explicit-gram precedence, config policy, and legacy-log readability before production changes.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_portions.py tests/test_cli.py tests/test_config.py tests/test_db.py
```

### Stop-and-Fix Rule
- Record the expected RED failures before changing production parser, model, config, CLI, or persistence behavior.

## M29. Implement external estimate parsing and additive provenance `[x]`
### Goal
- `strict|ask|estimate` policy and exact structured payload validation allow only complete agent-supplied fuzzy masses, persist explicit approximate provenance, and preserve central deterministic nutrition calculation.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_portions.py tests/test_parser.py tests/test_cli.py tests/test_config.py tests/test_db.py
```

### Stop-and-Fix Rule
- Any partial write/application, imprecise match, locally generated weight, explicit-gram regression, or issue #29 identity regression blocks documentation work.

## M30. Document, validate, smoke, audit, and commit `[x]`
### Goal
- README and agent guidance publish the exact schema, correction route, and non-measured semantics; all focused/full tests, Ruff, disposable mocked-provider CLI smoke, diff audit, and one scoped conventional commit pass.

### Validation
```sh
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

### Stop-and-Fix Rule
- Do not commit until full validation passes, the exact breakfast smoke uses only a temporary database and mocked providers, and the diff is scoped to issue #31.

## Issue #29 Source
- Task: Ensure unbranded foods resolve only to truthful generic proxies, never arbitrary branded exact products.
- Canonical input: GitHub issue #29 and the user's strict TDD, smoke, commit, and no-push requirements.
- Repo context: resolver intent, OFF/USDA selection, local cache/aliases, CLI/API JSON, docs, and agent skill.
- Last updated: 2026-07-21

## Issue #29 Assumptions
- Exact identity is established only by user barcode capture, an explicit brand/SKU match in the query, or an exact local pin/alias; provider confidence alone cannot establish exact identity.
- USDA generic lookup should request and rank Foundation/SR Legacy records ahead of any branded data, without embedding nutrition facts or food aliases in production.
- A branded OFF source may represent an unbranded query only as an explicitly assumed generic proxy after strict name/category/core-nutrient checks.

## Issue #29 Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M25 | Freeze identity, provider, cache, policy, and literal contracts | M24 | [x] |
| M26 | Implement intent-aware generic proxy resolution | M25 | [x] |
| M27 | Document identity semantics and verify release gates | M26 | [x] |

## M25. Freeze issue #29 contracts `[x]`
### Goal
- Focused tests reproduce arbitrary branded OFF exact matches, realistic USDA generic-versus-branded ranking, exact user intent, cache isolation, all policies, and the literal acceptance list.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_foods.py tests/test_usda.py tests/test_off.py
```

### Stop-and-Fix Rule
- Record the expected RED failures before changing resolver/provider production behavior.

## M26. Implement intent-aware generic proxy resolution `[x]`
### Goal
- Unbranded input returns only a clearly sourced safe generic proxy or structured `food_needs_source`; exact user intent remains exact-only and cache entries cannot cross identity boundaries.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_foods.py tests/test_usda.py tests/test_off.py tests/test_cli.py
```

### Stop-and-Fix Rule
- Any arbitrary branded `exact_product`, generic fallback for branded/barcode intent, unsafe cache write, or missing provenance blocks documentation work.

## M27. Document identity semantics and verify release gates `[x]`
### Goal
- README and agent skill distinguish exact products from generic proxies, and all tests, lint, literal isolated smoke, diff audit, and local commit requirements pass.

### Validation
```sh
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

### Stop-and-Fix Rule
- Do not commit until the full suite, Ruff, clean temp-data smoke, and scoped diff audit pass.

## Issue #27 Source
- Task: Add safe backdated meal logging and local-date-scoped stats.
- Canonical input: GitHub issue #27 and the user's strict TDD, smoke, commit, and no-push requirements.
- Repo context: CLI argument contracts, local-time timestamp handling, SQLite log queries, tests, README, and agent skill.
- Last updated: 2026-07-21

## Issue #27 Assumptions
- The process local timezone is the user local timezone; tests set `TZ` and call `time.tzset()` where available.
- A supplied date maps to local 12:00:00 with the offset active on that calendar day; it is persisted as the existing ISO-8601 `logged_at` field, so no schema migration is required.
- Date-scoped stats use a half-open interval from local midnight on the requested date to local midnight on the next date.
- `today` and `week`, existing rows, food cache, aliases, and recipes retain their current contracts.

## Issue #27 Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M21 | Freeze date parsing, timestamp, and no-write contracts | M20 | [x] |
| M22 | Implement backdated parsed/direct logging | M21 | [x] |
| M23 | Implement date-scoped stats and preserve old periods | M22 | [x] |
| M24 | Update guidance, validate, smoke, audit, and commit | M23 | [x] |

## M21. Freeze date parsing, timestamp, and no-write contracts `[x]`
### Goal
- Controlled-timezone tests specify literal `2026-07-20`, deterministic local noon, malformed/impossible/future errors, and unchanged default behavior before production changes.

### Tasks
- [x] Add CLI and database behavior tests.
- [x] Witness the focused tests fail for the expected missing behavior.

### Definition of Done
- Tests cover both parsed and direct log forms, JSON date fields, adjacent-day exclusion, no-write failures, and no-date compatibility.

### Validation
```sh
TZ=Asia/Almaty PYTHONPATH=. pytest -q tests/test_cli.py tests/test_db.py
```

### Known Risks
- Offset-aware ISO strings sort correctly only when query bounds use the same local timezone contract; DST boundaries require constructing each local midnight independently.

### Stop-and-Fix Rule
- Do not modify production date behavior until the new focused tests are observed RED.

## M22. Implement backdated parsed/direct logging `[x]`
### Goal
- `--date YYYY-MM-DD` safely stores local noon and returns effective `logged_at` plus `local_date` for either log form.

### Validation
```sh
TZ=Asia/Almaty PYTHONPATH=. pytest -q tests/test_cli.py -k 'date or backdated'
```

### Stop-and-Fix Rule
- Any invalid/future input write or default-log regression blocks M23.

## M23. Implement date-scoped stats and preserve old periods `[x]`
### Goal
- `stats date YYYY-MM-DD` returns only entries in the requested local calendar day while `today` and `week` remain compatible.

### Validation
```sh
TZ=Asia/Almaty PYTHONPATH=. pytest -q tests/test_db.py tests/test_cli.py -k 'stats or date'
```

### Stop-and-Fix Rule
- Adjacent local-day leakage or a changed existing period contract blocks M24.

## M24. Update guidance, validate, smoke, audit, and commit `[x]`
### Goal
- Humans and agents use the CLI rather than SQLite; all requested gates and literal disposable CLI commands pass before one local commit.

### Validation
```sh
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

### Stop-and-Fix Rule
- Do not commit until full tests, Ruff, checkout-import proof, clean disposable smoke, and diff/status audit pass.

## Issue #23 Source
- Task: Make no-key base mode a successful safe product and USDA an optional coverage enhancement.
- Canonical input: GitHub issue #23 and the user's strict TDD, smoke, commit, and no-push requirements.
- Repo context: onboarding/status, installer, resolver errors and OFF provenance, tests, README, and agent skill.
- Last updated: 2026-07-21

## Issue #23 Assumptions
- OFF barcode lookup, source-backed label capture, user cache, and aliases define useful base coverage even when OFF full-text or USDA is unavailable.
- `installed_and_ready` requires both a configured and reachable USDA provider; every other verified install is `installed_base_ready` unless login PATH repair takes priority.
- Unbranded high-confidence OFF results may retain `exact_product` when source identity is a real named product, or become `generic_proxy` when the source product identity is generic; brand/SKU queries never receive a generic proxy.
- Tests and installer smoke use only checkout-local artifacts and local network stubs; no public install or live provider request is allowed.

## Issue #23 Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M17 | Freeze base/enhanced setup and doctor contracts | M16 | [x] |
| M18 | Make fresh installer completion base-ready | M17 | [x] |
| M19 | Implement safe no-key OFF resolution and actionable source errors | M18 | [x] |
| M20 | Update installation/agent UX and run release verification | M19 | [x] |

## M17. Freeze base/enhanced setup and doctor contracts `[x]`
### Goal
- No-key status is `base_ready` with base generic coverage and explicitly optional USDA enhancement; reachable configured USDA is connected/enhanced.

### Tasks
- [x] Add and witness RED setup/status capability tests.
- [x] Implement the minimal additive capability model and interactive optional-enhancement copy.
- [x] Preserve credential redaction and independent OFF capability reporting.

### Definition of Done
- Setup JSON and text treat the no-key product as ready and disclose enhanced coverage without portraying base as failed.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_config.py tests/test_cli.py
```

### Known Risks
- Doctor JSON is consumed by the shell installer, so fields must remain additive and parseable.

### Stop-and-Fix Rule
- Record RED before onboarding implementation; repair focused regressions before M18.

## M18. Make fresh installer completion base-ready `[x]`
### Goal
- A verified no-token install succeeds as `installed_base_ready`, while reachable USDA is `installed_and_ready` and PATH repair remains highest priority.

### Tasks
- [x] Add and witness RED installer JSON/human and agent-isolation contracts.
- [x] Add base/enhanced coverage and optional setup information without weakening sanitized verification.
- [x] Keep genuine installation/verification failures as `error`.

### Definition of Done
- Installer tests cover no-key, enhanced, PATH repair, malformed doctor JSON, and inherited-agent isolation.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_install.py
```

### Known Risks
- POSIX shell JSON construction must remain valid for multiline doctor output and constrained utility PATHs.

### Stop-and-Fix Rule
- Do not change installer behavior until its new status contract is observed RED.

## M19. Implement safe no-key OFF resolution and actionable source errors `[x]`
### Goal
- Strict high-confidence OFF results resolve with truthful provenance; unsafe or unavailable results return one no-key-first `food_needs_source` action contract.

### Tasks
- [x] Add and witness RED tests for exact/generic OFF identity, weak/wrong-type, unavailable OFF, and brand/SKU denial.
- [x] Preserve category/token/core-nutrient thresholds and prevent rejected candidates from cache/log writes.
- [x] Replace first-screen raw USDA-key failures with photo, barcode, label capture, cache, and optional-USDA guidance.

### Definition of Done
- No-key users either receive a safe source-backed food or a structured actionable source request; no generic brand substitution occurs.

### Validation
```sh
PYTHONPATH=. pytest -q tests/test_off.py tests/test_foods.py tests/test_cli.py tests/test_capture.py
```

### Known Risks
- Existing tests intentionally preserve the pine-nuts/cheese incident and may not be weakened.

### Stop-and-Fix Rule
- Any unsafe candidate acceptance, failed-write side effect, or provenance ambiguity blocks M20.

## M20. Update installation/agent UX and run release verification `[x]`
### Goal
- Documentation makes no-token installation a successful completion and the checkout passes every requested gate and disposable installer smoke.

### Tasks
- [x] Update README and `skill/SKILL.md` installation/limitation language.
- [x] Run full pytest, Ruff, diff audit, and checkout-import verification.
- [x] Run a disposable user-level installer against this PR source with temp HOME/tool bins and local provider stubs, then create one scoped conventional commit.

### Definition of Done
- Exact outputs are recorded in status/final notes; one local commit exists; nothing is pushed and no PR is opened.

### Validation
```sh
PYTHONPATH=. pytest -q
ruff check .
git diff --check
```

### Known Risks
- Installer source selection must be overridden locally without changing the production public source contract.

### Stop-and-Fix Rule
- Do not commit until all gates and the literal fresh no-key smoke pass.

## Issue #19 Source
- Task: Implement the v0.4 zero-friction source-backed capture slice.
- Canonical input: GitHub issue #19 plus the user's explicit default-policy override.
- Repo context: provider policy, runtime resolver, capture CLI, user SQLite schema, tests, README, and agent skill.
- Last updated: 2026-07-21

## Issue #19 Assumptions
- `allow_for_unbranded` is the default despite the issue body's older `ask` default.
- A USDA proxy is eligible only when the returned record passes existing nutrition/confidence checks, is a generic data type with no brand, has an FDC id, and covers every normalized query token; unmatched brand/SKU-like input therefore stays exact-only.
- Package-photo OCR/vision remains agent-side. The CLI accepts only extracted facts and a mandatory local source reference and never stores the image.
- Schema version 4 is the additive migration boundary already started on this branch; issue #19 completes that explicit v3-to-v4 migration rather than introducing a second version number.

## Issue #19 Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M13 | Add failing policy, proxy, capture, migration, and smoke contracts | M12 | [x] |
| M14 | Implement v4 provenance and deterministic capture/resolution | M13 | [x] |
| M15 | Document v0.4 agent flow and privacy contract | M14 | [x] |
| M16 | Run full validation, smoke, audit, and local commit | M15 | [x] |

## M13. Add failing issue #19 acceptance contracts `[x]`
### Goal
- Freeze the user-visible policy, JSON, endpoint, persistence, migration, and clean-install behavior before runtime implementation.

### Validation
```sh
pytest -q tests/test_config.py tests/test_foods.py tests/test_off.py tests/test_cli.py tests/test_db.py
```

### Stop-and-Fix Rule
- Record expected RED failures before production changes; no live provider traffic or personal-image fixture may enter tests.

## M14. Implement v4 provenance and deterministic capture/resolution `[x]`
### Goal
- Source-backed unbranded USDA proxies and exact OFF/package captures persist and replay with explicit mode and provenance.

### Validation
```sh
pytest -q tests/test_config.py tests/test_foods.py tests/test_off.py tests/test_cli.py tests/test_db.py
```

### Stop-and-Fix Rule
- Reject incomplete nutrition, unsafe/branded generic substitution, blank provenance, and failed capture without cache or log writes.

## M15. Document v0.4 agent flow and privacy contract `[x]`
### Goal
- README and agent skill give exact commands and direct agents to request a photo—not manual label lookup—when exact package facts are needed.

### Validation
```sh
pytest -q tests/test_install.py tests/test_cli.py
ruff check .
```

### Stop-and-Fix Rule
- Keep docs aligned with executable syntax and stable JSON fields before release validation.

## M16. Run full validation, smoke, audit, and local commit `[x]`
### Goal
- Produce one coherent, validated local conventional commit with no push or PR.

### Validation
```sh
pytest -q
ruff check .
git diff --check
```

### Stop-and-Fix Rule
- Do not commit until full tests, Ruff, literal isolated-DB smoke, and diff audit all pass.

## Issue #17 Source
- Task: Fix the Open Food Facts full-text provider contract without live-test traffic.
- Canonical input: GitHub issue #17 and the user's required behavior.
- Repo context: `nomnomcli/off.py`, provider onboarding/doctor output, focused tests, README, and agent skill.
- Last updated: 2026-07-21

## Issue #17 Assumptions
- OFF's legacy production full-text endpoint is `https://world.openfoodfacts.org/cgi/search.pl`.
- Product/barcode reachability and full-text readiness are independent capabilities and must be reported separately.
- Existing user-cache and USDA fallback behavior remains unchanged; OFF never substitutes v2 catalog rows for failed full-text search.

## Issue #17 Milestone Order
| ID | Title | Depends on | Status |
| --- | --- | --- | --- |
| M9 | Add failing OFF v1 and readiness contract tests | M8 | [x] |
| M10 | Implement v1-only full-text and split probes | M9 | [x] |
| M11 | Document status semantics and validate | M10 | [x] |
| M12 | Audit and commit scoped changes | M11 | [x] |

## M9. Add failing OFF v1 and readiness contract tests `[x]`
### Goal
- Capture endpoint, parameter, semantic, retry, no-fallback, confidence, and doctor contracts before implementation.

### Validation
```sh
pytest -q tests/test_off.py tests/test_foods.py tests/test_config.py tests/test_cli.py
```

### Stop-and-Fix Rule
- Record the expected RED failures before modifying runtime code.

## M10. Implement v1-only full-text and split probes `[x]`
### Goal
- Free text uses only the capability-probed v1 CGI endpoint; v2 remains product/barcode-only.

### Validation
```sh
pytest -q tests/test_off.py tests/test_foods.py tests/test_config.py tests/test_cli.py
```

### Stop-and-Fix Rule
- Never add a v2 free-text fallback or live-network test to make a contract test pass.

## M11. Document status semantics and validate `[x]`
### Goal
- README, setup output, and `skill/SKILL.md` explain product reachability versus full-text resolution readiness exactly.

### Validation
```sh
pytest -q tests/test_off.py tests/test_foods.py tests/test_config.py tests/test_cli.py tests/test_install.py
pytest -q
ruff check .
```

### Stop-and-Fix Rule
- Repair any focused, full-suite, or lint regression before committing.

## M12. Audit and commit scoped changes `[x]`
### Goal
- Commit only coherent issue #17 code, tests, docs, and execution records before the separate push/PR step.

### Validation
```sh
git diff --check
git status --short
git diff --stat
```

### Stop-and-Fix Rule
- Do not commit until the diff is scoped and every acceptance gate passes.

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
