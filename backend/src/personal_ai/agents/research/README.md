# Research orchestration

This package coordinates bounded, owner-scoped research. Search/provider calls remain in adapters; evidence validation and the shared context/LLM contracts remain in their owning packages. Research sessions do not write chat messages or durable memory.

## Module map

- `contracts.py` and `repositories.py`: Phase 5 request/session state and repository contract.
- `service.py`: one request-owned pass, including query planning, bounded attempts, evidence selection, synthesis, expiry, and fenced session persistence.
- `iterative_contracts.py`, `iterative_repositories.py`, and `iterative_fakes.py`: typed Phase 8 run, budget, event, state, repository, and test-fixture contracts.
- `iterative_service.py`: bounded iterative state machine over the Phase 5 session/evidence pipeline. It owns deterministic sufficiency/gap assessment, follow-up sequencing, run transitions, budget/resource reservations, cancellation/recovery fences, and safe progress events. It remains the main context-cost hotspot; read this map and the contracts first, then inspect only the relevant state transition.

## State, budgets, and recovery

Phase 5 stores source queries, attempts, observations, selected evidence, citations, and answer in an expiring owner-scoped session. Phase 8 persists a separate versioned run linked to that session. Repository transactions/fences protect state transitions and stale-worker recovery; uncertain external calls are not silently retried. The run ledger bounds queries, provider attempts, tokens, time, and cost. Iteration, progress, and decision gates remain off by default; single-pass research remains the normal path.

## Entry points and verification

Read `contracts.py` and `service.py` for single-pass behavior, or `iterative_contracts.py` before touching `iterative_service.py`. Relevant checks are `backend/tests/test_research_pipeline.py`, `test_research_routes.py`, `test_iterative_research.py`, `test_iterative_research_contracts.py`, and `test_iterative_research_routes.py`. Use `make research-eval` and `make iterative-research-eval` for the synthetic baselines. See the [research task router](../../../../../docs/README.md), [research-agent guide](../../../../../docs/research-agent.md), and [Phase 8 release evidence](../../../../../docs/releases/phase-8-iterative-research.md).
