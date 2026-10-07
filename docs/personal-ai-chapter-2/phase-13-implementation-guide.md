# Phase 13 implementation guide — Deterministic context planner

Phase 13 adds deterministic, versioned rules for choosing narrow context-source
operations before request-specific retrieval. Planner output is a selection
proposal; the Phase 11 coordinator repeats capability, scope, operation, field,
deadline, result-count, and byte checks before any provider runs. The Phase 12
builder applies the planned source token ceilings and retains its provenance,
sensitivity, expiry, permission, and global-budget checks. See the
[implementation evidence](phase-13-implementation-evidence.md) for the tested
source state and remaining limits.

## Runtime contracts

- [`context/planner.py`](../../backend/src/personal_ai/context/planner.py)
  defines `ContextPlanner`, `ContextPlanningRule`, `ContextPlan`, and
  content-free decisions. Phrase matching is case-folded and deterministic over
  at most 4,096 intent characters. Rules have stable versioned IDs, categories,
  explanations, fields, result and byte ceilings, token allocations, optional
  bounded windows, and optional exact candidate-entity selection.
- Planning considers only capabilities registered for the request's
  application and provider implementations currently available to the
  coordinator. Unavailable optional rules produce an explicit omission; they
  never expand to another provider or broader field set. Required unavailable
  sources stop planning. Ambiguous categories in one configured exclusive
  group produce no selections.
- Plans carry a request-scope fingerprint, selected provider operations,
  category and rule reasons, and per-source token allocations. The safe Phase 12
  build manifest records the planner version and reason codes without storing
  user intent. A plan cannot be reused for another request scope.
- `ContextAssembler.plan_context` resolves planning capability state before
  retrieval. `ChatTurnService` invokes it before the memory retriever. Default
  rules select the bounded `ai_memory.search` projection only when the user
  explicitly asks to recall saved personal context. They select one
  `global_profile.profile` field only for a matching explicit profile question.
  Other requests do not read either source.
- The built-in permission revalidator checks the `memory_enabled` gate and
  re-reads current per-application profile sharing at final assembly. The
  memory adapter also checks owner/application/workspace scope, active status,
  content sensitivity, and selected fields. Other permission dependencies
  remain fail-closed until their own current-grant revalidators are supplied.
- App integrations can supply additional deterministic rules for registered
  providers, including exact fields, result/byte/token bounds, time windows,
  and candidate entity references. The coordinator still performs the final
  authorization and contract checks. No model call or LLM classification is
  part of planning.

## Baseline and evaluation

[`context-plan-fixtures.json`](../../backend/src/personal_ai/evaluation/context-plan-fixtures.json)
contains named standalone and synthetic Travel, Shopping, Finance, and Health
requests, plus ambiguous and unavailable-provider cases. The
[`context_planner` evaluation](../../backend/src/personal_ai/evaluation/context_planner.py)
records selected/excluded fields, exact synthetic provider calls, answer-support
coverage, response bytes, estimated input tokens, planned token budgets, and
fixture latency. Run it with `make context-plan-eval`. The fixtures use fake
providers and establish only local deterministic planning behavior.

## Scope limits

Phase 13 does not add real Travel, Shopping, Finance, or Health providers, a
domain rule set, an LLM planner, adaptive planning, provider routing, or new
authorization policy. The default production rules cover explicit
personal-memory recall and individual shared profile fields. Domain behavior
is exercised with synthetic providers; live domain integrations and their
permissions remain future work.

Review the repository-root README before closing this phase. It was updated to
describe deterministic context planning and expose the new evaluation command.
