# Phase 24 — Bounded cascades and deterministic validation

Phase 24 adds an internal, explicitly configured buffered task coordinator. Application workflows remain Gemini-only behind the existing Phase 15 membership and end-to-end revocation gates. No task is promoted to a cascade by default. See the [written plan](personal-ai-next-scope-detailed-implementation-plans/plans/phase-24-implementation-plan.md) and [verification evidence](phase-24-implementation-evidence.md).

## Implementation map and ownership

| Component | Responsibility and boundary |
| --- | --- |
| `routing.phase21.CascadePolicy` on `RoutingTaskProfile` | Server-owned weaker-to-stronger endpoint order, validator input/output contract IDs, cumulative token and per-bucket quota ceilings, bounded output bytes. Existing P21 task fields retain attempt/depth/auxiliary/deadline/retention ownership. |
| `routing.cascade.CascadeCoordinator` | Resolve a registered validator before preparation; select each stage through P21/P23; prepare, finalize and dispatch; expose only a durably accepted result. No provider or application classification. |
| `context.cascade.FrozenContextAssembler` | Reuse `ContextBuilder` over the same frozen messages/source records with local conservative fitting and endpoint-specific ceilings. Preserve permission dependencies and source text; do not retrieve or summarize inside a cascade. |
| `routing.cascade.EndpointInputPreparer` | Bind the neutral generator/counter to the selected endpoint, perform an admitted authoritative count using `prepare_bounded_input`, and carry frozen sensitivity/policy to inference. Schema and serializer participate in the prepared-input digest. |
| `RoutingDecisionService` | Own current authorization/profile checks, single-use generation receipts, auxiliary identities, root locking and deadline, shared physical admission/claim/settlement helpers, and bounded terminal validation observations. |
| `PostgresProviderUsageAccounting` | Keep attempts, unknown-outcome fencing, quota reservations and health canonical. Read cumulative reservations/known actual usage under the existing request advisory lock; never add a second cascade ledger. |
| `validation.tasks` and `validation.checks` | Versioned `TaskValidator` registration; typed exact-source/schema/citation/span/constraint inputs; bounded safe validation results. Phase 22 scoring reuses the extracted structural/constraint checks. Domain validators compose or replace these checks without generic control-flow edits. |
| `evaluation.cascade` | Paired P22 fixture runner with per-case quality gates and complete resource totals. Evaluation never activates a runtime policy. |

## Control flow and contracts

An explicit task policy orders at most five endpoint profiles. This is a trusted configured strength order, not a provider-name ranking or a learned policy. Each stage still passes all existing strict-free, sensitivity, capability, quality, source authorization, quota and health gates; P23 scores only the admitted stage. A missing stage stops without a send. Alternative source sets require the existing explicit source-narrowing policy. Required citations and hard rules remain frozen even when optional sources are narrowed.

Preparation rebuilds with the shared context builder, then recounts the exact messages and structured schema using the selected endpoint's authoritative counter. Each external count consumes an existing root auxiliary slot and its own P19 physical attempt. Count and generation reservations consume the same request attempt/token/quota bounds. The assembler uses local estimates and performs no external retrieval or summaries. Runtime resolvers and send callbacks are trusted internal capabilities and must supply the existing conformant, zero-hidden-retry neutral adapters with nested gateway accounting disabled; P21/P19 own these physical sends. There is no permissive live resolver or public cascade API. Generic fixture preparation must explicitly declare itself synthetic and bind to a synthetic-test-attested endpoint; live preparation requires an authoritative counter identity.

The task's existing `max_reselections` governs linked depth, `max_physical_attempts` includes counts and generation, `max_auxiliary_calls` caps external counting/preparation, and `deadline_ms` bounds the whole root. Limits must cover the configured stages. Cumulative per-bucket limits count all original reservations or larger known settled usage across quota resets; unpriced quota units fail closed. Unknown capacity remains unknown. No paid, BYOK, subscription, or hidden retry path is introduced.

The existing preparation identity plus committed dispatch permit is the implemented execution-plan seam. No parallel `ExecutionPlan` state or new persistence table is introduced. Counting uses the same routing service's auxiliary-event identity and P19 single-use claim, with current operation-specific authority. Generation remains protected by the existing finalization/claim receipt. The primary and auxiliary paths share physical admission, claim and neutral settlement helpers.

Provider success is accounted separately from task validation. A terminal routing event records a bounded `ValidationResult` and the producing attempt ID; validator ID/version remain in the immutable task snapshot. A successful but invalid response settles its physical consumption and leaves a failed decision, permitting the existing single-child linked reselection. Rejected buffers are discarded by the dispatch service. Accepted results include the actual generation invocation/attempt and endpoint/profile version. Each endpoint gets its own preparation digest; different serializers or truncation do not masquerade as identical input.

Unknown/timeout outcomes retain their original P19 fence. Same-endpoint physical retries are not enabled for cascades. Duplicate auxiliary identities and already-started cascades cannot resend. Interrupted work with no retained output is unavailable: there is no reconstruction from current source/profile state and no regeneration under a new identity. This deliberately conservative recovery behavior preserves the existing unknown-outcome semantics.

`replay_cascade` follows complete retained decision links and replays the frozen P23 inputs. It distinguishes initial/final endpoints, decisions and the accepted attempt without raw outputs or optional GCS bodies. Missing, deleted, expired or unsupported records are unavailable. Callers pass the existing `dependency_expires_at` retention bound when source rights or other dependencies expire sooner; owner-scoped repository reads/deletion fences remain authoritative.

## Validators and exposure

`StructuredTaskValidator` validates strict JSON object shape, required fields/types, citation membership/coverage, exact source offsets/quotes, and declared hard constraints. Duplicate JSON keys, nonfinite constants and excessive nesting are rejected. Exact source text and rules are frozen across stages. Validation exceptions produce a safe rejection code without retaining exception text, model output or source contents. Rich itinerary/shopping semantics remain domain-owned registered validators, rather than task-name branches. A synthetic domain validator demonstrates the registration seam.

Only bounded/structured tasks can configure this path. Streaming tasks are rejected, so a chat that has exposed its first delta cannot restart or concatenate a different model. Missing validators/contracts fail before preparation or dispatch.

## Evaluation and adoption

Run `make cascade-eval` with the backend development environment active. The paired runner uses the twenty Phase 22 synthetic fixtures, P23 routing, P24 buffering, shared context assembly, admitted synthetic exact counters and every P19 attempt. It records auxiliary calls, total count/generation tokens and quota, validation rejects, and modeled end-to-end latency. Synthetic counter counts and timing are contract fixtures, not provider measurements.

Both arms accept all twenty cases with quality 1.0. Direct stronger execution uses 40 physical sends (20 counts + 20 generations); weaker-first uses 54 (27 counts + 27 generations), with seven validation rejects. Total conservative tokens are 17,508 versus 23,603. Shared quota use and modeled latency also increase. This baseline does not justify adoption; direct routing remains the deterministic rollback/default. Live project-specific quality, counters, actual latency and quota measurements remain external gates.

## Architecture audit and downstream use

The audit checked canonical state, authorization, disclosure, execution modes, context preparation, profile versions, concurrency, unknown outcomes, observation capacity and provider transport ownership. Root decisions and P19 reservations remain the only durable lifecycle/accounting state; source snapshots and buffers are transient. No migration, adaptive scorer, provider/app-name branch, domain mutation, browser route, credential storage or GCS-only replay dependency was added.

Phase 25's user-controlled ChatGPT lane remains separate from strict-free escalation. Phase 26 can register Travel-owned providers, policies and validators through these seams after its Phase 15 prerequisites; it cannot use this implementation to mutate itinerary authority. Phase 35 can later replace strategy behavior without moving validation or accounting into the transport. Domain-specific validator adapters and production source/membership acceptance belong to their existing domain phases and gates.
