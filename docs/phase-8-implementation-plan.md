# Phase 8 implementation plan

This plan adds bounded, iterative investigation to the Phase 5–7 research platform. It must preserve Phase 5’s evidence provenance and Phase 6’s deterministic decision rules; iteration improves evidence coverage, never loosens a constraint.

## Scope boundary

Phase 8 adds evidence-sufficiency assessment, gap/conflict detection, focused follow-up queries, configurable stop budgets, persisted iteration traces, progress streaming, and comparative evaluation. It excludes open-ended autonomy, background self-directed browsing, transactions, authentication, and learned optimization.

## Delivery conventions and cross-cutting requirements

- Model the loop as an explicit finite state machine with allowed transitions,
  lease owner, idempotency key, event sequence number, and terminal state. A
  state machine transition is durable before its external side effect is
  attempted; retrying it must be safe.
- Account for every budget dimension before dispatching work and reconcile it
  after each attempt. Include planned and actual query/source/token/cost/time
  usage; reserve enough budget for synthesis and do not launch work that cannot
  be represented safely in the remaining budget.
- Use structured assessor/planner outputs with schemas, allowed gap taxonomy,
  query/domain caps, and deterministic validation. They can recommend a next
  action, never call an adapter or change constraints directly.
- Preserve intermediate evidence and conflicts even when a later iteration
  finds a better source. The final result must say what remains incomplete,
  not treat maximum iterations as proof of sufficiency.
- Feature-gate iterative runs separately from the Phase 5 research mode and
  default to single pass. Runs initiated before a configuration change retain
  their recorded policy/budget version.
- SSE is a view of persisted state, not the source of truth. A reconnect reads
  session state/events; it must not start a new run or expose raw queries,
  source text, prompts, provider traces, or chain-of-thought.

## Required verification matrix

Use deterministic clocks and fake corpus/adapters to test state transitions,
all stop reasons, budget reservation/settlement, repeated/no-progress queries,
conflicts, stale evidence, entity ambiguity, provider errors, leases, retries,
restart, cancel/disconnect, reconnect, event ordering, and disabled parity.
Compare cost and evidence outcomes to the same single-pass fixture snapshots;
an iterative result is not promotable merely because it made more searches.

## Required implementation artifacts

P8.1 must create accepted state-machine/budget ADRs, versioned run and event
schemas, a transition validator, deterministic clock/queue/search fakes,
fixture-result schema, migration/index definitions, and the safe research SSE
extension before P8.2 writes a run. The orchestrator is the only component
that may advance state; planners and assessors return validated proposals,
while Phase 5 adapters and Phase 6 decisions retain their existing authority.

**Required persisted records:**

| Record | Required fields |
| --- | --- |
| Research run | `id`, `owner_id`, `session_id`, `state`, `policy_version`, `budget_version`, `idempotency_key`, `current_iteration`, `lease_expires_at` (nullable), `created_at`, `updated_at`, `terminal_reason` (nullable) |
| Iteration | `id`, `run_id`, `sequence`, `state`, `input_evidence_snapshot_id`, `assessment_id` (nullable), `query_ids`, `budget_before`, `budget_after`, `started_at`, `completed_at` (nullable) |
| Evidence gap | `id`, `run_id`, `iteration_id`, `gap_class`, `target_id` (nullable), `evidence_ids`, `required`, `status`, `reason_code` |
| Run event | `id`, `run_id`, `sequence`, `event_type`, `idempotency_key`, `safe_payload`, `occurred_at` |
| Budget ledger entry | `id`, `run_id`, `iteration_id` (nullable), `dimension`, `reserved`, `settled`, `status`, `created_at` |

**Required configuration:**

| Setting | Purpose |
| --- | --- |
| `ITERATIVE_RESEARCH_ENABLED` | Independent opt-in gate; single-pass remains default |
| `ITERATIVE_RESEARCH_POLICY_VERSION` | Immutable transition/gap policy |
| `ITERATIVE_MAX_ITERATIONS`, `ITERATIVE_MAX_QUERIES`, `ITERATIVE_MAX_SOURCES` | Work bounds |
| `ITERATIVE_MAX_ELAPSED_SECONDS`, `ITERATIVE_MAX_TOKENS`, `ITERATIVE_MAX_PROVIDER_COST` | Time/input/spend bounds |
| `ITERATIVE_ALLOWED_DOMAINS` | Narrow source-domain policy for follow-ups |
| `ITERATIVE_PROGRESS_ENABLED` | Safe persisted-progress/SSE presentation gate |

## Dependency map

```text
P8.0 Fixtures ─> P8.1 Contracts/policies ─> P8.2 Iteration state ─> P8.3 Sufficiency assessor ─> P8.4 Follow-up planner ─> P8.5 Orchestrator ─> P8.6 Progress UI ─> P8.7 Verify
P5 search/evidence + P6 constraints + P7 domains ────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 8 — Iterative research behavior

### P8.0 — Establish iterative fixtures and single-pass comparisons

**Dependencies:** Phase 7 completion review

**Goal:** show when another search is warranted and when it is wasteful.

**Work:** add deterministic cases for sufficient first-pass evidence, missing required fact, stale required fact, conflicting sources, ambiguous entity, no viable candidates, repeated query, budget exhaustion, adapter failure, and user cancellation. Record expected iteration count, gap classes, allowed follow-up queries, stop reason, selected evidence, and final decision state.

**Requirements:** fixtures pin the initial evidence snapshot, fake corpus,
clock, and every budget dimension; explicitly mark which improvement would be
meaningful versus an unnecessary extra query; keep all source text and planner
outputs synthetic.

**Acceptance criteria:** every fixture compares Phase 5 single-pass and Phase 8 results using a fixed fake corpus; no evaluation needs a judge model or external network.

### P8.1 — Define iterative-research contracts and budgets

**Dependencies:** P8.0  
**Decision required:** yes

**Goal:** make continuation and stopping explicit, auditable, and safe.

**Work:** define `ResearchRun`, `Iteration`, `EvidenceGap`, `SufficiencyAssessment`, `StopReason`, and a versioned `EvidenceQualityBudget` (max iterations, queries, sources, elapsed time, tokens, provider cost, and allowed domains). Default to low bounded limits and opt-in iteration.

**Requirements:** only defined gap classes may trigger a follow-up; explicit user constraints and cancellation always win; raw chain-of-thought is neither requested nor stored—persist structured reasons only.

**Acceptance criteria:** policy validation rejects unbounded budgets and unsupported actions; every terminal run has a clear stop reason.

**Out of scope:** autonomous goals, background work after a terminal state,
planner tool calls, a model-derived change to user constraints, or Phase 9
operations/authentication work.

### P8.2 — Persist idempotent run and iteration state

**Dependencies:** P8.1

**Goal:** survive retries/disconnects without duplicate research or misleading progress.

**Work:** persist append-only run/iteration events, leases, request idempotency, parent/child query links, budget consumption, and derived status. Resume only safely leased work; make cancellation terminal and prevent post-cancellation synthesis writes.

**Requirements:** cancellation keeps previously persisted evidence auditable
but makes it ineligible as a completed result unless explicitly resumed by a
new request; lease recovery records the prior attempt and cannot duplicate an
already committed adapter or synthesis result.

**Acceptance criteria:** tests cover duplicate delivery, lease expiry, restart, cancellation race, and no extra query after terminal state.

**Out of scope:** using SSE as durable state, destructive removal of partial
research records, or resume of a cancelled run without a new request.

### P8.3 — Implement structured evidence-sufficiency assessment

**Dependencies:** P8.1, P8.2

**Goal:** decide whether available evidence can answer the defined task.

**Work:** implement deterministic checks for required constraint evidence, freshness, unresolved conflict, entity confidence, candidate coverage, and citation support; optionally accept a validated LLM classification as advisory input. Emit structured gap records tied to evidence/candidate IDs.

**Requirements:** the assessor cannot assert a fact not in evidence or suppress a deterministic constraint failure; uncertain assessment prefers explicit insufficiency over continued looping.

**Acceptance criteria:** fixtures prove sufficient stop, gap classification, conflict preservation, and safe assessor fallback.

**Out of scope:** a model judging truth, gap records unsupported by a
validated evidence/decision snapshot, or implicit constraint relaxation.

### P8.4 — Generate focused, deduplicated follow-up searches

**Dependencies:** P8.3

**Goal:** fill named gaps rather than repeat broad search.

**Work:** map each permitted gap class to bounded query templates and optional validated planner proposals; check prior query normalization/results; enforce source/domain and remaining budget limits; persist why a query was proposed and whether it was skipped.

**Requirements:** the planner cannot widen a user’s requested location, dates,
budget, product variant, or other constraint without a new user request; a
follow-up query includes no more user/memory context than needed for the named
gap and remains subject to Phase 5 URL/content safeguards.

**Acceptance criteria:** tests prove targeted queries, duplicate suppression, budget refusal, no attempt to resolve unresolvable gaps, and preservation of user constraints.

**Out of scope:** broadening a search merely to find a convenient answer,
repeat-searching an exhausted gap, or any URL/content policy exception.

### P8.5 — Orchestrate bounded research iterations and final synthesis

**Dependencies:** P8.2–P8.4

**Goal:** connect assess → follow-up → search → evidence → reassess into a bounded state machine.

**Work:** execute one transition at a time through existing Phase 5 components, recompute Phase 6 constraints/ranking after relevant evidence changes, stop deterministically, and produce a sourced final result or clear incomplete result. Never re-run a completed iteration without an idempotency/lease check.

**Requirements:** preserve the exact Phase 5 source/evidence and Phase 6
decision contracts; when no further safe action exists, return the best
supported partial answer plus gap/stop reason rather than fabricating closure.

**Acceptance criteria:** integration tests cover every stop reason, recovery, partial evidence, and no regression to single-pass/ordinary-chat behavior when disabled.

**Out of scope:** parallel unbounded agent work, direct provider calls outside
the Phase 5 boundary, or a final result that hides an unresolved required gap.

### P8.6 — Stream safe research progress and render it

**Dependencies:** P8.2, P8.5

**Goal:** let users understand progress without exposing secrets or hidden reasoning.

**Work:** extend only the opt-in research event contract with stable milestones (planning, searching, extracting, assessing, follow-up, completed/incomplete/cancelled), iteration number, safe counts, and terminal reason. Render a cancellable timeline with citations/results only when available.

**Requirements:** no raw prompts, retrieved private content, provider traces, or chain-of-thought in events; reconnect uses persisted status rather than replaying work.

**Acceptance criteria:** UI/API tests cover ordering, reconnect, cancellation, failure, and inaccessible research sessions; normal chat SSE remains unchanged.

**Out of scope:** raw search queries/prompts, provider traces, unpersisted
progress, chain-of-thought, or reconnect-triggered execution.

### P8.7 — Evaluate, document, and verify Phase 8

**Dependencies:** P8.0–P8.6

**Goal:** promote iteration only when it improves defined evidence outcomes within budget.

**Work:** compare single-pass and iterative fixtures for required-fact coverage, invalid recommendations, conflict resolution visibility, evidence freshness, cost/query/time budget, and unnecessary iterations. Document policies, stop reasons, privacy-safe progress, operations, and feature gates.

**Requirements:** promotion criteria require a measurable benefit on defined
fixtures and no degradation in safety, provenance, constraints, or configured
budgets; publish comparisons for every policy/model/provider version and retain
the single-pass baseline as a selectable control.

**Acceptance criteria:** offline CI proves no infinite/repeated loop, budget breach, post-cancel work, unsupported citation, or constraint relaxation; iterative research remains disabled by default until evaluation thresholds are met.

**Implementation handoff:** record the finite-state transition table, event
schema, budget defaults/overrides, stop-reason taxonomy, recovery playbook,
and comparative evaluation command. Phase 9 operations must monitor these
without logging sensitive research content.

## Phase 8 completion review

Before declaring Phase 8 done, verify all task acceptance criteria and answer:

1. Is every extra query linked to a named, permitted evidence gap?
2. Can the system stop safely for sufficiency, exhaustion, failure, cancellation, or no productive next step?
3. Do repeated/adversarial results remain bounded by every configured resource budget?
4. Are progress events useful while excluding raw prompts and hidden reasoning?
5. Does iteration preserve Phase 5 provenance and Phase 6 constraint-first decisions?

Only after all answers are yes should work advance to Phase 9.
