# Architecture reconciliation — 2026-10-02

Status: documentation reconciliation after the Phase 5 local implementation.
Reviewed repository revision: `66a0f65` (before these documentation edits).
This record summarizes the documentation changes; it does not claim Phase 6
authorization or new runtime verification.

## Why these docs changed

The live repository implements Phases 1–5 locally, while some high-level
descriptions still depicted Phase 5 as pending, Pub/Sub as a research path, or
travel and shopping as necessarily in-repository applications. The supplied
`personal-ai-system-reconciled-docs/` package describes a useful longer-term
direction but was written before the live Phase 5 completion evidence. The
[Phase 5 guide](phase-5-implementation-guide.md),
[release record](releases/phase-5-source-grounded-research.md), and accepted
[ADR 0011](decisions/0011-bounded-source-grounded-research.md) remain the
authority for delivered research behavior. The supplied package was not edited.

## Changes made

| Area | Updated documents | Clarification |
| --- | --- | --- |
| Status and handoff | [README](../README.md), [project brief](project-brief.md), [implementation plan](implementation-plan.md), [API contract](api-contract.md) | Phases 1–5 are delivered locally; external checks remain open; implementation is paused after Phase 5 and Phase 6 is not authorized. |
| Runtime topology | [README](../README.md), [architecture](architecture.md), [GCP deployment](gcp-deployment.md), [research-agent model](research-agent.md) | Chat and bounded research use direct requests and SSE. Pub/Sub currently serves gated, durable Phase 4 memory-lifecycle jobs through the private worker. Phase 5 does not submit research jobs. |
| Separate applications | [project brief](project-brief.md), [architecture](architecture.md), [implementation plan](implementation-plan.md), [research-agent model](research-agent.md), [Phase 7 plan](phase-7-implementation-plan.md) | The core owns reusable AI/research and optional thin domain intelligence. A future rich application may live elsewhere and own its authoritative trips, bookings, purchases, business rules, and UI. |
| Phase 6 contract gate | [Phase 6 plan](phase-6-implementation-plan.md) | Canonical entities and claims are research representations. Decisions retain owner-scoped evidence provenance and a reconstructable snapshot while records are retained; a Phase 5 research-session reference is optional when another validated evidence path supplied the decision. Provider retention/deletion obligations apply to snapshots too. |
| Storage, security, model examples | [GCP deployment](gcp-deployment.md), [implementation plan](implementation-plan.md) | Firestore remains the current store; canonical records and vector retrieval are separate portability concerns. Cloud Storage waits for a real blob need. Real private data triggers authentication, authorization, and provider-policy work regardless of phase number. `gemini-2.5-flash` stays the example/default pending opt-in compatibility checks for a newer stable Flash model; embedding migration is separate. |

## Boundary for upcoming work

The [Phase 6 plan](phase-6-implementation-plan.md) remains a plan. Before its
schemas are implemented, P6.1 must make evidence references and owner checks
explicit and test both a session-backed and an independently supplied,
validated-evidence decision. Hard constraints remain deterministic; current
requirements and fresh evidence outrank optional memory preferences. The core
must not write an external application's authoritative state as a side effect
of research or ranking.

No generic application/plugin framework, app manifests, SDK extraction,
general workflow engine, AWS adapter, Cloud Storage integration, rich domain
app, or health feature was added by this documentation work.

## Verification and open gaps

This documentation-only reconciliation was checked by reviewing local links,
content against the referenced code and release records, and `git diff --check`.
No backend/frontend test suite, provider call, emulator check, or cloud
deployment was run for this documentation change. The Phase 5 release record
reports its own dated offline test and evaluation results; these are not new
results from this reconciliation.

Real Firestore/emulator transactions and index readiness, Brave storage/AI-use
rights and provider behavior, Gemini token counting/strict synthesis, deployed
browser cancellation, and earlier-phase external checks remain open. Before
switching the generation-model recommendation, run opt-in synthetic counting,
streaming, summary, extraction, research-output, timeout, and cancellation
checks for the candidate model and record the model ID, configuration, date,
revision, results, and remaining gaps. Do not treat a generation-model switch
as an embedding-vector migration.
