# Phase 21 implementation plan — Deterministic task-aware routing

Renumbered from former Phase 13 with scope preserved.

## Scope boundary
**Goal:** Select eligible free models using transparent task rules.

### Normative commitments
- Define a small task taxonomy.
- Add routing requirements for capability, sensitivity, context size, quality floor, and escalation.
- Apply hard eligibility filtering.
- Add fixed task-specific priorities.
- Trace rejection/selection.
- Route chat plus at least two non-chat subtasks.

### Phase acceptance criteria
- No round-robin.
- Privacy/capability precede scoring.
- Known task type does not require an LLM classifier.

### Explicitly out of scope
- quota scarcity scoring
- learned routing
- cascades
- ChatGPT-plan explicit lane

## Current state and reuse
Current dependency injection selects one Gemini client. Task routing, rejection traces and actual per-turn producing-model metadata need extension.

## Phase 10 storage dependency

DynamoDB turn/runtime records hold actual producing-model attribution and compact actual-build manifests; Postgres owns versioned policy/registry and usage controls. Reference exact versions without duplicating canonical control records. See the [Phase 10 storage contract](../../phase-10-storage-ownership-and-access-patterns.md); existing work packages and acceptance remain unchanged.

## Prerequisites and work ordering
Required phases: 16, 18, 19, plus Phase 10 persistence foundation.

## Phase-specific invariants
- Known callers pass task type rather than paying for classification.
- Strict-free, privacy, capability, context limits, and known exhaustion/cooldown are hard constraints.
- Route decisions are reconstructable from registry/ledger inputs.

## Work packages
### P21.0 — Task taxonomy and requirements
Define a small taxonomy from actual operations: chat, summary, extraction, research synthesis/planning where used, rewrite, structured validation-related generation and embedding through its separate boundary. Callers supply known task type; no LLM classifier. Requirements include capability, privacy/sensitivity, prepared context capacity and quality-floor policy, with finite retry/escalation permission.

Separate task ID from typed requirements, adding citation behavior, quality-profile references, and deterministic validator IDs/versions where relevant. A new application task such as `travel.itinerary_proposal` declares requirements/policy through registration rather than a router branch. This remains a bounded typed configuration seam, not a runtime task-plugin system; Phase 24 implements validator execution.

**Acceptance:** Actual task callers supply typed requirements without an LLM classifier.

### P21.1 — Transparent deterministic router
Apply strict-free/privacy/capability/known exhaustion/cooldown hard filters before versioned fixed task priorities. Phase 22 measured quality does not exist yet: use explicitly unmeasured configured baseline priorities and never fabricate numeric quality. If a task requires a measured floor with no profile, deny. Fit/recount for selected endpoint and record all exclusions and versions; before-visible-output fallback obeys the same filters.

Consume registered endpoint facts and [execution/cost eligibility](../../03-free-tier-inference-and-routing.md#execution-identity-and-cost-modes), then task requirements and deterministic policy. Provider/model names may appear in profile configuration and trace identity, but cannot define generic control flow. BYOK/ChatGPT remain outside this automatic free-only router.

**Acceptance:** Hard filters precede deterministic priorities and unmeasured quality is never represented as measured.

**Extension acceptance:** A synthetic endpoint and task using existing requirements route by profile/policy configuration without generic router changes. Paid, unknown-cost, or explicit-only variants are rejected even when free candidates are exhausted; a genuinely new requirement needs a shared contract extension with conformance coverage.

### P21.2 — Integrate and persist attribution
Route chat and at least two actual non-chat tasks using the shared runtime, existing assembly and invocation ledger. Persist actual producing provider/model and safe selection/fallback trace on automatic turns rather than static `AI_MODEL`. Conversation persistence follows DynamoDB after Phase 10. Maintain branch/supersession and partial-failure semantics. No round-robin, scarcity scoring, cascades or ChatGPT automatic route.

**Acceptance:** Chat plus two non-chat tasks route through the runtime and store actual producing-model attribution.

## Requirement coverage
R21.1–R21.6 map respectively to P21.0/P21.1/P21.2 exactly as in former Phase 13.
## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only when this phase changes the truth of user-visible capabilities, architecture, tech stack, setup, deployment, provider support, or project status. Keep implementation details in `docs/`; if no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the phase-specific deterministic tests plus applicable backend/frontend test, lint, typecheck and build checks. Finish with `git diff --check`. External/provider/cloud checks are opt-in and skipped checks remain **unverified**, never passed. Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation evidence.
