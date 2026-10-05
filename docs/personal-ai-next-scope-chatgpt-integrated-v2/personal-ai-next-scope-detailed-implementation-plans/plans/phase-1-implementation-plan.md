# Phase 1 implementation plan — Application and workspace identity

This is the detailed execution plan for integrated next-scope **Phase 1 — Application and workspace identity**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Make every request explicitly application-aware.

### Normative commitments from the integrated roadmap

- Add/verify `application_id`.
- Add optional `workspace_id`.
- Thread identity through API, conversation, memory scope, tracing, and tools.
- Define canonical app IDs.
- Preserve standalone use.

### Phase acceptance criteria

- App namespaces cannot leak.
- Existing chat works.
- Traces identify app/workspace.

### Explicitly out of scope

- application registry policy
- cross-app permissions
- domain database access
- new domain features

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/api/`
- `backend/src/personal_ai/context/`
- `backend/src/personal_ai/memory/`
- `backend/src/personal_ai/domains/`
- `frontend/`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

`AuthenticatedPrincipal` in `auth/contracts.py` and owner-only `Conversation`/`Message` in `entities/conversation.py` are the current identity seam. Extend API schemas, owner-scoped repository contracts, chat services, and the Next.js proxy together; no `application_id` or `workspace_id` is currently persisted. Phase 1 is the first new implementation phase, not a rerun of existing repository Phase 1. Keep deployed owner verification authoritative and preserve old conversation access through an explicit standalone identity/migration rule. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make context-eval`, `make memory-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- Treat standalone chat as a canonical application identity, not a bypass.
- Never accept application/workspace identity as authority for ownership; authenticated principal remains authoritative.
- Workspace is optional and must have explicit null/no-workspace semantics.
- Existing conversation IDs and owner scoping must remain valid.

## Dependency map

**Prerequisites:** Phase 0

```text
P1.0 Identity/request-envelope -> P1.1 API
P1.1 API -> P1.2 Conversation
P1.2 Conversation -> P1.3 Tool/tracing/context
P1.3 Tool/tracing/context -> P1.4 Backward
```

The map is sequencing guidance, not a requirement to commit once per work package. Prefer a few coherent commits that preserve reviewable boundaries.

## Required verification matrix

- Offline unit/contract tests cover success plus malformed/denied/unavailable/error paths for each new contract.
- Integration tests prove the phase composes with the existing owner/application/workspace and context boundaries.
- Regression tests prove the phase-disabled/default path preserves prior behavior.
- No automated test requires live provider credentials, a real GCP project, or personal data unless explicitly marked opt-in.
- Safe tracing/evidence records IDs, counts, versions, states, and reason codes without raw secrets or unnecessary private content.
- Documentation/release evidence states exactly which external provider/emulator/cloud checks were run, skipped, or remain open.

## Required implementation artifacts

- Code/configuration changes required by the work packages below, limited to Phase 1 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 1 work packages

### P1.0 — `application_id`

**Dependencies:** Phase 0  

**Goal:** implement this scoped Phase 1 commitment without pulling later-phase behavior forward.

**Work:**

- Add/verify `application_id`.
- Reconcile the existing implementation relevant to **Add/verify `application_id`.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Treat standalone chat as a canonical application identity, not a bypass.
- Never accept application/workspace identity as authority for ownership; authenticated principal remains authoritative.
- Workspace is optional and must have explicit null/no-workspace semantics.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- application registry policy
- cross-app permissions
- domain database access
- new domain features

### P1.1 — Optional `workspace_id`

**Dependencies:** P1.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 1 commitment without pulling later-phase behavior forward.

**Work:**

- Add optional `workspace_id`.
- Reconcile the existing implementation relevant to **Add optional `workspace_id`.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Treat standalone chat as a canonical application identity, not a bypass.
- Never accept application/workspace identity as authority for ownership; authenticated principal remains authoritative.
- Workspace is optional and must have explicit null/no-workspace semantics.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- application registry policy
- cross-app permissions
- domain database access
- new domain features

### P1.2 — Thread identity through API, conversation, memory scope, tracing, and tools

**Dependencies:** P1.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 1 commitment without pulling later-phase behavior forward.

**Work:**

- Thread identity through API, conversation, memory scope, tracing, and tools.
- Reconcile the existing implementation relevant to **Thread identity through API, conversation, memory scope, tracing, and tools.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Treat standalone chat as a canonical application identity, not a bypass.
- Never accept application/workspace identity as authority for ownership; authenticated principal remains authoritative.
- Workspace is optional and must have explicit null/no-workspace semantics.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- application registry policy
- cross-app permissions
- domain database access
- new domain features

### P1.3 — Canonical app IDs

**Dependencies:** P1.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 1 commitment without pulling later-phase behavior forward.

**Work:**

- Define canonical app IDs.
- Reconcile the existing implementation relevant to **Define canonical app IDs.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Treat standalone chat as a canonical application identity, not a bypass.
- Never accept application/workspace identity as authority for ownership; authenticated principal remains authoritative.
- Workspace is optional and must have explicit null/no-workspace semantics.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- application registry policy
- cross-app permissions
- domain database access
- new domain features

### P1.4 — Preserve standalone use

**Dependencies:** P1.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 1 commitment without pulling later-phase behavior forward.

**Work:**

- Preserve standalone use.
- Reconcile the existing implementation relevant to **Preserve standalone use.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Treat standalone chat as a canonical application identity, not a bypass.
- Never accept application/workspace identity as authority for ownership; authenticated principal remains authoritative.
- Workspace is optional and must have explicit null/no-workspace semantics.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- application registry policy
- cross-app permissions
- domain database access
- new domain features

### P1.5 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P1.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 1 commitment without pulling later-phase behavior forward.

**Work:**

- Wire the completed work packages through the narrow existing integration seam for this phase; do not add new product behavior.
- Run the phase verification matrix and all affected existing regressions from a clean checkout.
- Update the implementation guide/release evidence with actual code paths, tested revision, commands, outcomes, and explicit external verification gaps.
- Confirm every later-phase gate remains disabled/absent unless the integrated roadmap explicitly requires it now.
- Reconcile the existing implementation relevant to **Integrate the completed Phase work, run the required regression/evaluation matrix, update implementation documentation/evidence, and leave later-phase capabilities disabled or absent.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Create/reuse named synthetic fixtures with explicit expected selections, exclusions, errors, and invariants.
- Run deterministic offline comparisons first; make live/cloud checks explicit opt-in steps.
- Define promotion/completion gates before interpreting results and record failures without hiding them.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Treat standalone chat as a canonical application identity, not a bypass.
- Never accept application/workspace identity as authority for ownership; authenticated principal remains authoritative.
- Workspace is optional and must have explicit null/no-workspace semantics.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- App namespaces cannot leak.
- Existing chat works.
- Traces identify app/workspace.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- application registry policy
- cross-app permissions
- domain database access
- new domain features

---

## Phase verification and closeout

### Required local/offline checks

- `make backend-test`
- `make backend-lint`
- `make frontend-test`
- `make frontend-lint`
- `make frontend-typecheck`
- `git diff --check`

### Optional external checks

- Run only the provider/emulator/cloud/browser/native checks that are relevant to the phase and available in the environment.
- Use synthetic data. Never use the absence of credentials/network/cloud access as a reason to weaken offline tests.
- Record a skipped external check as **unverified**, not passed.

### Documentation/evidence closeout

- Update this plan only if implementation discovered a necessary scope-preserving clarification; do not silently rewrite the roadmap after coding.
- Create/update the phase implementation guide with actual files/classes/routes/configuration and a concise code map.
- Record release/verification evidence with date, tested revision, commands, outcomes, and explicit remaining external gaps.
- Update ADRs/API/deployment/runbook docs only where their contracts actually changed.

## Phase 1 completion review

- 1. Did implementation satisfy every normative Phase 1 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?

## Handoff to the next phase

Do not begin the next phase until the Phase 1 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
