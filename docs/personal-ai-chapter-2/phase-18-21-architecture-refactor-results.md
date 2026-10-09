# Phase 18–21 architecture refactor — review and implementation results

Date: 2026-10-09. Review baseline and tested base commit: `5b05a9d0f63161c125fc95c8542352ba8f132e4f` (post-remediation main). Verification covers the uncommitted refactor working tree, not that base commit alone. The implementation digest and final counts below identify the tested changes. No provider, deployed, cloud, or database-engine acceptance is inferred from offline checks.

The [revised implementation plan](phase-18-21-architecture-refactor-implementation-plan.md) was saved before substantive refactoring and is the design authority for this effort. Original Phase 18–21 evidence remains historical. [Current state](../current-state.md) is the living implementation boundary.

## 1. Architecture review summary

The proposal's core diagnosis survives independent review: routing's essential complexity is admission, current authority, bounded lineage, reservation and replay, rather than multiple mutually equivalent representations. The post-remediation implementation preserved important safety behavior, but full candidate profiles, strategy input/result/identity copies, execution plans, revalidation booleans and reservation proofs made authority difficult to follow.

The review covered the phase plans, implementation/evidence and remediation history, current registry/routing/usage/artifact/account code, migrations 016–021, tests, ADRs 0021/0022, and future 22/23/24/25.2/26/35 boundaries. The attached document was a proposal, not an instruction to preserve its design.

| Proposal | Final disposition |
| --- | --- |
| P18 static catalog; P19 runtime ledger; P20 orthogonal artifacts | Accepted. Live quota observations leave P18 entirely. |
| Shared owner lifecycle authority | Accepted as one persistence helper/table, without a generic lifecycle framework. |
| Compact canonical decision and narrow strategy view | Accepted. Ranking derives selection; canonical source digests derive count/hash. |
| Exact historical references | Endpoint refs accepted with actual retained definitions. Task policy remains one small immutable snapshot; no unused task registry is introduced. |
| Explicit strategy semantics | Accepted. `semantic_version` and `artifact_id` are manually maintained replay identities; build/source identity is not generated or enforced. |
| Ready-only dispatch permit | Strengthened: the permit is a receipt. A durable one-use claim repeats direct current checks. |
| Reservation and authorization transaction | Mandatory on the common Postgres path; no generic Unit of Work. |
| Minimal lifecycle/root controls | Simplified further: single-child lineage/depth replaces the mutable reselection counter. Auxiliary usage remains root-owned across descendant expiry. Closure derives physical outcome from P19. |
| Staged migration/compatibility | Preserve existing V1 rows read-only, then cut over all active writers/contracts in this effort. No shadow writer, dual-write executor or permanent V2 wrapper. |
| Remove every P19 endpoint projection | Modified. Existing fixed-provider/public-lookup calls retain one secret-free accounting projection until gated workflow integration supplies exact refs. It is immutable audit/adapter metadata, not a second catalog. |

New issues incorporated into the implementation:

- Profile history previously retained high-water versions without historical definitions. Exact replay/audit references needed real retention.
- Reservation verification and authorization publication were separate transactions; caller booleans could substitute for current authority.
- A reusable ready receipt did not prevent duplicate provider sends.
- Quota-window/health lock inversion could deadlock reservation or claim against another owner's settlement on the same endpoint. Sorted windows now precede health; health's bootstrap absence is locked too.
- Static corrections could overwrite fresher provider-header confidence/freshness. Header evidence is preserved while configured ceilings can narrow.
- Transport attribution used the proposed attempt ID instead of the ledger-assigned ID after retry lineage adjustment.
- Caller-supplied closure success could disagree with physical attempt state. Closure now reads the terminal ledger outcome.
- Persisted root deadlines/retention, ranking coverage, event scope/sequence and receipt attribution needed explicit corruption checks.

The Phase 21 concrete data-contract count falls from 22 to 18 (excluding the private common base), despite adding explicit current-authority evidence and a one-use receipt. More substantially, a 32-candidate decision fits below 32 KiB without full-profile amplification. The final design reduces state and equality invariants while retaining checks at the boundaries that actually authorize effects. Hard admission precedes strategies; strategies see references and score features. Future evidence/strategy/transport changes have explicit seams, but no quality collection, scarcity policy, cascade execution, paid routing, BYOK execution or learned policy is implemented.

## 2. Implementation summary

**P18** owns current static endpoint facts and immutable historical definitions. `QuotaBucket` describes topology, operations, ceilings and provenance; it rejects remaining/reset/observation/freshness fields. `EndpointRef` identifies one exact definition. Selected-profile revalidation checks that current definition and frozen requirements inside the dispatch transaction. Unrelated registry changes do not invalidate it. Removed IDs cannot reuse earlier versions.

**P19** owns quota windows/observations, reservations, health, invocations, physical attempts and settlement. `QuotaObservation` represents live facts. Its small connection-aware reservation/proof/claim methods accept neutral invocation/attempt data, never P21 DTOs. They verify scope, exact profile/operation/lineage, pending/fresh state, budget and every required bucket's authority/unit/amount/state. Existing retry, unknown-outcome, aggregation, provenance and retention algorithms remain. Gateway metadata uses the ledger-assigned attempt.

**P20** keeps artifact body/metadata, budgets, storage identity, retention and private API behavior. Only its shared owner fence moves to `postgres_owner_lifecycle.py` and `owner_lifecycle_fences`; boundary error adaptation remains. Routing and usage no longer import artifact implementation to authorize work.

**P21** persists one bounded `RoutingDecision`: request/task policy, candidate refs/rejections/features/evidence references, strategy identity, ranking and reason. `StrategyView` contains only preferences and eligible features. `PreparationIdentity` binds the exact endpoint/serializer/counter, prepared-input digest/count and canonical source subset. No active observation/strategy-result/execution-plan/revalidation/reservation-copy hierarchy remains.

Finalization reloads the decision and checks current P18, injected access/credential/policy/source authority, preparation, quality-floor expiry and root deadline. It reserves P19 capacity and publishes authorization in one transaction/savepoint. Failed publication rolls back all reservation changes. A claim repeats checks, verifies exact ledger attribution and atomically marks the attempt claimed with a dispatch event. The internal one-send callback runs after commit and settles against that exact attempt. Invalid callback results become conservative unknown outcomes. Successful closure requires P19 success; callers cannot assert it independently.

Provider IO cannot share an atomic transaction with an external provider or permission service. The claim commit is the authorization point; expiry is checked again immediately after commit. Crashes or uncertain effects remain conservative. There is no permissive production authorization resolver and no new HTTP routing surface. Existing Gemini workflows remain behind the documented Phase 15 integration boundary.

Migration **022** renames the shared fence, archives old decisions without rewriting their replay horizon, adds immutable endpoint definitions and an attempt-claim timestamp, and creates compact decisions plus normalized bounded events. Its checksum includes SQL, a package initializer, and a self-contained versioned Python data-conversion module; it does not depend on mutable runtime routing or quota code. The hook verifies the V1 registry digest, retains available old profiles, transfers old quota observations into P19, advances active profile/registry identity and fails on conflicting definitions/high-water history. It does not invent missing older definitions. Active schema is `endpoint-registry-v2`; the existing catalog record key remains stable. Historical endpoint payloads carry an independent definition schema version and are decoded by fixed V1/V2 decoders.

Old decision rows are audit-readable within their original retention, explicitly reporting historical strategy unavailable. New ranking replay uses the recorded semantic/artifact identity and retained features/preferences; both identity values are manual, so an implementation change requires an explicit `artifact_id` update and exact build-level provenance is not mechanically enforced. A missing implementation never silently substitutes today's strategy. Maintenance and account export/deletion cover both generations and normalized events. Historical SQL migrations remain unchanged.

## 3. Invariant verification

The retained and expanded tests cover:

- Strict-free/billing/privacy/capability/request-limit/counter admission; paid/BYOK/subscription isolation; no hard-ineligible candidate reaching scoring.
- Immutable exact profile history, selected-profile changes/removal, unrelated catalog changes and corrupt registry/high-water state.
- P19 runtime authority, unknown capacity without invented availability, unavailable/stale authorization denial, health bootstrap/cooldown and shared bucket topology.
- Direct final authorization, no reservation on denial, atomic reservation/publication rollback, exact attempt/bucket attribution, claim once and callback after commit.
- Idempotent concurrent finalization, root reselection/auxiliary budgets, inherited exclusions, source narrowing, stricter requirements and unknown-outcome retry/reselection fences.
- Bounded prompt-free persistence, corrupt ranking/lifecycle/receipt/sequence/scope rejection, replay retention and explicitly recorded strategy identity.
- Existing artifact/account fencing/retention behavior and owner deletion versus authorization.

Offline adapters establish coordination behavior only. Opt-in real-Postgres tests additionally exercise concurrent finalization/claim, deletion, shared quota/health lock ordering, root budgets, rollback, corruption, expiry/event cleanup and a staged SQL/data migration retaining V1 audit rows. Those engine cases are present but unexecuted here.

## 4. Initial refactor validation results

These counts record the original refactor before the 2026-10-09 post-refactor remediation in §8. The §8 results supersede them for the changed routing, migration, accounting, lint, and build checks.

Initial refactor implementation SHA-256: **581da7c53a814689b8ecead7ad1f47c8d80b77d2b89b2c754b1889a985d327d1**. This is the digest of sorted changed backend source/test paths, a NUL separator, eight-byte big-endian file length, and file bytes (excluding generated artifacts and documentation), based on the initial refactor baseline above.

| Check | Result |
| --- | --- |
| `PATH="$PWD/backend/.venv/bin:$PATH" make backend-test backend-lint` | 1,026 passed, 62 skipped, one existing Starlette deprecation warning; Ruff passed. |
| Targeted P18–21, gateway, migration and artifact suites (command below) | 269 passed, 36 skipped; existing Starlette and Pydantic warnings. |
| `cd backend && .venv/bin/python -m pytest -q tests/persistence` | 25 passed, 60 skipped. Engine/cloud gates skipped. |
| `make backend-build` with the existing venv and temporary UV cache | Source distribution and wheel built successfully. |
| `python -m compileall -q backend/src` with temporary bytecode cache | Passed. |
| Nine Makefile offline evaluation targets | Passed: context, context-plan, memory, memory-lifecycle, research, decision, domain, iterative-research, itinerary-proposal. No failed case reported. |
| Documentation link/content review and `git diff --check` | Passed; no missing relative links in changed documents. |

Targeted command, from `backend`:

```sh
.venv/bin/python -m pytest -q tests/test_endpoint_registry.py tests/test_postgres_routing.py tests/test_provider_usage.py tests/test_provider_usage_api.py tests/test_artifacts.py tests/test_routing_phase21.py tests/test_routing_migration.py tests/test_litellm_gateway.py tests/persistence/test_routing_decisions.py tests/persistence/test_provider_usage_accounting.py tests/persistence/test_artifact_tier.py
```

PostgreSQL 17/pgvector binaries were available, but isolated `initdb` attempts (including an approved unsandboxed attempt) failed at `shmget(... size=56 ...)` with **No space left on device**. No server started and no migration was applied to an existing database. This was a host shared-memory failure, not an automatic-approval rejection. Docker was unavailable. PostgreSQL locking/migration, DynamoDB Local, live provider, cloud/IAM, account/free-tier/privacy and deployment checks remain unverified. Skipped tests are not passes.

The backend has no separate configured type-check command; Ruff and compilation are its static checks. No frontend behavior/code changed. Existing dependency deprecation warnings are recorded separately from test failures. There are no known failing offline checks in the final tree.

## 5. Remaining follow-ups

**Required acceptance:** run migrations through 022 and the opt-in persistence suites against an isolated healthy Postgres/pgvector and DynamoDB Local environment before deployment; specifically execute the staged migration and concurrency cases. Inspect real historical data, if any, for missing definitions and conflicts rather than discarding it. This is validation still required, not an unfinished parallel executor.

**Existing integration gates:** complete Phase 15 membership and derived-context revocation acceptance, then connect real application preparation/current authority and a one-send transport to the internal coordinator. Provider/account/privacy/free-tier/cloud acceptance remains separate. This refactor does not expand those previously gated capabilities.

**Conditional cleanup:** remove legacy rows/reader/table when their retention/deletion condition is satisfied; remove the fixed-provider projection bridge when real routed call sites pass exact refs. No unconditional temporary dual-write or old execution-plan cleanup remains.

**Optional future work:** Phases 22–24 evidence/scarcity/cascade systems, richer task features/learned strategies, new provider quota/transport types, explicit paid/BYOK and application/UI routing. None is required to operate the refactored internal contracts.

## 6. Files changed

| Group | Main files |
| --- | --- |
| P18 | `routing/contracts.py`, `routing/definitions.py`, `routing/registry.py`, `persistence/postgres_routing.py`, `routing/__init__.py` |
| P19 | `usage/quota.py`, `usage/contracts.py`, `usage/profiles.py`, `persistence/postgres_usage.py`, `llm/litellm_gateway.py` |
| P20/shared lifecycle | `persistence/postgres_owner_lifecycle.py`, `postgres_artifacts.py`, `postgres_auth.py`, `auth/owner_data.py` |
| P21 | `routing/phase21.py`, `routing/strategy.py`, `routing/service.py`, `persistence/postgres_routing_observations.py` |
| Persistence/migration | `persistence/postgres.py`, `routing_migration.py`, `migrations/022_routing_authorities.sql`, `migrations_py/022_routing_authorities.py`; export/maintenance/inventory changes above |
| Tests | Endpoint registry, Postgres registry, migration, routing, provider usage, artifacts and LiteLLM tests; persistence routing/usage suites |
| Docs | Revised plan, this report, current state/router, root/Chapter 2/storage READMEs and P18–21 guides |

Backend paths above are relative to `backend/src/personal_ai/`, test paths to `backend/tests/`. Pre-existing unrelated untracked review/handoff documents were preserved. No credentials or private user data were introduced; no deployment was made.

## 7. Residual compatibility debt

| Item | Why it remains | Exact removal condition |
| --- | --- | --- |
| `routing_decisions_legacy`, scoped audit reader and export/deletion/purge branches | Existing V1 replay/audit data must survive its original horizon. Old semantics are not available for equivalent replay or dispatch. | Zero retained legacy rows after expiry or owner deletion, verified on the target database; then a dedicated migration drops the table and removes its reader/inventory/maintenance branches. |
| Fixed-provider `ProviderEndpoint` accounting projection/resolver mapping | Current gated Gemini and public lookup adapters require safe attribution before application routing is enabled. It is produced once, revalidated against current P18, and never owns mutable catalog/quota truth. | Phase 15 acceptance plus routed application integration passes exact refs at those existing fixed call sites. Public lookup retains its explicit descriptor until it becomes a registered endpoint. |
| Stable `endpoint-registry-v1` storage record key and historic migrations | Storage identity/checksum history must remain readable; payload schema is V2. | No cleanup required. Rename only through a separately justified data migration. |
| Retained immutable definitions | Durable audit configuration, not temporary duplicate runtime state. No user prompts/secrets are stored. | An explicit future retention policy must prove no retained usage/routing record requires a definition before any deletion. No automatic purge is introduced. |

There is no active V1 routing writer, strategy executor, execution plan, boolean revalidation, reservation DTO or dual-write adapter left to remove.

## 8. Post-refactor remediation and validation

Date: 2026-10-09. Tested source tree is based on commit `7a29e841f687ee1b76f2191b31199b78f72ed144` plus the remediation changes recorded in this commit. The checks below exercised offline behavior only unless stated otherwise.

Remediation backend code/test SHA-256: **566a959bdc42ffeb296a720ad892d5d0938b95f9a6e31cc64a6e363c73270b6d**. The digest covers sorted changed `.py`/`.sql` paths under `backend/src` and `backend/tests`, hashing each repo-relative UTF-8 path, a NUL byte, an eight-byte big-endian file length, and the file bytes.

| Handoff finding | Disposition |
| --- | --- |
| P21's 32-event ceiling could reject a valid maximum-budget request after dispatch | Raised the event bound to 128 (covers 32 physical attempts, 16 auxiliary calls, and lifecycle transitions), with a 2 MiB aggregate and 16 KiB per-event limit. Finalization/claim preflight required follow-up capacity before reservation or consuming the one-use claim. Boundary tests cover both. |
| Migration 022 depended on mutable runtime code | Replaced the runner's mutable hook with the frozen `migrations_py/022_routing_authorities.py`; its only imports are standard library modules. The migration checksum covers SQL, the versioned module, and its package initializer. The legacy module is a compatibility wrapper and is not checksummed or used by the runner. |
| Endpoint history used current-model decoding | Added an independent `definition_schema_version` and fixed V1/V2 decoders. Historical definitions no longer use the active `EndpointProfile` validator; unknown schema versions and identity conflicts fail explicitly. |
| P19 budget/unresolved checks crossed logical request boundaries | The advisory lock, unresolved-send fence, attempts and token totals now use owner/application/null-safe workspace/request. `run_id` stays attribution only, so runs in the same logical request share limits. P21's unresolved-send reselection check uses the same application/workspace scope. |
| Strategy artifact identity could be mistaken for a build hash | Documentation and code comments now say `semantic_version` and `artifact_id` are manually maintained. Behavior changes require an explicit `artifact_id` change; source/build provenance is not automatically enforced. |
| Engine acceptance required real Postgres and DynamoDB Local | Offline and opt-in cases now cover scope isolation, shared run budgets, maximum event capacity, and application-scoped reselection. Real-engine execution remains open: Docker is unavailable; `initdb` failed twice at shared-memory allocation (`shmget`, `No space left on device`), no server started, and no database was migrated. DynamoDB Local is unavailable. |

Validation on 2026-10-09:

| Check | Result |
| --- | --- |
| `PATH="$PWD/backend/.venv/bin:$PATH" PYTEST_ADDOPTS=-q make backend-test backend-lint` | 1,032 passed, 67 skipped, one existing Starlette deprecation warning; Ruff passed. Skips include opt-in persistence cases. |
| `PATH="$PWD/backend/.venv/bin:$PATH" UV_CACHE_DIR=/private/tmp/personal-ai-remediation-uv-cache make backend-build` | Source distribution and wheel built successfully. |
| `cd backend && .venv/bin/python -m compileall -q src` | Passed. |
| Nine Makefile offline evaluation targets: context, context-plan, memory, memory-lifecycle, research, decision, domain, iterative-research, itinerary-proposal | Passed; synthetic/offline only. |
| Real PostgreSQL/DynamoDB Local suites | Not run; local services could not be started for the reasons above. No real migration or concurrency behavior is claimed. |
| Documentation link/content review and `git diff --check` | Passed; all relative targets in seven changed Markdown files resolve, with no whitespace errors. |

The real-engine acceptance requirement remains: run migration 022 and the opt-in persistence suites against isolated, healthy PostgreSQL/pgvector and DynamoDB Local services before deployment. No cloud, provider, deployed, or production-security acceptance is inferred from these offline results.
