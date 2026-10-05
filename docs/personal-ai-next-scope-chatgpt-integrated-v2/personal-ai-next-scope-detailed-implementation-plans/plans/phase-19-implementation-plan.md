# Phase 19 implementation plan — Shopping integration

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Validate project state, external evidence, constraints, and routing.

### Normative commitments from the integrated roadmap

- Implement Shopping providers.
- Feed structured requirements to product research.
- Preserve hard/soft constraints.
- Use saved/rejected products.
- Evaluate routing for extraction/rewrite/synthesis.
- Add sidecar to project/search/comparison/product views with explicitly selected products and active requirements.
- Show selected context before ChatGPT send.
- Support Copy and non-authoritative draft insertion.
- Keep shortlist/requirement mutations behind Phase 23.

### Phase acceptance criteria

- Recommendations reflect project state.
- Deterministic constraints remain authoritative.
- Personal AI does not own Shopping state.

### Explicitly out of scope

- checkout/purchase execution
- shortlist mutations before Phase 23
- Shopping state duplication in core
- cross-app budget federation

## Current state and reuse

Exact-barcode Open Food Facts catalog comparisons are implemented. Shopping project/requirements/shortlist authoritative app context and shared sidecar are missing.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/domains/shopping/models.py`
- `backend/src/personal_ai/domains/shopping/module.py`
- `backend/src/personal_ai/domains/providers.py`
- `backend/src/personal_ai/domains/service.py`
- `backend/src/personal_ai/ranking/policy.py`
- `backend/src/personal_ai/entities/research.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 7, 13, 16. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

**Conditional prerequisite:** additive sidecar integration consumes Phase 17.4. Baseline domain/backend work does not depend on live ChatGPT approval. Keep blocked sidecar work explicitly pending; do not declare the entire phase complete while any intended package is pending.

## Phase-specific invariants

- Rejected/saved state is authoritative Shopping state supplied through providers.
- External prices/availability/reviews remain evidence with freshness.
- Generic sidecar output cannot mutate shortlist/requirements in this phase.

## Work packages

### P19.0 — Shopping-owned project providers

**Depends on:** required phases above.

Pin authoritative Shopping app read contracts and membership; add typed bounded requirements, constraints, active project, selected/saved/rejected products and history providers. Core does not own project/shortlist DB state. Reuse exact-identity/claim/constraint services; OFF supplies catalog identity only, not current offers/reviews/availability. Budget/private preferences can raise sensitivity.

**Acceptance:** Bounded project/selected-product providers preserve domain ownership and exact catalog identity.

### P19.1 — Research and task baseline

**Depends on:** P19.0.

Feed structured hard/soft requirements into bounded product research; preserve unknown/conflicting/stale required attributes as failures. Route actual extraction/rewrite/synthesis tasks through the shared runtime and ledger; keep deterministic filtering authoritative. Record evidence freshness, source rights and task-quality baselines; no new unbounded merchant crawl or checkout.

**Acceptance:** Hard constraints/rejections/current offer evidence remain authoritative through routed task fixtures.

### P19.2 — Additive sidecar hooks

**Depends on:** P19.1 and Phase 17.4 for sidecar work.

After 17.4, attach shared sidecar to project/search/comparison/product views with explicitly selected products and active requirements shown before send. Enable Copy and permitted non-authoritative drafts; shortlist/requirement authoritative writes wait for 23. If ChatGPT live gates remain blocked, retain this package pending and complete baseline providers independently.

**Acceptance:** Shared Shopping sidecar previews selected context and cannot mutate shortlist/requirements before 23.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R19.1: Implement Shopping providers. | P19.0 |
| R19.2: Feed structured requirements to product research. | P19.1 |
| R19.3: Preserve hard/soft constraints. | P19.1 |
| R19.4: Use saved/rejected products. | P19.0 |
| R19.5: Evaluate routing for extraction/rewrite/synthesis. | P19.1 |
| R19.6: Add sidecar to project/search/comparison/product views with explicitly selected products and active requirements. | P19.2 |
| R19.7: Show selected context before ChatGPT send. | P19.2 |
| R19.8: Support Copy and non-authoritative draft insertion. | P19.2 |
| R19.9: Keep shortlist/requirement mutations behind Phase 23. | P19.2 |

## Targeted verification and closeout

Test saved/rejected product selection, exact identity, hard constraints, private budget exclusion, stale price/availability, provider failures, selected-context visibility and no shortlist/requirement writes.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make research-eval`, `make decision-eval`, `make domain-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Pin actual Shopping app API/revision and provider/source rights before live integration; real offer availability is not established by OFF or fakes.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
