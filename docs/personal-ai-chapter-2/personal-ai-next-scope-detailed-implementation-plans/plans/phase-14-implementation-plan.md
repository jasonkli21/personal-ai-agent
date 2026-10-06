# Phase 14 implementation plan — Provenance and context inspection

Renumbered on 2026-10-06 from former next-scope Phase 6. This plan preserves the former detailed plan’s normative commitments, work packages, invariants, acceptance criteria, and verification scope. Only phase numbering/prerequisites, persistence references superseded by Phase 10, and README-maintenance requirements are changed. Read the source roadmap, Phase 10 persistence plan, and shared execution contract first. This plan defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Make effective model context auditable.

### Normative commitments from the integrated roadmap

- Trace planning/provider/policy/exclusion/token decisions.
- Correlate request IDs.
- Add development inspection.
- Redact sensitive values.

### Phase acceptance criteria

- A developer can explain source selection, exclusion, authority, and token use.

### Explicitly out of scope

- production raw-prompt logging
- public inspection endpoints
- routing optimization
- new domain data

## Current state and reuse

Owner-scoped gated estimated inspection and safe correlation exist. Actual-build traces and end-to-end proxy correlation need extension.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/context/inspection.py`
- `backend/src/personal_ai/context/contracts.py`
- `backend/src/personal_ai/memory/inspection.py`
- `backend/src/personal_ai/auth/middleware.py`
- `backend/src/personal_ai/api/schemas.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends the post-Phase-10 GCP/Neon/DynamoDB deployment assets, `Makefile`, and `.github/workflows/quality.yml` only when required; do not reintroduce Firestore as a canonical runtime dependency. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 5, 10. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Inspector must be read-only and development-gated.
- Never require a live provider call merely to inspect already-built context.
- Foreign-owner/workspace references must preserve safe not-found semantics.

## Work packages

### P14.0 — Safe trace schema

**Depends on:** required phases above.

Add versioned actual-build metadata: scope/request/turn IDs, plan/policy versions, requested/selected/excluded source IDs/categories, authority/sensitivity, counts and counter kind, reasons and optional artifact reference. Do not persist raw prompts, source secrets or hidden reasoning. Record manifests during preparation instead of inferring past dispatch from current state.

**Acceptance:** Captured safe manifests contain versions/counts/reasons without private source text or credentials.

### P14.1 — Inspector and frontend integration

**Depends on:** P14.0.

Extend gated read-only context inspection and the Next.js proxy/UI with safe manifests and explicit estimated-reconstruction labels. Forward validated X-Request-ID and expose correlation consistently. Cross-owner/app/workspace queries preserve not-found semantics. Inspection must have no provider calls, writes or retention side effects.

**Acceptance:** Correlation survives proxy/API and inspection has zero model/write side effects.

### P14.2 — Bounded retention and evaluation evidence

**Depends on:** P14.1.

Keep compact traces bounded in existing operational records; bulky traces wait for Phase 20. Include trace schema/policy versions and missing-manifest behavior. Extend context fixtures so a reviewer can explain each selection, exclusion and budget outcome without sensitive content.

**Acceptance:** Old or absent manifests degrade explicitly, and bounded retained metadata supports fixture explanations.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R14.1: Trace planning/provider/policy/exclusion/token decisions. | P14.0 |
| R14.2: Correlate request IDs. | P14.1 |
| R14.3: Add development inspection. | P14.1 |
| R14.4: Redact sensitive values. | P14.0 |

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only when implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Test correlation through proxy, metadata redaction, no-side-effect inspection, actual versus estimated labels, foreign IDs, unavailable historical manifests and bounded output.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make memory-eval`, `make memory-lifecycle-eval`, `make research-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Only relevant provider/emulator/cloud/domain/browser checks run opt-in with explicit environment and synthetic data. Local fakes do not establish deployed compatibility.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
