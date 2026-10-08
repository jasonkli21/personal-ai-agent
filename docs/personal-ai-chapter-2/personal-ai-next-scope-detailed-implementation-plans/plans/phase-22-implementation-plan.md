# Phase 22 implementation plan — Cross-provider task evaluation matrix

Renumbered from former Phase 14 with scope preserved. Raw retained outputs use GCS and compact/versioned evaluation summaries use Postgres under the Phase 10/20 ownership model.

## Scope boundary
**Goal:** Measure actual task quality.

### Normative commitments
- Reuse/extend existing fixtures.
- Compare enabled strict-free Gemini, Groq, and Cloudflare models.
- Store raw outputs in GCS and summaries in Postgres.
- Version quality profiles.
- Define task quality floors.

### Phase acceptance criteria
- Router quality assumptions have project-specific evidence.
- Evaluations are bounded/reproducible.
- Strict-free eval mode cannot call paid endpoints.

### Explicitly out of scope
- automatic model promotion without thresholds
- paid-provider experiments in strict-free mode
- model judge as sole scorer
- learned router

## Current state and reuse
Deterministic domain/task fixtures and evaluation runners are reusable. Cross-provider quality matrix and versioned measured profiles are missing.

## Phase 10 storage dependency

Queryable evaluation profiles/summaries belong in Postgres; retained raw bodies belong in Phase 20 GCS. This assignment neither implements extra evaluation features nor permits prompts/secrets in compact runtime events. See the [Phase 10 storage contract](../../phase-10-storage-ownership-and-access-patterns.md); existing work packages and acceptance remain unchanged.

## Prerequisites and work ordering
Required phases: 20 and 21, plus Phase 10 persistence foundation.

## Phase-specific invariants
- Separate deterministic offline fixtures from opt-in live-provider evaluations.
- Never claim a provider was evaluated if the live check was skipped.
- Evaluation preserves sensitive-data policy; synthetic fixtures are default.

## Work packages
### P22.0 — Baseline matrix and scoring
Extend fixture/run formats to record task/profile identity and version against endpoint-profile identity/version, model, provider, account/config scope where material, serializer/runtime/config, counter, policy, tested revision, and seed/counter where supported. Define held-out fixtures and deterministic schema/citation/provenance/hard-constraint/privacy scoring, with answer support/relevance, token/quota and latency metrics. Model judges may supplement, never be sole scorer. Capture current single-provider and Phase 21 deterministic-strategy baselines before comparison.

**Acceptance:** Held-out task fixtures and thresholds produce reproducible deterministic baseline metrics.

### P22.1 — Bounded provider runs and artifacts
Run identical synthetic task inputs through enabled eligible Gemini/Groq/Cloudflare profiles with Phase 19 admission and bounded attempts/concurrency. Offline fakes validate harness mechanics; live output is separate evidence. Store retained raw outputs in Phase 20 GCS and compact searchable summaries in Postgres; no private fixtures or unlicensed retained provider evidence.

These three remain the initial live comparison. The harness iterates registered eligible endpoint profiles and task fixtures/profiles, without three provider-specific paths. Add a synthetic additional provider/endpoint and task to prove fixture/profile-based extension without harness redesign; this neither adds a fourth live integration nor establishes measured live quality. Strict-free admission excludes paid/unknown-cost and explicit-only lanes before evaluation dispatch.

**Acceptance:** Bounded eligible runs store permitted raw artifacts separately from compact summaries; skipped live models have no quality score.

### P22.2 — Versioned quality profiles and promotion
Define task quality floors, confidence/sample coverage and profile invalidation when model/config changes. Unrun/skipped endpoints have no measured quality. Require reproducible benefit and no hard-boundary regression; export/publish only permitted artifacts. Domain phases later extend fixtures with their implemented read contracts before optimization consumes those results.

Bind each quality result to provider, endpoint-profile ID/version, logical model, account/configuration scope where material, serializer/runtime version, task-profile ID/version, policy version, tested revision, and counter/seed where applicable. Freeze safe profile/account/execution metadata needed to reproduce eligibility without secrets. When quality evidence affects a route, the [routing observation](../../03-free-tier-inference-and-routing.md#routing-observation-contract) records the exact evidence/profile version used; later results correlate to the invocation/decision they evaluate where applicable. Relevant changes invalidate evidence rather than inheriting another credential/account/profile's eligibility or an obsolete configuration's score.

**Acceptance:** Versioned profiles include coverage/config evidence and cannot promote stale or unrun models.

**Extension acceptance:** Synthetic profiles use the same run/scoring/artifact paths; changed endpoint/task/policy/configuration identities cannot silently reuse old quality evidence. Skipped live checks remain unmeasured.

## Requirement coverage
Former R14.1–R14.5 are preserved as R22.1–R22.5 and map to P22.0–P22.2 without scope reduction.
## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only when this phase changes the truth of user-visible capabilities, architecture, tech stack, setup, deployment, provider support, or project status. Keep implementation details in `docs/`; if no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the phase-specific deterministic tests plus applicable backend/frontend test, lint, typecheck and build checks. Finish with `git diff --check`. External/provider/cloud checks are opt-in and skipped checks remain **unverified**, never passed. Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation evidence.
