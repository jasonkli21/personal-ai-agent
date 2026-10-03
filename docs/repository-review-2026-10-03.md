# Repository maintainability and implementation review

**Date:** 2026-10-03. **Reviewed base:** `4ff354b6f881fa87550fd442b5b5240c365f86e5`, plus the uncommitted cleanup changes in this working tree. **Environment:** local synthetic/offline validation; no real provider, emulator, cloud deployment, or personal data.

## Outcome and implementation completeness

The existing architecture is sound enough to retain: thin Next.js proxies and API routes, backend-owned orchestration, provider-neutral model/context contracts, owner-scoped repositories, separate durable memory and expiring external evidence, deterministic constraints, and bounded research. This review makes contained corrections within those boundaries. It introduces no replacement framework, dependency upgrade, broad migration, or new product feature.

Phases 1–8 have local implementations. Their bounded scope is deliberate: research synthesis returns validated source excerpts; iterative automatic claim proposals are limited to supported literal prices; Nominatim supplies places and Open Food Facts supplies catalog identity, without live lodging/merchant offers. Experimental gates remain default-off. These are documented capabilities, not evidence that every roadmap aspiration or external acceptance check is complete.

The assumption that all major phases are complete does not hold for Phase 9. Local authentication, request safeguards, private-service deployment plumbing, maintenance, export and deletion-request records exist, but physical deletion, full legacy migration, complete provider accounting, operational telemetry/recovery, and release promotion gates are unfinished. Earlier documentation incorrectly described authentication and Phase 9 as entirely future work; README, brief, architecture, API contract, deployment checklist, agent handoff, and operational references now describe the implemented boundary and open acceptance work accurately. Historical release records retain their tested-revision context.

## Review coverage

| Area | Reviewed behavior and boundaries |
| --- | --- |
| Chat, context and LLM | Active branches, supersession, turn reservations, stale recovery, terminal writes, cancellation, output bounds, complete-turn budgeting, summary coverage/fallback, shared context use, provider errors and counting |
| Memory and worker | Source/privacy validation, original/derived identities, vector eligibility, scoring, lifecycle events/projections, atomic source checks, leases, retries/recovery, Pub/Sub resources and service identity |
| Research and evidence | Planning, fixed provider endpoints, URL/content policy, extraction, freshness/deduplication, citations, request keys, replay/fencing, bounded aggregates and expiry |
| Decisions and domains | Subject/identifier grounding, aliases, claim provenance, hard constraints, currency/unit uncertainty, ranking fallback, historical snapshots, lookup reservations and provider contracts |
| Iterative research | State transitions, cancellation fences, event cursors, leases, uncertain side effects, resource ledgers, follow-up validation, strict synthesis and shared decision integration |
| Authentication and account | Signed issuer/audience/expiry checks, allowlist/owner mapping, local/deployed separation, same-origin credentials, request limits, safe errors/logs, export encoding/limits and deletion state transitions |
| Frontend | All pages/features/clients/proxies, stale state, navigation guards, GIS reauthentication, stream framing/limits/teardown, CSP, development behavior and feature gates |
| Storage and operations | Firestore schemas, transactions and SDK boundaries, indexes, migration safety, Docker startup, Cloud Run identities, publisher permissions, scheduler/backup defaults and rollback documentation |
| Tooling and artifacts | Dedicated source/test trees, discovery, source/test type separation, lockfiles, CI commands, package fixtures/imports, plans/ADRs/acceptance records and documentation links |

No real datastore/provider behavior is inferred from mocks. Repository-boundary tests simulate SDK interactions; credentials and integration checks stay opt-in.

## Structural cleanup

- Moved all frontend tests and test setup into `frontend/tests`, mirroring their former source hierarchy. Vitest discovers only that tree. `frontend/tsconfig.test.json` checks tests separately; production compilation no longer receives Vitest globals. Backend tests remain under `backend/tests`, separate from `backend/src`.
- Extracted shared branch selection into `backend/src/personal_ai/storage/branches.py`; production Firestore code no longer imports branch rules from `fake.py`. Ancestry validation is linear and rejects missing, foreign and cyclic links.
- Added one shared `storage/async_io.py` bridge for synchronous work used by chat, research, domains and workers. It joins in-flight work before cancellation cleanup, preventing late writes from racing retries.
- Consolidated duplicate memory transaction lifecycle code in the existing transaction helper. Shared bounded Google signing-key transport closes sessions on either verification outcome.
- Extracted chat branch reconciliation into `frontend/src/features/chat/chat-state.ts`; expanded the compressed chat page into readable handlers and JSX.
- Consolidated SSE wire parsing in `frontend/src/lib/sse.ts`, bounding individual frames independently of network chunking.
- Removed unused `PHASE_1_OWNER_ID`, obsolete unconsumed environment placeholders, and an empty feature README. Corrected environment examples and moved-test references.

Large lifecycle and iterative modules were reviewed rather than split solely by line count. Their fenced execution/persistence responsibilities remain cohesive; demonstrated duplication was removed without creating speculative layers. Runtime synthetic fixtures remain source assets because gated demo/evaluation entrypoints consume them.

## Fixed review findings

Each entry is fixed in this working tree unless the status explicitly limits that claim.

| Severity | Area/files | Problem, likely impact and correction |
| --- | --- | --- |
| High | `domains/providers.py`, `tests/test_domains.py` | OFF v3.6 responses were parsed as v2 integer statuses; real success responses were rejected. Parse named v3 statuses, validate barcode identity, and handle actual product-not-found 404 responses. Provider mocks now match the official contract. |
| High | `decisions/service.py`, `ranking/policy.py` | An identifier anywhere in an excerpt could be borrowed from another subject and merge candidates incorrectly. Require an explicit subject-bound identifier assertion; regression rejects unrelated IDs. |
| High | `agents/research/repositories.py`, `tests/test_research_firestore.py` | Maintenance compared native timestamps against stored UTC ISO strings, leaving expiry ineffective. Use the stored representation, account for variable fractional precision, and compare decoded instants before bounded/preconditioned writes. |
| High | `services/chat_turns.py`, `domains/service.py`, `worker.py` | Synchronous storage/provider/token work blocked async handlers. Move it off the event loop and join writes during cancellation; regressions cover responsive health and persistence ordering. |
| High | `features/auth/auth-gate.tsx` | GIS sign-in controls disappeared after signout or rejected/expired identity. Initialize GIS once and render its button into each new container, restoring reauthentication. |
| High | `scripts/migrate_local_owner.py`, `tests/test_account_data.py` | Generic migration added schema-forbidden metadata and broke embedded owners/derived IDs. Chat-only apply now preserves schemas, audits separately, and refuses later-phase legacy data before any writes. **Full-data migration remains open below.** |
| High | `infrastructure/gcp/deploy.sh`, `tests/test_deployment_script.py` | Worker recovery republishes jobs without topic publisher permission. Grant the worker runtime topic-scoped publisher access; fake-CLI regression verifies the binding. |
| Medium | `storage/branches.py`, `memory/repositories.py` | Cyclic stored ancestry could hang branch selection or be accepted as memory provenance. Reject cycles and mismatched stored identities; exercise corrupt paths and a 6,000-message history. |
| Medium | `memory/lifecycle_repositories.py`, `memory/lifecycle_jobs.py` | Optional lifecycle source/discovery calls could outlive their allowance. Propagate remaining RPC deadlines and impose an aggregate post-completion ceiling. |
| Medium | `memory/lifecycle_jobs.py` | Pub/Sub clients were created eagerly and not explicitly released. Construct owned clients only when publishing, bound RPC/future waits, disable hidden retries and stop/close owned resources. |
| Medium | `ranking/policy.py` | Alias resolution retained only the final alias per entity, making matching depend on ordering. Evaluate every owner-attributable alias. |
| Medium | `decisions/firestore.py` | Alias lookup made two sequential queries per entity. Batch groups of 30 under a shared five-second allowance and reject truncated resolution sets. |
| Medium | `decisions/contracts.py`, `decisions/firestore.py` | Later aliases changed old supposedly immutable decision responses. New snapshots freeze alias membership; reconstruction verifies it. **Legacy membership remains open below.** |
| Medium | `ranking/policy.py` | Unknown currency/unit comparisons ignored explicit `fail_closed` on optional constraints. Apply that policy consistently. |
| Medium | `domains/providers.py` | Null/object fields could become purported names/brands through stringification; missing returned barcode fell back to requested identity. Validate types and actual returned identity. |
| Medium | `auth/middleware.py`, `settings.py` | Store/credential discovery ran on the event loop; concurrent first requests could construct duplicate stores. Construct/check stores in worker threads under an initialization lock. Reject required-auth development bypass, non-origin/path-bearing allowlists, non-HTTPS deployed origins and deployed emulator configuration. |
| Medium | `api/account.py`, `auth/account_data.py` | Disabled account dependencies could discover cloud credentials before returning 404; construction errors were opaque. Gate before construction, map failures safely, use typed principals and close per-request clients. Repository tests exercise real account methods, owner isolation, export encoding/limits and deletion replay/state rules. |
| Medium | `auth/middleware.py`, `auth/google_transport.py` | Untrusted request IDs could introduce control sequences into logs, and signing-key HTTP sessions lacked explicit closure. Restrict correlation IDs to a bounded safe alphabet and close verification sessions. |
| Medium | `lib/auth.ts` | Delayed 401s could erase a newer token; authenticated fetch did not enforce its same-origin contract. Clear only the token sent by that request and reject external destinations before attaching identity. No actual external token leak was demonstrated. |
| Medium | Chat and research pages | Conversation navigation, saved research restoration and event reconnection could overlap mutations, overwrite newer state or replace abort controllers. Share active-operation guards, disable mutation controls during navigation, clear stale editors and abort cleanup. |
| Medium | `lib/sse.ts`, chat/research clients | A per-chunk 8KB test rejected valid coalesced research frames. Bound individual frames after incremental parsing, retain aggregate bounds and release readers on interruption. |
| Medium | `middleware.ts`, account/health proxy routes | Development CSP blocked Next's eval source maps; account proxies ignored their gates; health forwarding had no deadline. Permit eval only in development, enforce proxy gates and combine health caller cancellation with a five-second ceiling. |
| Medium | `backend/Dockerfile`, `deploy.sh` | Shell PID 1 did not exec Uvicorn, weakening shutdown signal delivery; Bash-4-only email normalization failed on macOS system Bash. Exec Uvicorn and use portable normalization. |
| Low | Chat composer, domain CSS, examples/docs | IME Enter could submit unfinished text; CSS produced a compatibility warning; configuration/test references and phase/auth status were stale. Respect composition, correct alignment and reconcile documentation. |

The OFF parser correction was checked against its [official response status schema](https://raw.githubusercontent.com/openfoodfacts/openfoodfacts-server/main/docs/api/ref/responses/response-status/response_status.yaml) and [official v3 product endpoint specification](https://raw.githubusercontent.com/openfoodfacts/openfoodfacts-server/main/docs/api/ref/api-v3.yaml). This was specification review, not a live lookup.

## Meaningful remaining findings

| ID / severity | Area/files | Problem and likely impact | Status and reason not fully fixed |
| --- | --- | --- | --- |
| R1 — High | `auth/middleware.py`, `auth/safeguards.py`, `llm/*`, worker | HTTP reservations estimate a few calls and one token amount, but context counting/summary/extraction can make additional calls and process repeated inputs; worker embeddings bypass this accounting. Daily counters do not guarantee a provider expenditure ceiling. | Not fixed beyond correcting documentation. Consistent per-operation reservation/settlement across model/search/embedding/worker adapters needs an agreed accounting policy and coherent interfaces. Keep current counters described as request estimates. |
| R2 — High | `scripts/migrate_local_owner.py`, memory/research/decision/domain repositories | Full Phase 3–8 ownership transfer must remap embedded ownership, owner-derived memory/lifecycle IDs and replay keys while preserving references. A top-level rewrite cannot safely expose those records to OIDC ownership. | Unsafe behavior is fixed by refusing apply before writes; full migration is unimplemented. It requires collection-aware mapping, backup/rollback decisions and validation through repository readers. Chat-only migration has offline coverage; no real migration was run. |
| R3 — High | `auth/account_data.py`, account API, Phase 9 lifecycle docs | Deletion stops at `confirmed_pending_operator`; no immediate access-removal policy, physical/derived-data deletion, completion certificate or deletion-aware restore exists. Backup script support is not a restore drill. | Not implemented in this cleanup. Retention, provider/backups, grace periods and irreversible boundaries require explicit lifecycle decisions. Keep deployed deletion off. Export encoding/limits are tested, but live fidelity and concurrent-read consistency remain unverified. |
| R4 — High | `.github/workflows/quality.yml`, `deploy.sh`, Phase 9 release checklist/runbook | Offline evaluations fail CI correctly, but no versioned configuration/build release record, baseline comparison/promotion gate, alert/dashboard ownership, restore/rollback rehearsal or staged end-to-end readiness evidence exists. Scheduler support also lacks the planned dry-run/run-ledger/dead-letter operational workflow. | Remains a Phase 9 acceptance gap. Completing these requires operator/cloud setup and a reviewed release policy. This task neither deploys nor approves production. |
| R5 — Medium | `storage/firestore.py`, `context/repositories.py`, `decisions/firestore.py` | Chat preparation/recovery/terminal and summary operations retain SDK-default retries/timeouts; decision reconstruction has individually bounded reads without one total allowance. Slow storage can extend requests and cancellation cleanup or exhaust worker-thread capacity. | Event-loop blocking and optional-memory/alias deadlines are fixed; a consistent repository operation deadline remains. This needs coordinated interface changes and failure/recovery tests rather than scattered timeouts. |
| R6 — Medium | Chat/message/memory repositories, `decisions/firestore.py` | Long conversations are repeatedly read in full; several memory validations repeat history work. Decision reconstruction still loads claims/entities individually. Linear branch CPU and batched aliases reduce some cost, but durable reads can grow materially. | Remaining scaling risk, not a demonstrated current outage. Bound branch-head/ancestor access and batch reconstruction when changing these persistence contracts; arbitrary truncation would damage provenance/context. |
| R7 — Medium | `decisions/contracts.py`, `decisions/firestore.py` | Older snapshots have no `alias_ids`, so historical membership cannot be distinguished from aliases introduced later. Their compatibility reader retains the old behavior. | New snapshots are fixed. Backfilling exact old membership without recorded evidence would fabricate history; a deliberate legacy policy/migration is needed. |
| R8 — Medium, plausible/unverified | `domains/contracts.py`, `domains/repositories.py` | Comparison cells repeat full source metadata. Allowed row/cell/source combinations can plausibly exceed Firestore's document limit; there is no aggregate serialized-size guard. A large accepted comparison could fail storage with a generic unavailable response. | No realistic maximal fixture or emulator failure was established in this pass; do not claim data loss. Reproduce through the service and datastore boundary, then choose a compatible aggregate ceiling or representation. |
| R9 — High release verification gap | All production adapters and `infrastructure/gcp` | Real Google sign-in/key rotation, owner mapping, Firestore transactions/indexes/vector search/TTL, Pub/Sub/Scheduler/IAM, deployed browser cancellation, provider terms/retention/quotas, and export/restore fidelity are unverified. A fake test cannot establish them. Existing/inherited IAM also needs inspection before claiming only named invokers can access services. | Requires the opt-in emulator/provider checks and synthetic staging checklist. No credentials or cloud access were used. These are verification gaps, not confirmed failures in each integration. |

Current documented bounds also matter when extending the system: conversation discovery returns 50 recent records without cursor pagination; lifecycle source validation conservatively excludes ancestry beyond its 64-link ceiling. They were not silently relaxed or expanded into new features.

## Tests and validation

| Validation actually run | Result |
| --- | --- |
| `make backend-test` | **501 passed, 12 opt-in skipped**, 513 collected; existing Starlette/httpx deprecation warning |
| `make backend-lint` | Passed |
| `make context-eval` | 5/5 passed |
| `make memory-eval` | 14/14 passed |
| `make memory-lifecycle-eval` | 60/60 fixture/variant results passed |
| `make research-eval` | 13/13 passed |
| `make decision-eval` | 15/15 passed |
| `make domain-eval` | 10/10 passed |
| `make iterative-research-eval` | 18/18 paired fixtures passed |
| `make frontend-test` | **95 passed, 19 files** |
| `make frontend-lint` | Passed |
| `make frontend-typecheck` | Passed for both source and test configurations |
| `make backend-build` | Source distribution and wheel built successfully |
| `uv lock --check --offline --project backend` | Passed; no dependency upgrades |
| Wheel contents/import-boundary inspection | New branch/async/auth helpers and evaluation JSON/schema assets included; tests excluded from wheel |
| `make frontend-build` | Passed; existing Next.js ESLint-plugin configuration warning remains (Vitest also reports the existing Vite CJS-API deprecation warning) |
| Production frontend startup/loopback smoke | `/` and `/account` 200; disabled research page/proxy and export proxy 404; nonce CSP without eval and `nosniff` present; server shut down |
| Deployment fake-CLI regression | Passed under system Bash; no cloud calls; verifies private-service/digest/default-gate and worker publisher arguments |
| `bash -n infrastructure/gcp/deploy.sh` | Passed |
| Ruff formatting of new operator/auth/test files | Passed |
| Source/test separation, internal Markdown links and `git diff --check` | Passed |

Backend validation used Python 3.11.15 and uv 0.11.13. The final frontend test/lint/typecheck/build pass used an existing local Node 22.23.3 runtime and pnpm 11.19.0. An earlier pass and the startup smoke used bundled Node 24.19.0. Python 3.12 and Docker image execution were not locally verified; CI remains configured for those runtimes/images. No emulator/provider/cloud checks were run. The first backend build encountered a sandbox cache-path restriction; rerunning with a writable temporary `UV_CACHE_DIR` succeeded without escalation.

The initial user modification to `frontend/tsconfig.tsbuildinfo` was preserved byte-for-byte. No commit, push or deployment was performed. Remaining work is the concrete R1–R9 closure above; further features should not obscure the open operational acceptance items.
