# Phase 21 — deterministic task-aware routing

Phase 21 implements the local routing core described by the [phase plan](personal-ai-next-scope-detailed-implementation-plans/plans/phase-21-implementation-plan.md) and the shared [routing contract](03-free-tier-inference-and-routing.md). Known callers can provide a typed task profile, hard admission runs before a replaceable strategy, and the result is an explicit provisional execution plan. The router and strategy contain no provider client or credential handle.

The Phase 15 prerequisite is still open. The authoritative membership and end-to-end derived-context revocation acceptance required by the plan must complete before any request workflow uses automatic endpoint selection. Chat and existing non-chat app workflows remain Gemini-only. This phase does not claim actual producing-endpoint attribution for application turns.

## Contracts and decision flow

- `personal_ai.routing.phase21` defines the task taxonomy (`chat`, `summary`, `extraction`, research planning/synthesis, rewrite, structured generation, and embedding), versioned task policies, quality floors, privacy-safe request facts, runtime and quality evidence, strategy input/results, endpoint-specific preparation, quota references, and the bounded execution plan.
- `RoutingDecisionService.route` applies the Phase 18 registry assessment and checks endpoint authorization, credential usability, health/cooldown, known exhaustion, and required task-quality floors before it creates strategy input. Rejected endpoint identities and reason codes remain in the observation; rejected profiles and their task priorities are removed from the strategy view.
- `RoutingStrategy` is a project-owned seam. `DeterministicScoringStrategy` uses configured task priorities plus only the fresh quality, latency, and reliability measurements enabled by the task profile. It resolves ties by endpoint profile ID and then profile version in ascending order. Missing measurements do not become fabricated quality values or win by an implicit zero score.
- The selection is provisional. `finalize` requires exact endpoint/profile and serializer identity, endpoint context/output fit, required counter confidence/schema coverage, current policy/authorization/credential/health/source facts, and reservations for every applicable quota bucket. It persists the final reservation event before returning a ready plan. Reselection references are advisory; they cannot dispatch a fallback.
- A fit, reservation, or revalidation failure stays attached to its decision. A different endpoint can be considered only through a new linked decision; the service excludes the prior endpoint, recomputes the requirements/plan bounds, and caps reselection by the task profile.

## Replay and persistence

`PostgresRoutingDecisionRepository` stores canonical decision facts and append-only outcome events in Postgres migration `020_routing_decisions.sql`. The owner/application/workspace scope is checked on reads and writes, owner deletion fences deny access/publication, and expired replay inputs are hidden before bounded purge. The decision record contains request/run IDs, typed requirements, task/policy/registry/strategy versions, candidate profiles and decision-time evidence, the provisional result, and lifecycle lineage. It stores neither raw prompt text nor embeddings.

Decision facts are limited to 32 candidates and 65,536 encoded bytes. Outcome history allows at most 32 events and 65,536 encoded bytes; each event is bounded. When decision facts exceed the replay cap, the service persists an explicit no-route/incomplete observation with compact candidate IDs and profile digests instead of truncating required facts. Replay is available only while the exact stored decision facts remain within the declared horizon, at most 90 days; it never reconstructs from the current registry.

The repository exposes bounded owner-scoped lookup/list paths for request, run, invocation, attempt, and evaluation IDs. Account export includes the canonical rows in the Postgres inventory. Scheduled worker maintenance invokes a bounded purge for expired routing observations.

The opt-in `tests/persistence/test_routing_decisions.py` suite exercises the real migration, scoped access/export joins, owner fences, expiration, and purge against Postgres. It is included in the existing Postgres CI step; offline fakes do not establish that the SQL ran successfully.

## Scope and acceptance gates

Offline tests route chat, research synthesis, and structured itinerary-proposal profiles through the same service without a classifier. Those tests establish contract behavior with synthetic endpoint facts; they do not establish application workflow integration, provider behavior, live account eligibility, or actual turn attribution. The next routing integration work must wait for Phase 15 membership and end-to-end revocation acceptance, then connect authorized callers to the shared builder and Phase 19 invocation/reservation ledger while preserving branch, partial-failure, and source narrowing rules. See [implementation evidence](phase-21-implementation-evidence.md) for commands, results, and open verification.
