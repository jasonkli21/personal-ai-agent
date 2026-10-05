# Phase 3 implementation plan — Context source and provider abstraction

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Normalize structured domain-context access.

### Normative commitments from the integrated roadmap

- Define context source classes.
- Define provider capabilities/interfaces.
- Normalize context item/provider response.
- Carry provenance, authority, sensitivity, timestamps, and references.
- Wrap existing memory where appropriate.
- Add fixtures.

### Phase acceptance criteria

- Core orchestration does not query domain databases.
- Context retains source identity.

### Explicitly out of scope

- real Travel/Shopping/Finance/Health providers
- context planning policy
- model selection
- direct core access to domain databases

## Current state and reuse

Memory retrieval, evidence and comparison source adapters are implemented; a general bounded domain-context provider protocol is missing.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/context/contracts.py`
- `backend/src/personal_ai/context/assembler.py`
- `backend/src/personal_ai/memory/contracts.py`
- `backend/src/personal_ai/memory/services.py`
- `backend/src/personal_ai/evidence/contracts.py`
- `backend/src/personal_ai/domains/contracts.py`
- `backend/src/personal_ai/domains/providers.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 1, 2. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Distinguish authoritative domain state, AI memory, external evidence, conversation, and client context.
- Do not flatten domain schemas into a universal untyped blob.
- Provider contracts must be independently testable with fakes.

## Work packages

### P3.0 — Typed context vocabulary

**Depends on:** required phases above.

Define source classes, bounded selection and normalized response/item records in the context boundary. Preserve a domain-typed payload rather than a universal untyped dictionary. Items carry source ID/version, owner/app/workspace, entity refs, authority, observation/effective/expiry times, field sensitivity, source refs and permission dependencies. Missing timestamps/authority remain explicit unknowns; client context and external evidence never become authoritative.

**Acceptance:** Typed items preserve source class, scope, authority, sensitivity, expiry and exact references.

### P3.1 — Provider operations and admission

**Depends on:** P3.0.

Define only operations needed by the roadmap (profile/current/entity/history/search), advertised per provider; unsupported operations fail explicitly. Validate allowed fields/time window/entity scope/result and byte bounds before any provider call. Apply owner/app isolation and deny cross-app retrieval by default now; Phase 7 completes sensitivity policy. Timeout/unavailable optional sources return bounded reasons; required-source failure stops preparation rather than retrieving unrelated data.

**Acceptance:** Denied selections produce zero source calls; bounds and required/optional errors are explicit.

### P3.2 — Existing-source wrappers and fixtures

**Depends on:** P3.1.

Wrap validated memory retrieval and immutable research/evidence records without recreating their persistence or freshness logic. Conversation/summary adapters use only the active branch. Add synthetic domain providers; no core domain DB client or real Health/Finance retrieval. Implement the small AI-owned global profile (units, locale, response preferences, application-independent defaults) as a bounded versioned Firestore/repository provider beside the existing context/memory seams, with explicit user-set provenance and permitted field sharing. It is distinct from inferred memory and domain profiles; absent values remain absent. Its read/update contract is owner-authenticated and participates in export/deletion. No domain data is automatically copied into it. Add typed TOOL_RESULT/client-context wrappers only for registered, bounded read capabilities; side effects still require Phase 23. Fake providers record precisely what was requested and disclosed.

**Acceptance:** Existing memory/evidence checks are reused; bounded global-profile and tool/client wrappers work with fakes and export/deletion inventory.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R3.1: Define context source classes. | P3.0 |
| R3.2: Define provider capabilities/interfaces. | P3.1 |
| R3.3: Normalize context item/provider response. | P3.0 |
| R3.4: Carry provenance, authority, sensitivity, timestamps, and references. | P3.0 |
| R3.5: Wrap existing memory where appropriate. | P3.2 |
| R3.6: Add fixtures. | P3.2 |

## Targeted verification and closeout

Test typed source metadata, expired/unknown observations, provider bounds, required versus optional failures, source ordering, foreign scope and zero provider calls on denial.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make memory-eval`, `make research-eval`, `make domain-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Only relevant provider/emulator/cloud/domain/browser checks run opt-in with explicit environment and synthetic data. Local fakes do not establish deployed compatibility.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
