# Shared execution contract

This contract applies to every detailed plan in this package.

## Preserve scope

A renumbered phase inherits every substantive requirement, work package, invariant, non-goal, acceptance criterion, and verification duty from its former plan unless the current plan explicitly identifies and justifies a change. Renumbering alone is never a reason to shorten scope.

## Understand before editing

Inspect the current repository, ADRs, implementation evidence, interfaces, tests, and active deployment configuration before substantive changes. Named future types are design targets, not permission to create parallel fictional modules when an existing seam should be extended.

## Storage ownership

After Phase 10:

- DynamoDB owns operational timeline record classes assigned by the ownership map;
- Postgres/pgvector owns relational/query-rich knowledge/vector state;
- GCS owns large artifact bodies when Phase 20 is active;
- one record class has one canonical store;
- no cross-store atomic transaction is assumed;
- cross-store operations are idempotent/recoverable.

Research run/session/replay groups and knowledge lifecycle events/state/effect receipts remain Postgres-owned; execution jobs remain DynamoDB-owned. Preserve existing atomic source/job validation through the narrow [Phase 10 storage contract](../phase-10-storage-ownership-and-access-patterns.md), without assuming guard expiry resolves an unknown effect. Export original embedding values and declare snapshot coverage; detailed recovery and cutover rules belong in the [Phase 10 verification plan](../phase-10-migration-cutover-and-verification-plan.md).

Do not reintroduce Firestore as canonical target storage after Phase 10 unless a separately approved architecture decision changes the roadmap.

## Security and scope

Owner/application/workspace isolation is mandatory across direct IDs, listings, vector queries, jobs, replay/idempotency, exports, traces, and cross-store references. Client metadata does not grant authority. Sensitive data must be authorized before retrieval/disclosure rather than fetched broadly and filtered afterward.

## Inference transport and routing ownership

Personal AI's neutral inference contracts remain the application-facing boundary. Implemented Phase 17R uses the LiteLLM Python SDK to normalize transport below the Personal AI inference gateway; LiteLLM types do not leak into context, domain, or application code. Personal AI owns endpoint profiles, hard admission/privacy/cost policy, semantic endpoint selection, quota semantics, evaluation, cascades, and later adaptive routing. LiteLLM Proxy/Gateway and semantic Router are not initial scope. Phase 17R disables implicit SDK/provider/HTTP retries; a later explicitly admitted retry repeats only the already-selected endpoint and receives a distinct Phase 19 physical-attempt identity/reservation. Unknown outcomes are not replayed under new identities.

Phase 18's endpoint registry and strict-free admission foundation is implemented after the Phase 17R gate; it is not yet connected to request-workflow provider selection. Phase 21 separates hard admission from a project-owned `RoutingStrategy` and produces an `ExecutionPlan`; every strategy receives only eligible endpoints and cannot call providers or bypass policy. Phase 21's deterministic scorer is the baseline implementation, not routing architecture embedded in orchestration.

## Routing observations and replay

Phases 19–24 record bounded, privacy-safe, versioned semantic facts and stable lineage so decisions can join to invocation, quality, quota, validator, and cascade outcomes. Follow the [Routing Observation Contract](../03-free-tier-inference-and-routing.md#routing-observation-contract), including its canonical scoped Postgres owner, decision bounds, 90-day replay horizon, no-route/reselection lineage, and separation between advisory observations and authoritative admission controls. Record decision-time mutable facts as immutable/versioned references or bounded snapshots; do not retain raw prompts or embeddings solely for future routing research. Phase 35 derives features and experiments with alternate strategies later. Replay reconstructs bounded decision context and does not promise unexecuted counterfactual provider outputs.

## Failure semantics

Differentiate terminal success, incomplete/unknown outcome, explicit rejection, unavailable dependency, timeout/cancellation, and advisory optional failures. Do not retry uncertain side effects under new identities. Required outputs such as exports fail explicitly when incomplete.

## Strict-$0

No phase may silently enable a potentially paid provider/cloud path in strict-$0 mode. Volatile free-tier facts are operational configuration/evidence, not hard-coded constants. External live checks remain distinct from deterministic offline tests.

## Documentation and root README

Every phase must review living docs affected by implementation. Before closing the phase, review the repository-root `README.md` and update it if implemented current-state facts changed in any of these categories:

- capabilities/features;
- architecture/data flow;
- technology stack;
- prerequisites/local setup;
- cloud deployment/topology;
- supported providers/integrations;
- project/phase status that the README communicates.

Keep detailed implementation mechanics in `docs/`, not the root README. If no README-visible fact changed, record that no README edit was required. Do not update the README to future target state before implementation is complete.

## Verification

Use deterministic fakes/synthetic fixtures for offline coverage. Run applicable backend/frontend tests, lint, typecheck/build checks, phase-specific evaluations, syntax checks, and `git diff --check`. A new documented command must exist before a plan claims it ran. Missing credentials/network/provider/cloud/domain access cannot weaken offline tests; skipped external checks are **unverified**, never passed.

## Evidence

Record actual files/interfaces, tested revision/configuration, commands/results, disabled gates, and unresolved external checks. Historical records remain historical; supersession is added explicitly rather than rewriting past architecture as current.
