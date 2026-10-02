# Roadmap Reconciliation

Status: proposed update to high-level planning  
Date: 2026-10-02

## Principle

Do not reset the project to the earlier v1 roadmap.

Use the repository's implemented phases as the baseline and layer the multi-application vision onto later phases.

## Current / delivered

### Phase 1 — Basic chat

Delivered locally.

Keep:

- Firestore persistence,
- append-only branch history,
- SSE streaming,
- regenerate/edit-and-retry,
- Gemini behind provider boundary.

### Phase 2 — Context management

Delivered locally.

Keep:

- provider-authoritative budgeting,
- working summaries,
- context inspection,
- shared assembler.

### Phase 3 — Simple attributable memory

Delivered locally.

Keep:

- exact user-source provenance,
- conservative extraction,
- embeddings,
- bounded retrieval,
- Firestore KNN,
- memory/context gates.

### Phase 4 — Experimental memory lifecycle

Delivered locally.

Keep:

- versioned deterministic scoring,
- append-only lifecycle events,
- conservative deterministic consolidation,
- contradiction/forgetting policies,
- private worker,
- durable job before Pub/Sub notification,
- fenced processing/recovery.

External verification remains a separate closeout concern.

## Phase 5 — Bounded source-grounded research

Authorized; ADR 0011 accepted.

Do not replace it with the earlier much broader "deep research agent" sketch.

Initial shape should remain bounded and auditable.

After implementation/evaluation, it can become the substrate for richer research.

## Phase 6 — Entities, constraints, ranking

Retain the existing intent:

- canonical entities,
- deterministic hard constraints,
- explainable ranking,
- memory preferences only after constraints,
- stale/conflicting/duplicate evidence evaluations.

Add one architectural goal:

> Keep entity/evidence/ranking contracts usable by external rich applications, but do not build a generic app SDK yet.

## Phase 7 — Domain validation

Reframe rather than replace the repo plan.

### In `personal-ai-system`

Build reusable AI-side domain capabilities:

- travel schemas/adapters/constraints/ranking;
- shopping schemas/adapters/constraints/ranking.

### Outside or beside the core repo

A rich reference app may eventually be created in its own repository.

Travel is the best first UI/application validation because it exercises:

- domain context,
- search,
- itineraries,
- maps,
- booking extraction,
- structured proposed edits.

The core repository should not need to contain the entire itinerary UI.

Shopping can then validate entity resolution/comparison/offer freshness.

Do not schedule health here.

## Phase 8 — Iterative research

Retain the existing intent only after bounded Phase 5/6 behavior is measured:

- evidence sufficiency,
- focused follow-up queries,
- conflict/staleness handling,
- stopping budgets,
- progress streaming.

Long-running async research should be introduced only when request-owned bounded SSE is no longer sufficient.

## Phase 9 — Hardening

Authentication should likely move earlier if a real personal/domain application begins storing non-synthetic personal data.

The existing Phase 9 items remain necessary:

- authentication/authorization,
- secrets,
- observability,
- rate/cost safeguards,
- backups/export/deletion,
- maintenance.

### Possible adjustment

If travel/shopping begin using real private email/bookings before Phase 9, split out a prerequisite phase:

```text
Security prerequisite:
  authenticated personal owner
  private API ingress/session
  provider data policy
  export/deletion basics
```

Do not wait for a nominal phase number if a feature crosses the current security boundary.

## Later — external application platform

Only after one or two real domain clients exist, consider formalizing:

- TypeScript/Python client SDK,
- app identity,
- tool registry,
- action/change-set protocol,
- memory-scope permissions,
- reusable React AI components,
- connector/event ingestion.

This is not a current numbered phase and should not preempt the research roadmap.

## Later — health application

Health is intentionally outside the current roadmap.

It should be reconsidered after:

- auth/authorization is real,
- sensitive provider policy exists,
- authoritative-vs-derived data separation is proven,
- blob/document handling is secure,
- deletion/export/audit controls exist.

The architecture should leave room for it without implementing health-specific behavior now.
