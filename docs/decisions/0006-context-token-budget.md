# ADR 0006 — Provider-authoritative context budgeting

Status: Accepted (2026-10-01)

## Decision

Every send, regenerate, and edit/retry passes through one context assembler.
The application input ceiling is `MAX_CONTEXT_TOKENS - MAX_RESPONSE_TOKENS -
CONTEXT_SAFETY_MARGIN_TOKENS`. Application/system instructions and labelled
summary wrappers count within that input ceiling. The newest user message is
mandatory and never truncated; optional history is selected backwards as complete
user/assistant turns, then sent chronologically. Failed, streaming, superseded,
and orphaned historical messages are excluded.

Production Gemini requests use provider token counts, including the complete
system instruction, through the documented REST `generateContentRequest` shape.
The locked SDK rejects system instructions on its public Developer API counting
method, so the provider adapter contains a narrowly scoped transport call and an
offline test against the installed SDK. See the
[official countTokens contract](https://ai.google.dev/api/tokens).
Counting failure rejects preparation safely; it never substitutes an estimate
and presents it as authoritative. Per-request repeated counts are cached.

Offline planning uses a labelled UTF-8 byte estimate with a 10% multiplier and
per-message overhead; fixture tests use deterministic word units. Neither claims
to reproduce provider tokenization. Inspection uses estimates to remain read-only
and avoid provider calls; summary provenance labels the counter used to create it.

Defaults for the example Gemini configuration are application ceilings of
32,768 context tokens, 4,096 response tokens, and 1,024 safety tokens. They are
conservative application choices, not automatic discovery of model capabilities.
`AI_MODEL` remains environment configuration; changing it requires verifying the
model's supported context/output sizes and running the opt-in synthetic check.

## Consequences

The Phase 1 message-count gate is removed. Impossible mandatory content returns
`context_message_too_large` before an assistant placeholder/LLM stream, while the
persisted user remains editable. Invalid operator budgets return
`context_budget_invalid`. Provider counting adds latency and requests; this phase
does not introduce billing analytics or automatic provider fallback.
