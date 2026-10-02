# Personal AI System — Reconciled Architecture Notes

Status: assessment/handoff package  
Reconciled: 2026-10-02

This package reconciles the earlier long-term platform discussion with the current repository documentation supplied on 2026-10-02.

The repository documents remain authoritative for implemented behavior. These notes do not rewrite accepted ADRs or imply that future work has been implemented.

## Current baseline

Based on the supplied repository docs:

- Phases 1–4 are implemented locally.
- External verification remains incomplete for some Firestore, Gemini, vector-index, and deployed Cloud Run behavior.
- Phase 5 research has an accepted ADR and explicit authorization, but this package does not assume Phase 5 implementation is complete.
- Firestore Native mode remains the deployed durable store.
- SSE remains the browser-facing streaming transport.
- Pub/Sub now has a real, bounded Phase 4 use for durable memory-lifecycle notifications; it is still not part of chat token streaming.
- Gemini remains behind a provider-neutral internal boundary.
- The public bootstrap is unauthenticated and is not suitable for real sensitive personal data.

## Reconciled long-term direction

`personal-ai-system` should evolve into a reusable AI/research substrate that can serve multiple rich applications without becoming their UI or authoritative domain database.

The current in-repo `domains/travel` and `domains/shopping` direction should be interpreted as shared domain intelligence/configuration modules. Rich travel, shopping, and eventually health products may live in separate repositories and call the shared system.

This preserves the current repository architecture while allowing specialized UIs such as:

- editable travel itineraries and maps,
- structured product comparison/research workspaces,
- health timelines and data views.

## Documents

1. [Reconciliation summary](docs/01-reconciliation-summary.md)
2. [Long-term vision](docs/02-long-term-vision.md)
3. [Current state and near-term scope](docs/03-current-state-and-near-term-scope.md)
4. [Domain application integration](docs/04-domain-application-integration.md)
5. [Free-tier and cloud portability](docs/05-free-tier-and-cloud-portability.md)
6. [Roadmap reconciliation](docs/06-roadmap-reconciliation.md)
7. [Codex assessment brief](docs/07-codex-assessment-brief.md)

## Source repository docs used for reconciliation

The supplied sources include:

- `project-brief.md`
- `architecture.md`
- `implementation-plan.md`
- `gcp-deployment.md`
- `api-contract.md`
- `research-agent.md`
- ADRs 0001–0011 supplied in the handoff

Codex should read the repository's current versions of those files before recommending implementation changes.
