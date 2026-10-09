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
- Required count confidence/serializer compatibility and required measured quality floors are hard eligibility filters applied before every strategy.
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

DynamoDB turn/runtime records hold actual producing-endpoint attribution and compact actual-build manifests; Postgres owns versioned policy/registry, invocation/quota controls, and canonical compact routing-decision observations. The D turn references the P decision ID; it does not duplicate the decision record. See the [Phase 10 storage contract](../../phase-10-storage-ownership-and-access-patterns.md).

## Prerequisites and work ordering

Required phases: 15, 16, 18, 19, and 10. Phase 18 requires completion of Phase 17R, so routing cannot bypass the LiteLLM reconciliation gate. Phase 15's authoritative membership and end-to-end revocation acceptance must also be complete before any request workflow is connected to automatic endpoint selection. Work packages run in order.

## Phase-specific invariants

- Known callers pass task type rather than paying for classification.
- Hard admission is deterministic and outside the strategy seam; strategies cannot widen the candidate set or change execution mode.
- Strict-free, privacy/sensitivity, authorization, capability, context/output limits, credential/account usability, health/cooldown, and known exhaustion are hard constraints.
- Required input-count provenance/confidence and endpoint/serializer/schema match are hard constraints. Tasks requiring measured quality admit only fresh, sufficiently covered endpoint evidence at or above their declared floor. Missing, stale, insufficiently covered, or below-floor evidence rejects before strategy input. A task explicitly configured to allow an unmeasured baseline may use fixed priorities without representing quality as measured.
- Endpoint-specific context fit is finalized after provisional selection. Remote counter/summary work is separately admitted; strategies never call providers. Final policy/source/profile revalidation and all-bucket reservation precede dispatch.
- Personal AI owns endpoint selection; the Personal AI inference gateway and LiteLLM execute the selected endpoint. LiteLLM Router must not select another provider/model.
- Strategies do not call providers, mutate orchestration state, own credentials/secrets, or silently switch cost modes.
- Route decisions reconstruct from the immutable/versioned or bounded decision-time inputs recorded under the [Routing Observation Contract](../../03-free-tier-inference-and-routing.md#routing-observation-contract).
- No raw prompt/embedding retention solely for route replay or future learning.

## Work packages

### P21.0 — Task taxonomy, requirements, and routing contracts

Define a small taxonomy from actual operations: chat, summary, extraction, research synthesis/planning where used, rewrite, structured generation, and embedding through its separate boundary. Callers supply known task type; no LLM classifier. Requirements include capability, privacy/sensitivity, endpoint-specific prepared context and output bounds, required count provenance/confidence, mandatory-versus-unmeasured quality-floor policy, citation/provenance behavior, deterministic validator references, and finite retry/escalation permission. Attempt limits count physical sends at every SDK/client layer plus auxiliary count/summary calls under one deadline and root budget. A task profile cannot treat a score preference as a substitute for its mandatory quality floor.

Define repository-equivalent contracts for:

```text
RoutingStrategyInput
  task/profile identity + version and typed requirements
  eligible endpoint profiles + profile versions
  admitted count compatibility and mandatory floor-qualified evidence
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
  task/profile identity and provisional/final selected endpoint
  reselection_candidate_refs (advisory only; never executable fallback)
  execution mode and required capabilities
  endpoint-specific prepared-input/count identity and final-fit result
  validator policy and escalation/cascade permission
  physical-attempt/auxiliary-call/time/token/quota bounds
  registry/policy versions
  routing decision ID, strategy ID/version, and reason
```

Use repository naming conventions, but preserve the seams. A strategy receives only endpoints that passed admission; it has no provider or credential handles. The result is data, not an execution call. `reselection_candidate_refs` are advisory references for the orchestrator only; the execution layer must never treat them as fallback permission. Selecting another endpoint requires a new linked routing decision, endpoint-specific assembly/count, policy/source/profile revalidation, quota reservation, and a new final plan. A new application task such as `travel.itinerary_proposal` declares typed requirements/policy rather than adding a router branch. This is bounded configuration, not a runtime task-plugin system; Phase 24 implements validator execution.

**Acceptance:** Actual task callers supply typed requirements without an LLM classifier. A synthetic task/profile fits the same contracts without a generic orchestration branch.

### P21.1 — Hard admission and deterministic baseline strategy

Stage 1 filters candidates by requested execution mode, endpoint enabled/configured state, strict-free/cost eligibility, authorization, privacy/sensitivity, required capabilities, endpoint-specific counter identity/provenance/confidence and structured-schema coverage, declared context/output bounds, credential/account usability, known quota-bucket relationships, health/cooldown, and known exhaustion. Preserve eligibility/rejection reasons in the decision record. No score or learned strategy can override a failed hard constraint.

Apply task quality policy before Stage 2. For a measured-only task, reject any candidate whose evidence is missing, stale, below declared coverage/confidence, or below the task floor. Phase 22 defines profile freshness/coverage evidence. Before Phase 22, only tasks explicitly allowing unmeasured baseline operation may proceed on configured fixed priorities; never fabricate numeric quality. The same floor-qualified candidate set is passed to every strategy. Use latency/reliability only when configured as decision inputs. Phase 23 may later add typed scarcity inputs or a compatible deterministic strategy without changing orchestration.

The first eligible strategy result is provisional until endpoint-specific assembly and count prove fit. Persist the provisional decision in `preparing` state before any remote counter, summary, or generation call. Use the selected endpoint's serializer/counter and context/output ceiling. A remote counter or summary call has its own endpoint/privacy/cost/quota admission and Phase 19 attempt identity; if denied it receives zero input. If count evidence is insufficient or the prepared input does not fit, do not dispatch generation to that endpoint; reselect within finite attempt/deadline/auxiliary-call limits, persist a linked decision before any new external call, and recompute assembly/count. Revalidate frozen authorization/source/policy and endpoint versions immediately before reservation and generation. A revoked source may be dropped only when task policy permits narrowing; otherwise abort. Reassembly never silently broadens disclosure.

Consume registered endpoint facts and [execution/cost eligibility](../../03-free-tier-inference-and-routing.md#execution-identity-and-cost-modes). Provider/model names may appear in profile configuration and trace identity, but cannot define generic control flow or ordered chains. BYOK/ChatGPT remain outside the automatic strict-free router.

The selected endpoint and advisory `reselection_candidate_refs` become an `ExecutionPlan`. A separate execution layer revalidates the frozen registry/policy versions as required and performs exactly the final selected endpoint through the Personal AI inference gateway. It does not dispatch an alternative directly; orchestrator reselection creates a linked decision and new final plan after recomputing endpoint-specific preparation and admission. Invocation lineage records each decision and physical attempt. The strategy itself makes no provider calls.

**Acceptance:** Hard filters and mandatory quality floors run before every strategy; below-floor, stale/missing, or insufficiently covered evidence cannot enter any strategy. An explicitly unmeasured baseline task remains usable before Phase 22 without invented quality. The deterministic scorer is replaceable and not scattered through orchestration; count-incompatible, unknown-cost, paid, or explicit-only profiles are rejected even when free candidates are exhausted.

### P21.2 — Replayable decision observations and integration

Before any external counter, summary, or generation call, persist the canonical bounded privacy-safe decision observation in Postgres as specified in the [Routing Observation Contract](../../03-free-tier-inference-and-routing.md#routing-observation-contract). Its initial `preparing` record includes schema version and decision ID; task/profile, policy, registry, strategy implementation/configuration, and tie-break versions; privacy-safe request facts; every considered candidate with endpoint/profile versions and admission result/reasons; exact quality-floor/evidence and latency/reliability inputs used; provisional selected or no-route outcome; and immutable/versioned references or decision-time snapshots. Append bounded preparation/dispatch outcomes without rewriting decision facts. Respect the 32-candidate/64-KiB bound and 90-day default replay horizon. Record rejected/no-route choices and failures before dispatch. The P observation is advisory history, not an admission grant; P19 reservations remain authoritative quota controls, and durable observation publication is a fail-closed precondition for external calls. If the observation or required reservation cannot be stored, make no external call. A D automatic turn stores the decision ID and actual producing-endpoint attribution only. Re-selection to a different endpoint creates a linked decision ID before its next external call; a physical retry of the identical plan retains its decision ID and uses a distinct P19 attempt ID. Do not retain raw prompts or embeddings for replay.

Route chat and at least two actual non-chat tasks using the shared runtime, existing assembly, and invocation ledger. Persist actual producing provider/model/endpoint and safe routing-decision identity on automatic turns rather than static `AI_MODEL`. Join the decision to Phase 19 invocation IDs and outcomes; later Phase 22 quality, Phase 23 scarcity, and Phase 24 validator/cascade outcomes use the same stable lineage. Conversation persistence follows DynamoDB after Phase 10. Maintain branch/supersession and partial-failure semantics.

**Acceptance:** Chat plus two non-chat tasks route through the runtime and store actual producing-endpoint attribution; historical decision context and exact strategy/policy versions can be reconstructed within the supported replay horizon without raw prompts; no-route and pre-dispatch failures are recorded; execution follows the plan and cannot silently change endpoint or mode. Cover two endpoints with different serializers/context limits, final-fit failure, denied remote counter with zero disclosure, bounded fit- and reservation-driven linked reselection with recomputed preparation, revocation between preparation/dispatch, and correct final producing-endpoint attribution. Replay a non-chat and no-route decision after registry/evidence updates and optional-artifact loss; expired/deleted inputs return unavailable. Cover cross-owner read denial and crash/partial-publication reconciliation. Phase 24 acceptance covers linked cascade selections. Overflow never silently truncates required replay facts.

## Requirement coverage

R21.1–R21.6 map to P21.0–P21.2: task taxonomy/requirements, hard eligibility, deterministic priorities, rejection/selection tracing, multi-task integration, and automatic-turn attribution. The additional strategy/plan/observation requirements are covered by P21.0–P21.2 and the shared contract referenced above.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only when this phase changes the truth of user-visible capabilities, architecture, tech stack, setup, deployment, provider support, or project status. Keep implementation details in `docs/`; if no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run deterministic tests for admission ordering, strategy contract conformance, rejected-candidate isolation, `ExecutionPlan` bounds/identity, replay serialization, privacy-safe telemetry, and routing through chat plus two non-chat tasks. Run applicable backend/frontend tests, lint, type checks, and builds. Finish with `git diff --check`. External/provider/cloud checks are opt-in and skipped checks remain **unverified**, never passed. Record actual files/interfaces, tested revision/configuration, commands/results, disabled gates, and unresolved external checks in implementation evidence.
