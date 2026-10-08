# Phase 16 implementation guide — Provider-neutral inference and embedding contracts

Phase 16 is implemented locally. Current runtime support remains Gemini plus
deterministic fakes; this phase adds capability contracts without provider
routing or provider selection. The [implementation evidence](phase-16-implementation-evidence.md)
records the tested tree, resolution of the 2026-10-07 independent review, and
the remaining live-provider checks.

## Runtime contracts

- [`llm/client.py`](../../backend/src/personal_ai/llm/client.py) defines
  provider/model/serializer identity, declared capabilities, streamed delta and
  explicit terminal events, bounded and structured generation results, usage
  confidence/source, token counts, and embedding-space results. A terminal
  success is required before compatibility streams report normal exhaustion;
  incomplete, rejected, and failed results map to safe application errors.
- [`llm/gemini.py`](../../backend/src/personal_ai/llm/gemini.py) implements
  neutral generation and structured generation. Provider SDK calls and
  serialization remain inside the `llm` adapter boundary. The adapter reports
  actual model and usage when Gemini supplies them, uses the stricter of the
  request deadline and configured provider timeout, and closes streams under a
  bounded cleanup scope.
- [`llm/fake.py`](../../backend/src/personal_ai/llm/fake.py) implements the
  same terminal, bound, usage, structured-generation, and capability behavior
  for offline contract checks. It reports estimates as estimates and can use a
  distinct synthetic provider/model identity.
- [`llm/context.py`](../../backend/src/personal_ai/llm/context.py) keeps
  Gemini's authoritative REST token-count transport and binds results to its
  model and exact endpoint serializer. Summary generation uses the neutral
  completion contract and retains invocation attribution in `SummaryDraft`.
- [`llm/preparation.py`](../../backend/src/personal_ai/llm/preparation.py)
  provides shared bounded preparation for non-chat inputs. It counts the exact
  endpoint messages, requires an authoritative provider count with matching
  identity, and rejects inputs above their configured ceiling.
- [`memory/extraction.py`](../../backend/src/personal_ai/memory/extraction.py)
  owns memory extraction instructions, exact user-source projection, bounded
  input preparation, structured-result parsing, and existing service-level
  validation. Application policy authorizes memory counting, extraction, and
  embeddings before remote disclosure, including query retrieval and background
  consolidation. Its Gemini adapter returns per-invocation attribution; chat
  extraction remains advisory and runs after a completed turn.
- [`llm/memory.py`](../../backend/src/personal_ai/llm/memory.py) exposes
  embeddings as a separate capability. Each result includes provider, model,
  dimensions, normalization, document/query task semantics, and space version.
  [`memory/contracts.py`](../../backend/src/personal_ai/memory/contracts.py),
  the repositories, and consolidation checks preserve and compare that full
  identity. Existing vectors and v1/v2 logical record schemas default to the
  compatible `v1` space; no re-index or vector rewrite is performed.
- [`services/chat_turns.py`](../../backend/src/personal_ai/services/chat_turns.py)
  consumes explicit stream events, requires terminal success before completion,
  observes normal stream exhaustion after a terminal event, preserves partial
  output on failure, and logs bounded provider/model/usage attribution without
  prompt or provider payload data. Summary, research, iterative synthesis,
  itinerary proposal, and booking extraction retain safe per-invocation
  attribution through the bounded text facade and keep task-owned validation.
  Memory extraction uses neutral structured generation, counts its exact schema,
  and retains exact-source parsing and validation in the memory service.

Only Gemini is configured in the current application. Higher-level paths import
neutral contracts or the adapter at composition boundaries; provider SDK imports
and SDK request/response handling remain under `personal_ai.llm`. No intelligent
routing, new provider, hosted credential support, quota optimization, or
embedding re-index was added.

## Scope limits

- Offline tests cover the neutral contract and the current adapter's local
  mapping. They do not establish live Gemini count, structured-output, stream,
  or embedding compatibility.
- Provider usage is reported only when available. Missing usage remains
  explicitly unavailable; fake counts remain estimated.
- Phase 14 immutable Postgres policy/source-version references and Phase 15
  end-to-end derived-context revocation remain open. Phase 16 does not close
  those prerequisites or production identity/security gates.
- The root README was reviewed. No edit was required because the configured
  provider, user-facing capabilities, setup, and deployment behavior did not
  change.
