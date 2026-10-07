# Detailed implementation plans

This directory contains 33 implementation plans for the regenerated chapter. `manifest.json` is the machine-readable index and prerequisite graph.

## Status

- Phases 0–2: completed history.
- Phase 10: P10.0 documentation decisions complete; P10.1–P10.6 remain unimplemented. Firestore remains current.
- Phases 11–36: future work under the preserved-scope numbering map.

See [ADR 0021](../../decisions/0021-polyglot-persistence-foundation.md), the [Phase 10 storage contract](../phase-10-storage-ownership-and-access-patterns.md) and [migration/verification plan](../phase-10-migration-cutover-and-verification-plan.md) for the reviewed foundation.

## Scope-preservation contract

Former Phase 3–28 detailed plans are authoritative for substantive scope. Renumbering changes only phase/prerequisite identifiers, persistence references invalidated by Phase 10, and README-maintenance obligations. Do not replace specific work packages or acceptance criteria with generic summaries.

## Shared closeout rule

Every phase must review the repository-root README for factual accuracy. Change it only for user/developer-visible current-state facts; implementation details remain here. Phase 10 has a mandatory README architecture/tech-stack/setup/deployment reconciliation after cutover.

## Plans

- Phase 0: [Repository, architecture and planning reconciliation](plans/phase-0-implementation-plan.md)
- Phase 1: [Application and workspace identity](plans/phase-1-implementation-plan.md)
- Phase 2: [Application registry and manifest model](plans/phase-2-implementation-plan.md)
- Phase 10: [Polyglot persistence foundation and Firestore migration](plans/phase-10-implementation-plan.md)
- Phase 11: [Context source and provider abstraction](plans/phase-11-implementation-plan.md)
- Phase 12: [Context builder refactor](plans/phase-12-implementation-plan.md)
- Phase 13: [Deterministic context planner](plans/phase-13-implementation-plan.md)
- Phase 14: [Provenance and context inspection](plans/phase-14-implementation-plan.md)
- Phase 15: [Permissions and sensitivity policy](plans/phase-15-implementation-plan.md)
- Phase 16: [Provider-neutral inference and embedding contracts](plans/phase-16-implementation-plan.md)
- Phase 17: [Concrete provider adapters: Gemini, Groq, Cloudflare](plans/phase-17-implementation-plan.md)
- Phase 18: [Provider/model registry and strict-free eligibility](plans/phase-18-implementation-plan.md)
- Phase 19: [Provider usage accounting and quota ledger](plans/phase-19-implementation-plan.md)
- Phase 20: [Cloud Storage artifact tier and retention](plans/phase-20-implementation-plan.md)
- Phase 21: [Deterministic task-aware routing](plans/phase-21-implementation-plan.md)
- Phase 22: [Cross-provider task evaluation matrix](plans/phase-22-implementation-plan.md)
- Phase 23: [Quota-aware routing](plans/phase-23-implementation-plan.md)
- Phase 24: [Bounded cascades and deterministic validation](plans/phase-24-implementation-plan.md)
- Phase 25.1: [ChatGPT authentication and local bridge](plans/phase-25-1-implementation-plan.md)
- Phase 25.2: [ChatGPT provider/runtime integration, policy, and usage handling](plans/phase-25-2-implementation-plan.md)
- Phase 25.3: [Shared AI sidecar UI](plans/phase-25-3-implementation-plan.md)
- Phase 25.4: [ChatGPT domain integration contract](plans/phase-25-4-implementation-plan.md)
- Phase 26: [Travel integration](plans/phase-26-implementation-plan.md)
- Phase 27: [Shopping integration](plans/phase-27-implementation-plan.md)
- Phase 28: [Finance integration](plans/phase-28-implementation-plan.md)
- Phase 29: [Health integration](plans/phase-29-implementation-plan.md)
- Phase 30: [Cross-app context federation](plans/phase-30-implementation-plan.md)
- Phase 31: [Mutation proposal framework](plans/phase-31-implementation-plan.md)
- Phase 32: [Smarter context planning](plans/phase-32-implementation-plan.md)
- Phase 33: [Search and evidence retrieval optimization](plans/phase-33-implementation-plan.md)
- Phase 34: [Memory retrieval optimization](plans/phase-34-implementation-plan.md)
- Phase 35: [Adaptive routing experiments](plans/phase-35-implementation-plan.md)
- Phase 36: [Integrated evaluation and hardening](plans/phase-36-implementation-plan.md)
