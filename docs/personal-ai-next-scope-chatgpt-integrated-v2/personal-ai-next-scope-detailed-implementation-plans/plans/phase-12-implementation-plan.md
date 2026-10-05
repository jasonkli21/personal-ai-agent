# Phase 12 implementation plan — Cloud Storage artifact tier and retention

This is the detailed execution plan for integrated next-scope **Phase 12 — Cloud Storage artifact tier and retention**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Keep bulky immutable observability/evaluation/export artifacts out of Firestore.

### Normative commitments from the integrated roadmap

- Define `ArtifactStore` and `ArtifactRef`.
- Add fake/in-memory and private GCS implementations.
- Add compressed JSON/JSONL support.
- Persist compact artifact metadata/reference in Firestore.
- Use the tier for detailed routing/context traces, raw evaluation output, exports, and debug/replay artifacts.
- Add retention/deletion behavior and Firestore/GCS storage observability.
- Keep memory vectors and operational records in Firestore.
- Add conservative artifact-write guardrails for free GCS ceilings.

### Phase acceptance criteria

- Raw evals/traces can avoid Firestore storage.
- Firestore still holds queryable summaries/references.
- No public artifact access.
- Optional artifact failure does not fail successful inference.
- Export artifact failure is explicit.
- No DynamoDB dependency.

### Explicitly out of scope

- DynamoDB
- online vector search in GCS
- public buckets
- indefinite raw trace retention

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/storage/`
- `backend/src/personal_ai/evaluation/`
- `infrastructure/`
- `docs/`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

There is no Cloud Storage artifact adapter or bucket in the current runtime/deployment. Firestore repositories are distributed by domain behind protocols; `firestore.indexes.json` includes operational and memory-vector indexes. Add a narrow artifact repository/reference/retention seam and deploy resources without moving canonical/queryable/vector state from Firestore. Existing Phase 9 export/deletion/backups remain incomplete; carry artifact deletion/export obligations forward. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make context-eval`, `make memory-eval`, `make research-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- GCS is not a shadow database.
- Never move memory vectors, active conversations, quota state, or authoritative domain data to GCS.
- Sensitive Finance/Health verbose traces default to minimal retention or no artifact.
- Track operation counts as well as bytes; avoid one-object-per-tiny-event patterns.

## Dependency map

**Prerequisites:** Phase 11

```text
P12.0 ArtifactRef/ArtifactStore -> P12.1 In-memory/fake
P12.1 In-memory/fake -> P12.2 Private
P12.2 Private -> P12.3 Firestore
P12.3 Firestore -> P12.4 Compression/retention/deletion/orphan
P12.4 Compression/retention/deletion/orphan -> P12.5 Usage
P12.5 Usage -> P12.6 Trace/evaluation/export
```

The map is sequencing guidance, not a requirement to commit once per work package. Prefer a few coherent commits that preserve reviewable boundaries.

## Required verification matrix

- Offline unit/contract tests cover success plus malformed/denied/unavailable/error paths for each new contract.
- Integration tests prove the phase composes with the existing owner/application/workspace and context boundaries.
- Regression tests prove the phase-disabled/default path preserves prior behavior.
- No automated test requires live provider credentials, a real GCP project, or personal data unless explicitly marked opt-in.
- Safe tracing/evidence records IDs, counts, versions, states, and reason codes without raw secrets or unnecessary private content.
- Documentation/release evidence states exactly which external provider/emulator/cloud checks were run, skipped, or remain open.
- Storage failure/orphan/retention/authorization behavior is exercised without relying on public buckets or production data.

## Required implementation artifacts

- Code/configuration changes required by the work packages below, limited to Phase 12 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 12 work packages

### P12.0 — `ArtifactStore` and `ArtifactRef`

**Dependencies:** Phase 11  

**Goal:** implement this scoped Phase 12 commitment without pulling later-phase behavior forward.

**Work:**

- Define `ArtifactStore` and `ArtifactRef`.
- Reconcile the existing implementation relevant to **Define `ArtifactStore` and `ArtifactRef`.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep persistence behind repository/store protocols and provide an in-memory fake for automated tests.
- Define idempotency/concurrency/failure semantics for partial writes or retries.
- Document required indexes/object layout/retention behavior without exposing storage details to higher layers.

**Requirements:**

- GCS is not a shadow database.
- Never move memory vectors, active conversations, quota state, or authoritative domain data to GCS.
- Sensitive Finance/Health verbose traces default to minimal retention or no artifact.
- Storage failures must have explicit user-visible versus best-effort semantics.
- No collection/bucket scan may become a normal request-path dependency unless explicitly designed.

**Acceptance criteria:**

- Persistence tests cover create/read/update or append semantics, isolation, missing records, and injected failure.

**Out of scope:**

- DynamoDB
- online vector search in GCS
- public buckets
- indefinite raw trace retention

### P12.1 — Fake/in-memory and private GCS implementations

**Dependencies:** P12.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 12 commitment without pulling later-phase behavior forward.

**Work:**

- Add fake/in-memory and private GCS implementations.
- Reconcile the existing implementation relevant to **Add fake/in-memory and private GCS implementations.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep persistence behind repository/store protocols and provide an in-memory fake for automated tests.
- Define idempotency/concurrency/failure semantics for partial writes or retries.
- Document required indexes/object layout/retention behavior without exposing storage details to higher layers.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- GCS is not a shadow database.
- Never move memory vectors, active conversations, quota state, or authoritative domain data to GCS.
- Sensitive Finance/Health verbose traces default to minimal retention or no artifact.
- Storage failures must have explicit user-visible versus best-effort semantics.
- No collection/bucket scan may become a normal request-path dependency unless explicitly designed.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Persistence tests cover create/read/update or append semantics, isolation, missing records, and injected failure.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- DynamoDB
- online vector search in GCS
- public buckets
- indefinite raw trace retention

### P12.2 — Compressed JSON/JSONL support

**Dependencies:** P12.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 12 commitment without pulling later-phase behavior forward.

**Work:**

- Add compressed JSON/JSONL support.
- Reconcile the existing implementation relevant to **Add compressed JSON/JSONL support.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- GCS is not a shadow database.
- Never move memory vectors, active conversations, quota state, or authoritative domain data to GCS.
- Sensitive Finance/Health verbose traces default to minimal retention or no artifact.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- DynamoDB
- online vector search in GCS
- public buckets
- indefinite raw trace retention

### P12.3 — Persist compact artifact metadata/reference in Firestore

**Dependencies:** P12.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 12 commitment without pulling later-phase behavior forward.

**Work:**

- Persist compact artifact metadata/reference in Firestore.
- Reconcile the existing implementation relevant to **Persist compact artifact metadata/reference in Firestore.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep persistence behind repository/store protocols and provide an in-memory fake for automated tests.
- Define idempotency/concurrency/failure semantics for partial writes or retries.
- Document required indexes/object layout/retention behavior without exposing storage details to higher layers.

**Requirements:**

- GCS is not a shadow database.
- Never move memory vectors, active conversations, quota state, or authoritative domain data to GCS.
- Sensitive Finance/Health verbose traces default to minimal retention or no artifact.
- Storage failures must have explicit user-visible versus best-effort semantics.
- No collection/bucket scan may become a normal request-path dependency unless explicitly designed.

**Acceptance criteria:**

- Persistence tests cover create/read/update or append semantics, isolation, missing records, and injected failure.

**Out of scope:**

- DynamoDB
- online vector search in GCS
- public buckets
- indefinite raw trace retention

### P12.4 — Use the tier for detailed routing/context traces, raw evaluation output, exports,…

**Dependencies:** P12.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 12 commitment without pulling later-phase behavior forward.

**Work:**

- Use the tier for detailed routing/context traces, raw evaluation output, exports, and debug/replay artifacts.
- Reconcile the existing implementation relevant to **Use the tier for detailed routing/context traces, raw evaluation output, exports, and debug/replay artifacts.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep persistence behind repository/store protocols and provide an in-memory fake for automated tests.
- Define idempotency/concurrency/failure semantics for partial writes or retries.
- Document required indexes/object layout/retention behavior without exposing storage details to higher layers.
- Record safe IDs, policy/profile versions, counts, decisions, and reason codes needed to reconstruct behavior.
- Apply allowlist/redaction before persistence or display; raw private content remains absent by default.
- Add read-only inspection/tests proving no write/provider side effects.
- Create/reuse named synthetic fixtures with explicit expected selections, exclusions, errors, and invariants.
- Run deterministic offline comparisons first; make live/cloud checks explicit opt-in steps.
- Define promotion/completion gates before interpreting results and record failures without hiding them.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.
- Make route/candidate decisions deterministic and inspectable from explicit inputs for this phase.
- Preserve hard strict-free/privacy/capability/context-limit constraints before optimization logic.
- Record selected/rejected candidates and reason codes in safe trace metadata.

**Requirements:**

- GCS is not a shadow database.
- Never move memory vectors, active conversations, quota state, or authoritative domain data to GCS.
- Sensitive Finance/Health verbose traces default to minimal retention or no artifact.
- Storage failures must have explicit user-visible versus best-effort semantics.
- No collection/bucket scan may become a normal request-path dependency unless explicitly designed.
- Observability is not a second source of truth and must respect the underlying data sensitivity.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.
- Optimization logic cannot widen a hard eligibility boundary.

**Acceptance criteria:**

- Persistence tests cover create/read/update or append semantics, isolation, missing records, and injected failure.
- A developer can reconstruct the decision path from safe metadata for named fixtures.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.
- Named fixtures reproduce route decisions and rejection reasons.

**Out of scope:**

- DynamoDB
- online vector search in GCS
- public buckets
- indefinite raw trace retention

### P12.5 — Retention/deletion behavior and Firestore/GCS storage observability

**Dependencies:** P12.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 12 commitment without pulling later-phase behavior forward.

**Work:**

- Add retention/deletion behavior and Firestore/GCS storage observability.
- Reconcile the existing implementation relevant to **Add retention/deletion behavior and Firestore/GCS storage observability.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep persistence behind repository/store protocols and provide an in-memory fake for automated tests.
- Define idempotency/concurrency/failure semantics for partial writes or retries.
- Document required indexes/object layout/retention behavior without exposing storage details to higher layers.
- Record safe IDs, policy/profile versions, counts, decisions, and reason codes needed to reconstruct behavior.
- Apply allowlist/redaction before persistence or display; raw private content remains absent by default.
- Add read-only inspection/tests proving no write/provider side effects.

**Requirements:**

- GCS is not a shadow database.
- Never move memory vectors, active conversations, quota state, or authoritative domain data to GCS.
- Sensitive Finance/Health verbose traces default to minimal retention or no artifact.
- Storage failures must have explicit user-visible versus best-effort semantics.
- No collection/bucket scan may become a normal request-path dependency unless explicitly designed.
- Observability is not a second source of truth and must respect the underlying data sensitivity.

**Acceptance criteria:**

- Persistence tests cover create/read/update or append semantics, isolation, missing records, and injected failure.
- A developer can reconstruct the decision path from safe metadata for named fixtures.

**Out of scope:**

- DynamoDB
- online vector search in GCS
- public buckets
- indefinite raw trace retention

### P12.6 — Keep memory vectors and operational records in Firestore

**Dependencies:** P12.5 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 12 commitment without pulling later-phase behavior forward.

**Work:**

- Keep memory vectors and operational records in Firestore.
- Reconcile the existing implementation relevant to **Keep memory vectors and operational records in Firestore.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep persistence behind repository/store protocols and provide an in-memory fake for automated tests.
- Define idempotency/concurrency/failure semantics for partial writes or retries.
- Document required indexes/object layout/retention behavior without exposing storage details to higher layers.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- GCS is not a shadow database.
- Never move memory vectors, active conversations, quota state, or authoritative domain data to GCS.
- Sensitive Finance/Health verbose traces default to minimal retention or no artifact.
- Storage failures must have explicit user-visible versus best-effort semantics.
- No collection/bucket scan may become a normal request-path dependency unless explicitly designed.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Persistence tests cover create/read/update or append semantics, isolation, missing records, and injected failure.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- DynamoDB
- online vector search in GCS
- public buckets
- indefinite raw trace retention

### P12.7 — Conservative artifact-write guardrails for free GCS ceilings

**Dependencies:** P12.6 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 12 commitment without pulling later-phase behavior forward.

**Work:**

- Add conservative artifact-write guardrails for free GCS ceilings.
- Reconcile the existing implementation relevant to **Add conservative artifact-write guardrails for free GCS ceilings.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.
- Keep persistence behind repository/store protocols and provide an in-memory fake for automated tests.
- Define idempotency/concurrency/failure semantics for partial writes or retries.
- Document required indexes/object layout/retention behavior without exposing storage details to higher layers.

**Requirements:**

- GCS is not a shadow database.
- Never move memory vectors, active conversations, quota state, or authoritative domain data to GCS.
- Sensitive Finance/Health verbose traces default to minimal retention or no artifact.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.
- Storage failures must have explicit user-visible versus best-effort semantics.
- No collection/bucket scan may become a normal request-path dependency unless explicitly designed.

**Acceptance criteria:**

- Negative tests prove protected data/provider paths are never invoked after denial.
- Persistence tests cover create/read/update or append semantics, isolation, missing records, and injected failure.

**Out of scope:**

- DynamoDB
- online vector search in GCS
- public buckets
- indefinite raw trace retention

### P12.8 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P12.7 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 12 commitment without pulling later-phase behavior forward.

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

- GCS is not a shadow database.
- Never move memory vectors, active conversations, quota state, or authoritative domain data to GCS.
- Sensitive Finance/Health verbose traces default to minimal retention or no artifact.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Raw evals/traces can avoid Firestore storage.
- Firestore still holds queryable summaries/references.
- No public artifact access.
- Optional artifact failure does not fail successful inference.
- Export artifact failure is explicit.
- No DynamoDB dependency.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- DynamoDB
- online vector search in GCS
- public buckets
- indefinite raw trace retention

---

## Phase verification and closeout

### Required local/offline checks

- `make backend-test`
- `make backend-lint`
- storage/artifact fake integration suite
- `bash -n infrastructure/gcp/deploy.sh` when deployment scripts change
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

## Phase 12 completion review

- 1. Did implementation satisfy every normative Phase 12 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Can optional artifact persistence failure break successful user inference, or can required exports fail silently? Both required answers are no.

## Handoff to the next phase

Do not begin the next phase until the Phase 12 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
