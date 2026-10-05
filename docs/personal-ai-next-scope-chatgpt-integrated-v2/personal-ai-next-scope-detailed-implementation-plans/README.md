# Detailed next-scope implementation plans

Generated: 2026-10-05

This package expands the integrated next-scope roadmap into phase-by-phase execution plans using the current `personal-ai-system` repository's implementation-plan conventions as the structural benchmark.

## Scope rule

The plans **elaborate but do not broaden** the integrated roadmap. The source documents are copied under `source/` for review. If a detailed plan conflicts with the integrated source scope, the integrated source scope wins and Phase 0 should reconcile the discrepancy before implementation.

The existing substantive work remains unchanged. ChatGPT integration is additive and is represented as four separate implementation documents for **17.1–17.4**, followed by the renumbered existing domain/optimization phases.

## Repository conventions used

The generated plans follow the current repo's patterns:

- explicit scope boundary and exclusions;
- dependency map;
- numbered work packages;
- dependencies / goal / work / requirements / acceptance criteria / out of scope for each package;
- deterministic fake/offline tests by default;
- opt-in provider/emulator/cloud verification recorded separately;
- implementation-guide and release-evidence closeout;
- completion review before advancing phases.

They also honor current `AGENTS.md` boundaries: provider SDKs remain behind the LLM boundary, Firestore remains behind repositories, model turns use shared context assembly, current owner/auth behavior is preserved, and external evidence remains distinct from durable memory.

## Phase 0 repository reconciliation

The [dated Phase 0 review](phase-0-reconciliation-2026-10-05.md) maps the code at `24f75a7`, existing Phase 1–8 local implementations, partial existing Phase 9 safeguards, reusable classes, missing work, dependency order, and external verification gaps. The [revised Phase 0 plan](plans/phase-0-implementation-plan.md) is documentation-only. Every later detailed plan has a repository-specific note; its hypothetical candidate paths and repeated boilerplate do not require parallel subsystems or advance later-phase scope.

The next-scope Phase 1–28 numbering is separate from the repository's existing Phase 1–9 history. Phase 17.1–17.4 is additive: strict-free Gemini/Groq/Cloudflare, context, storage, routing, evaluation, and domain work remain required. Existing Phase 9 release gates still block live private-data/production claims, while offline next-scope work can proceed with synthetic data.

## Plan files

There is no separate parent Phase 17 plan. The ChatGPT block is intentionally split into four execution documents.

| Phase | Plan | Size |
|---|---|---:|
| 0 | [Reconcile with current repository and roadmap](plans/phase-0-implementation-plan.md) | 5,593 B |
| 1 | [Application and workspace identity](plans/phase-1-implementation-plan.md) | 16,345 B |
| 2 | [Application registry and manifest model](plans/phase-2-implementation-plan.md) | 16,848 B |
| 3 | [Context source and provider abstraction](plans/phase-3-implementation-plan.md) | 20,867 B |
| 4 | [Context builder refactor](plans/phase-4-implementation-plan.md) | 19,060 B |
| 5 | [Deterministic context planner](plans/phase-5-implementation-plan.md) | 17,165 B |
| 6 | [Provenance and context inspection](plans/phase-6-implementation-plan.md) | 16,401 B |
| 7 | [Permissions and sensitivity policy](plans/phase-7-implementation-plan.md) | 19,628 B |
| 8 | [Provider-neutral inference and embedding contracts](plans/phase-8-implementation-plan.md) | 18,125 B |
| 9 | [Concrete provider adapters: Gemini, Groq, Cloudflare](plans/phase-9-implementation-plan.md) | 26,644 B |
| 10 | [Provider/model registry and strict-free eligibility](plans/phase-10-implementation-plan.md) | 21,429 B |
| 11 | [Provider usage accounting and quota ledger](plans/phase-11-implementation-plan.md) | 19,315 B |
| 12 | [Cloud Storage artifact tier and retention](plans/phase-12-implementation-plan.md) | 27,244 B |
| 13 | [Deterministic task-aware routing](plans/phase-13-implementation-plan.md) | 19,694 B |
| 14 | [Cross-provider task evaluation matrix](plans/phase-14-implementation-plan.md) | 19,018 B |
| 15 | [Quota-aware routing](plans/phase-15-implementation-plan.md) | 19,379 B |
| 16 | [Bounded cascades and deterministic validation](plans/phase-16-implementation-plan.md) | 18,609 B |
| 17.1 | [ChatGPT authentication and local bridge](plans/phase-17-1-implementation-plan.md) | 45,567 B |
| 17.2 | [ChatGPT provider/runtime integration, policy, and usage handling](plans/phase-17-2-implementation-plan.md) | 38,222 B |
| 17.3 | [Shared AI sidecar UI](plans/phase-17-3-implementation-plan.md) | 40,086 B |
| 17.4 | [ChatGPT domain integration contract](plans/phase-17-4-implementation-plan.md) | 28,536 B |
| 18 | [Travel integration](plans/phase-18-implementation-plan.md) | 26,106 B |
| 19 | [Shopping integration](plans/phase-19-implementation-plan.md) | 25,301 B |
| 20 | [Finance integration](plans/phase-20-implementation-plan.md) | 29,461 B |
| 21 | [Health integration](plans/phase-21-implementation-plan.md) | 29,312 B |
| 22 | [Cross-app context federation](plans/phase-22-implementation-plan.md) | 20,840 B |
| 23 | [Mutation proposal framework](plans/phase-23-implementation-plan.md) | 23,572 B |
| 24 | [Smarter context planning](plans/phase-24-implementation-plan.md) | 18,452 B |
| 25 | [Search and evidence retrieval optimization](plans/phase-25-implementation-plan.md) | 18,029 B |
| 26 | [Memory retrieval optimization](plans/phase-26-implementation-plan.md) | 16,687 B |
| 27 | [Adaptive routing experiments](plans/phase-27-implementation-plan.md) | 15,910 B |
| 28 | [Integrated evaluation and hardening](plans/phase-28-implementation-plan.md) | 25,988 B |


## Count

- **32 implementation-plan documents** total.
- Includes Phase 0 because it is part of the authoritative integrated roadmap.
- Phase 17 is represented by four documents: 17.1, 17.2, 17.3, 17.4.

## Recommended execution

1. Start with Phase 0 against the live repository and reconcile any drift.
2. Use each detailed plan as the phase backlog after reading its repository-specific note and the integrated source scope.
3. After implementation, produce/update the phase implementation guide and release evidence from the actual code and verification results.
4. Do not carry speculative file names or implementation assumptions forward when the repository provides a better existing seam.
