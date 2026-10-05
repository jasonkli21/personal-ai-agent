# Phase 0 implementation plan — Reconcile with current repository and roadmap

This is the documentation-only execution plan for integrated next-scope Phase 0. The [integrated roadmap](../source/05-phased-implementation-plan.md) defines its scope. The [dated reconciliation record](../phase-0-reconciliation-2026-10-05.md) records the review against the repository at `24f75a7`.

## Scope and precedence

Review current code, tests, accepted ADRs, release evidence, infrastructure, and the integrated source documents before changing behavior. Current code and verified evidence determine implementation status and reusable seams; the integrated source documents define product scope; detailed plans elaborate that scope. Do not treat speculative file names or generic work-package text as authority to create parallel abstractions.

The next-scope Phase 0–28 numbering is independent of the repository's existing Phases 1–9. Existing Phases 1–8 are locally implemented; existing Phase 9 is partial. Next-scope Phase 1 is the first planned implementation phase. No Phase 1 or later behavior is implemented in this review.

### Normative commitments

- Review existing plans, guides, ADRs, release and verification records, and tests.
- Map API identity/auth, context, memory and embeddings, research/search/evidence, domains, LLM/structured generation, Firestore/vector indexes, evaluation/tracing, frontend, and deployment.
- Confirm Gemini generation/embedding and Firestore index dependencies.
- Classify roadmap work as implemented, partial, reusable, needing extension/refactor, missing, or intentionally deferred.
- Reconcile dependencies, phase boundaries, verification commands, and external gaps without reducing integrated scope.

### Explicit exclusions

- Substantive code refactors, new provider integrations, schema migrations, and domain-application integration.
- New fixtures, contracts, fakes, integration tests, or live provider/cloud checks solely for this documentation audit.
- Production approval or closure of existing Phase 9 release gates.

## Repository review areas

Use the actual paths, not proposed module names:

- `backend/src/personal_ai/api/`, `auth/`, `services/`, `entities/`, and `storage/` for request identity, chat, and owner-scoped persistence.
- `context/`, `memory/`, `llm/`, `search/`, `evidence/`, `agents/research/`, `decisions/`, `ranking/`, `domains/`, `booking_extractions/`, and `itinerary_proposals/` for intelligence paths.
- `evaluation/`, `backend/tests/`, `frontend/tests/`, and `.github/workflows/quality.yml` for reproducible evidence.
- `frontend/src/app/`, `frontend/src/features/`, `frontend/src/lib/`, `frontend/src/middleware.ts`, `infrastructure/gcp/deploy.sh`, and `firestore.indexes.json` for client and deployment boundaries.

## Work packages

### P0.0 — Establish baseline

Read `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, `docs/phase-1-implementation-guide.md`, the relevant existing phase guides/plans, Phase 9 plan/evidence, accepted ADRs, release records, and the integrated next-scope source documents. Inspect `git status` first and preserve unrelated user changes. Record the reviewed revision and distinguish current code from historical evidence.

### P0.1 — Map actual subsystem seams

Trace the request from Next.js proxy through authenticated FastAPI owner resolution, active-branch context assembly, provider call, and persistence. Trace memory extraction/embedding/vector retrieval, bounded research/evidence/decision/domain paths, evaluation, and deployment. Document exact reusable contracts and limitations; do not create implementation artifacts.

### P0.2 — Reconcile roadmap and detailed plans

Check each phase against actual modules, already-completed prerequisites, missing work, and dependencies. Preserve all domain-context, strict-free Gemini/Groq/Cloudflare, storage, routing, evaluation, and ChatGPT requirements. Keep 17.1–17.4 additive and retain domain-application authority. Correct misleading work-package details and commands where necessary.

### P0.3 — Record evidence and gaps

Publish a dated reconciliation with a reuse/refactor/missing/defer map, phase sequence, verified local state, external verification gaps, and first implementation-phase readiness. Do not promote fake tests to provider/emulator/cloud evidence or close Phase 9 operational gates by assertion.

### P0.4 — Verify documentation

Review relative links, copied integrated source consistency, detailed-plan coverage, manifest sizes, Phase 17 dependencies, domain authority, and strict-free/security invariants. Run `git diff --check`. This documentation-only phase does not require backend/frontend test or build commands; later implementation phases retain their phase-specific tests and evaluation gates.

## Acceptance

- The next-scope numbering and existing repository phase numbering are clearly distinguished.
- Every integrated requirement remains assigned to a phase, with no ChatGPT substitution for strict-free work.
- Actual code seams, existing capability, partial Phase 9 status, and verification gaps are recorded accurately.
- No new product behavior, provider call, datastore migration, or deployment is introduced.
- Link/content review and `git diff --check` pass; any skipped external checks remain explicitly unverified.

Phase 1 may begin only after this review is complete. Its offline implementation can proceed while existing Phase 9 production gates remain open; live personal-data use and deployment require those gates to be satisfied independently.
