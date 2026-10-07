# Product intent and durable constraints

This is a personal learning and research project, not an attempt to host or reproduce a frontier model. It explores the systems around hosted models: streaming chat, persistence, context management, retrieval, memory, search, evidence, ranking, and evaluation.

The long-term goal is a reusable AI/research substrate. Shared modules may provide evidence-grounded travel and shopping intelligence, while separate domain applications retain authority over their records, business rules, and rich user interfaces.

Current implementation and verification status live in [current-state.md](current-state.md). The root [README](../README.md) describes current runtime and setup. This brief records product intent and constraints; it is not a phase diary or delivery record.

## Non-goals

- Do not host a frontier model on free-tier compute; use hosted inference behind replaceable provider interfaces.
- Do not add large orchestration frameworks unless the project explicitly chooses that direction.
- Do not infer production or private-data readiness from local implementation.
- Do not add product scope merely because a future plan exists; work on later scope requires explicit authorization.
- Do not let a model decide deterministic requirements such as budget, dates, availability, or dimensions.

## Durable architectural invariants

1. **Provider independence:** provider SDKs remain inside provider adapters and the `llm` boundary.
2. **Separate data classes:** durable, attributable user memory is distinct from external observations with source, observation time, and freshness/expiry.
3. **Evidence-backed conclusions:** recommendations retain the evidence and policy that support them; they do not become unqualified facts or memory.
4. **Requirements before preferences:** application code filters hard constraints before applying soft ranking preferences.
5. **Memory is advisory:** it may guide investigation and ranking but cannot override current constraints or fresh evidence.
6. **Thin shared domain modules:** shared AI-side modules may add schemas, adapters, constraints, and ranking features; external applications own authoritative domain state and rich UI.
7. **Evaluated experiments:** experimental behavior remains isolated until measured against a baseline.

See [architecture.md](architecture.md) for the stable system boundaries, [docs/README.md](README.md) for task routing and document authority, and [AGENTS.md](../AGENTS.md) for the operating contract.
