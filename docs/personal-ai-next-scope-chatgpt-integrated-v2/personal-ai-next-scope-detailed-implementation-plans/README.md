# Detailed next-scope implementation plans

Reconciled: 2026-10-05, code revision `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`.

Read the [canonical roadmap](../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../09-phase-0-reconciliation.md) and [shared execution contract](execution-contract.md). The [earlier Phase 0 record](phase-0-reconciliation-2026-10-05.md) remains historical and incomplete; its assertions are independently verified in the new review.

Actual repository behavior and accepted ADRs define the baseline; canonical product/architecture documents define intended scope; these plans define execution. All original normative commitments, acceptance and exclusions remain represented. Existing working services/repositories/fakes are reused, and new target types are marked future. `source/` preserves old link paths as canonical-document pointers rather than duplicate content.

There are **32 plans**. Phase 17 is represented by four subphase documents, with no separate parent plan. The next-scope numbering is separate from existing repository Phases 1–9. Exact prerequisite IDs and current byte sizes live in [manifest.json](manifest.json); recommended order is the table order.

| Phase | Plan | Required prerequisites |
| --- | --- | --- |
| 0 | [Reconcile with current repository and roadmap](plans/phase-0-implementation-plan.md) | none |
| 1 | [Application and workspace identity](plans/phase-1-implementation-plan.md) | 0 |
| 2 | [Application registry and manifest model](plans/phase-2-implementation-plan.md) | 1 |
| 3 | [Context source and provider abstraction](plans/phase-3-implementation-plan.md) | 1, 2 |
| 4 | [Context builder refactor](plans/phase-4-implementation-plan.md) | 3 |
| 5 | [Deterministic context planner](plans/phase-5-implementation-plan.md) | 4 |
| 6 | [Provenance and context inspection](plans/phase-6-implementation-plan.md) | 5 |
| 7 | [Permissions and sensitivity policy](plans/phase-7-implementation-plan.md) | 3, 5, 6 |
| 8 | [Provider-neutral inference and embedding contracts](plans/phase-8-implementation-plan.md) | 4, 7 |
| 9 | [Concrete provider adapters: Gemini, Groq, Cloudflare](plans/phase-9-implementation-plan.md) | 8 |
| 10 | [Provider/model registry and strict-free eligibility](plans/phase-10-implementation-plan.md) | 7, 9 |
| 11 | [Provider usage accounting and quota ledger](plans/phase-11-implementation-plan.md) | 10 |
| 12 | [Cloud Storage artifact tier and retention](plans/phase-12-implementation-plan.md) | 1, 6, 11 |
| 13 | [Deterministic task-aware routing](plans/phase-13-implementation-plan.md) | 8, 10, 11 |
| 14 | [Cross-provider task evaluation matrix](plans/phase-14-implementation-plan.md) | 12, 13 |
| 15 | [Quota-aware routing](plans/phase-15-implementation-plan.md) | 14 |
| 16 | [Bounded cascades and deterministic validation](plans/phase-16-implementation-plan.md) | 15 |
| 17.1 | [ChatGPT authentication and local bridge](plans/phase-17-1-implementation-plan.md) | 8, 10 |
| 17.2 | [ChatGPT provider/runtime integration, policy, and usage handling](plans/phase-17-2-implementation-plan.md) | 11, 13, 17.1 |
| 17.3 | [Shared AI sidecar UI](plans/phase-17-3-implementation-plan.md) | 6, 17.2 |
| 17.4 | [ChatGPT domain integration contract](plans/phase-17-4-implementation-plan.md) | 17.3 |
| 18 | [Travel integration](plans/phase-18-implementation-plan.md) | 7, 13, 16 |
| 19 | [Shopping integration](plans/phase-19-implementation-plan.md) | 7, 13, 16 |
| 20 | [Finance integration](plans/phase-20-implementation-plan.md) | 7, 13, 16 |
| 21 | [Health integration](plans/phase-21-implementation-plan.md) | 7, 13, 16 |
| 22 | [Cross-app context federation](plans/phase-22-implementation-plan.md) | 7, 18, 19, 20, 21 |
| 23 | [Mutation proposal framework](plans/phase-23-implementation-plan.md) | 7, 18, 19, 20, 21 |
| 24 | [Smarter context planning](plans/phase-24-implementation-plan.md) | 14, 22 |
| 25 | [Search and evidence retrieval optimization](plans/phase-25-implementation-plan.md) | 11, 12, 14 |
| 26 | [Memory retrieval optimization](plans/phase-26-implementation-plan.md) | 1, 4, 8, 14 |
| 27 | [Adaptive routing experiments](plans/phase-27-implementation-plan.md) | 14, 15, 16 |
| 28 | [Integrated evaluation and hardening](plans/phase-28-implementation-plan.md) | 12, 17.4, 22, 23, 24, 25, 26, 27 |

Domain baseline/backend work in 18–23 consumes shared context/runtime/domain contracts. Its additive sidecar tasks additionally require 17.4; do not remove pending scope if live ChatGPT eligibility is blocked. Optimization consumes recorded deterministic baselines before promotion. Local completion and external enablement are separate milestones; existing Phase 9 lifecycle/migration/cloud release gaps remain required.

Next implementation: **Phase 1 — Application and workspace identity**, offline with synthetic fixtures and disabled live gates. Phase 0 stops after documentation reconciliation and verification.
