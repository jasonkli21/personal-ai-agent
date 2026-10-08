# Phase 21 implementation plan — Deterministic task-aware routing

Renumbered from former Phase 13 with scope preserved. This phase establishes the semantic routing contract used by later deterministic and adaptive strategies.

## Scope boundary

**Goal:** Select among eligible endpoint profiles using transparent task rules, then produce an explicit execution plan.

### Normative commitments

- Define a small task taxonomy and typed routing requirements.
- Apply deterministic hard admission before any preference/scoring strategy.
- Define a replaceable project-owned `RoutingStrategy` seam; implement the deterministic scorer as its baseline strategy.
- Produce an `ExecutionPlan` without executing provider calls in the router or strategy.
- Trace candidate eligibility/rejection and selection with policy/strategy identity and version.
- Route chat plus at least two non-chat subtasks.

### Phase acceptance criteria

- No round-robin or provider-name priority chain exists in generic routing.
- Privacy, cost/execution mode, authorization, capabilities, context/output bounds, health, and exhaustion precede preference scoring.
- Known task type does not require an LLM classifier.
- Every strategy can select only from the deterministic eligible candidate set.
- Selection is explainable and replayable from bounded versioned facts without retaining raw prompts.

### Explicitly out of scope

- quota scarcity scoring (Phase 23);
- learned/adaptive routing (Phase 35);
- cascades (Phase 24);
- ChatGPT-plan automatic selection.

## Current state and reuse

Current dependency injection selects one Gemini client. Task routing, rejection traces, explicit execution plans, and actual per-turn producing-endpoint metadata need extension. The [target architecture](../../02-target-architecture.md#9-provider-runtime) and [inference/routing contract](../../03-free-tier-inference-and-routing.md) define ownership and the [Routing Observation Contract](../../03-free-tier-inference-and-routing.md#routing-observation-contract).

## Phase 10 storage dependency

DynamoDB turn/runtime records hold actual producing-endpoint attribution and compact actual-build manifests; Postgres owns versioned policy/registry and usage controls. Reference exact versions without duplicating canonical control records. See the [Phase 10 storage contract](../../phase-10-storage-ownership-and-access-patterns.md); existing work packages and acceptance remain unchanged.

## Prerequisites and work ordering

Required phases: 16, 18, 19, and 10. Phase 18 requires completion of Phase 17R, so routing cannot bypass the LiteLLM reconciliation gate. Work packages run in order.

## Phase-specific invariants

- Known callers pass task type rather than paying for classification.
- Hard admission is deterministic and outside the strategy seam; strategies cannot widen the candidate set or change execution mode.
- Strict-free, privacy/sensitivity, authorization, capability, context/output limits, credential/account usability, health/cooldown, and known exhaustion are hard constraints.
- Personal AI owns endpoint selection; the Personal AI inference gateway and LiteLLM execute the selected endpoint. LiteLLM Router must not select another provider/model.
- Strategies do not call providers, mutate orchestration state, own credentials/secrets, or silently switch cost modes.
- Route decisions reconstruct from the immutable/versioned or bounded decision-time inputs recorded under the [Routing Observation Contract](../../03-free-tier-inference-and-routing.md#routing-observation-contract).
- No raw prompt/embedding retention solely for route replay or future learning.

## Work packages

### P21.0 — Task taxonomy, requirements, and routing contracts

Define a small taxonomy from actual operations: chat, summary, extraction, research synthesis/planning where used, rewrite, structured generation, and embedding through its separate boundary. Callers supply known task type; no LLM classifier. Requirements include capability, privacy/sensitivity, prepared context and output bounds, quality-floor policy, citation/provenance behavior, deterministic validator references, and finite retry/escalation permission.

Define repository-equivalent contracts for:

```text
RoutingStrategyInput
  task/profile identity + version and typed requirements
  eligible endpoint profiles + profile versions
  decision-time policy context
  applicable quality evidence/references
  latency/reliability inputs when used
  quota/scarcity inputs when available in Phase 23

RoutingStrategyResult
  selected eligible endpoint
  optional bounded ranking/scores for eligible endpoints
  strategy ID/version
  policy/strategy reason

ExecutionPlan
  task/profile identity and selected endpoint
  permitted alternatives
  execution mode and required capabilities
  validator policy and escalation/cascade permission
  attempt/time/token bounds
  registry/policy versions
  routing decision ID, strategy ID/version, and reason
```

Use repository naming conventions, but preserve the seams. A strategy receives only endpoints that passed admission; it has no provider or credential handles. The result is data, not an execution call. A new application task such as `travel.itinerary_proposal` declares typed requirements/policy rather than adding a router branch. This is bounded configuration, not a runtime task-plugin system; Phase 24 implements validator execution.

**Acceptance:** Actual task callers supply typed requirements without an LLM classifier. A synthetic task/profile fits the same contracts without a generic orchestration branch.

### P21.1 — Hard admission and deterministic baseline strategy

Stage 1 filters candidates by requested execution mode, endpoint enabled/configured state, strict-free/cost eligibility, authorization, privacy/sensitivity, required capabilities, context/output limits, credential/account usability, health/cooldown, and known exhaustion. Preserve eligibility/rejection reasons in the decision record. No score or learned strategy can override a failed hard constraint.

Stage 2 passes only eligible endpoint profiles to the replaceable `RoutingStrategy`. Implement a deterministic baseline strategy using versioned fixed task priorities and measured quality where available. Phase 22 quality does not exist yet: use explicitly unmeasured configured baseline priorities and never fabricate numeric quality. If a task requires a measured floor with no applicable profile, deny. Use latency/reliability only when configured as decision inputs. Phase 23 may later add typed scarcity inputs or a compatible deterministic strategy without changing orchestration.

Consume registered endpoint facts and [execution/cost eligibility](../../03-free-tier-inference-and-routing.md#execution-identity-and-cost-modes). Provider/model names may appear in profile configuration and trace identity, but cannot define generic control flow or ordered chains. BYOK/ChatGPT remain outside the automatic strict-free router.

The selected endpoint and permitted alternatives become an `ExecutionPlan`. A separate execution layer revalidates the frozen registry/policy versions as required, performs the selected endpoint through the Personal AI inference gateway, and records invocation lineage. The strategy itself makes no provider calls.

**Acceptance:** Hard filters run first; the deterministic scorer is replaceable and is not scattered through orchestration; unmeasured quality is never represented as measured; unknown-cost, paid, or explicit-only profiles are rejected even when free candidates are exhausted.

### P21.2 — Replayable decision observations and integration

Record a bounded privacy-safe decision observation as specified in the [Routing Observation Contract](../../03-free-tier-inference-and-routing.md#routing-observation-contract): decision ID; task/profile and policy versions; strategy ID/version; privacy-safe request characteristics; all considered candidates with endpoint/profile versions and admission result/reasons; exact quality evidence and latency/reliability inputs used; selected endpoint, bounded ranking/reason; and immutable/versioned registry/policy references or decision-time snapshots. Quota/scarcity fields remain optional until Phase 23. Do not retain raw prompts or embeddings for replay.

Route chat and at least two actual non-chat tasks using the shared runtime, existing assembly, and invocation ledger. Persist actual producing provider/model/endpoint and safe routing-decision identity on automatic turns rather than static `AI_MODEL`. Join the decision to Phase 19 invocation IDs and outcomes; later Phase 22 quality, Phase 23 scarcity, and Phase 24 validator/cascade outcomes use the same stable lineage. Conversation persistence follows DynamoDB after Phase 10. Maintain branch/supersession and partial-failure semantics.

**Acceptance:** Chat plus two non-chat tasks route through the runtime and store actual producing-endpoint attribution; historical decision context and strategy/policy versions can be reconstructed without raw prompts; execution follows the plan and cannot silently change endpoint or mode.

## Requirement coverage

R21.1–R21.6 map to P21.0–P21.2: task taxonomy/requirements, hard eligibility, deterministic priorities, rejection/selection tracing, multi-task integration, and automatic-turn attribution. The additional strategy/plan/observation requirements are covered by P21.0–P21.2 and the shared contract referenced above.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only when this phase changes the truth of user-visible capabilities, architecture, tech stack, setup, deployment, provider support, or project status. Keep implementation details in `docs/`; if no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run deterministic tests for admission ordering, strategy contract conformance, rejected-candidate isolation, `ExecutionPlan` bounds/identity, replay serialization, privacy-safe telemetry, and routing through chat plus two non-chat tasks. Run applicable backend/frontend tests, lint, type checks, and builds. Finish with `git diff --check`. External/provider/cloud checks are opt-in and skipped checks remain **unverified**, never passed. Record actual files/interfaces, tested revision/configuration, commands/results, disabled gates, and unresolved external checks in implementation evidence.
