# Phase 17 implementation guide — Concrete provider adapters

Phase 17 adds local reference adapters for Gemini, Groq, and Cloudflare Workers
AI. The [implementation evidence](phase-17-implementation-evidence.md) records
offline checks and the account, privacy, and live-compatibility gates that remain
open.

## Adapter contracts

- [`llm/client.py`](../../backend/src/personal_ai/llm/client.py) remains the
  provider-neutral boundary for identity, capabilities, streamed deltas,
  terminal status, usage, structured generation, and rate-limit metadata.
- [`llm/gemini.py`](../../backend/src/personal_ai/llm/gemini.py) continues to
  implement Gemini generation behind that contract. The Gemini memory adapter
  keeps the existing embedding model, tasks, dimensions, normalization, and
  `v1` space identity.
- [`llm/groq.py`](../../backend/src/personal_ai/llm/groq.py) uses Groq's
  OpenAI-compatible Chat Completions endpoint. It supports bounded/streamed
  generation and JSON Schema output when that exact model has passed structured
  output preflight. It captures reported token usage and normalized rate-limit
  headers; 429 errors retain the same safe metadata. The request adapter does
  not retry.
- [`llm/cloudflare.py`](../../backend/src/personal_ai/llm/cloudflare.py) uses
  Cloudflare Workers AI's account-scoped OpenAI-compatible endpoint. It supports
  bounded/streamed generation and JSON Mode when the selected model passed
  structured-output preflight. Model validators in the consuming task remain
  authoritative because JSON Mode is not itself a guarantee that every schema
  constraint is met.
- [`llm/openai_compatible.py`](../../backend/src/personal_ai/llm/openai_compatible.py)
  contains only shared wire mechanics. Provider IDs, endpoint URLs, output-token
  fields, schema envelopes, credentials, and enablement gates stay in the
  adapter/configuration boundary. Completion bodies are limited to 1 MiB;
  streamed responses are limited to 2 MiB, with 128 KiB line and event limits.
  Limits are checked while reading, before JSON parsing or event accumulation.
  Empty and whitespace-only terminal output is incomplete.

Completion and stream identities must include the returned model ID. The ID
must exactly match the configured model or one of the exact aliases explicitly
listed in `GROQ_APPROVED_MODEL_ALIASES` or
`CLOUDFLARE_APPROVED_MODEL_ALIASES` for that configured account/model
preflight. No prefix, revision, or other implicit alias matching is performed;
the verified returned ID is retained in `GenerationMetadata`.

The request and response shapes follow the current [Groq Chat API](https://console.groq.com/docs/api-reference), [Groq structured output guide](https://console.groq.com/docs/structured-outputs), [Workers AI OpenAI-compatible API](https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/), and [Workers AI JSON Mode](https://developers.cloudflare.com/workers-ai/features/json-mode/). The adapters don't add SDK dependencies or retry behavior.

## Live enablement and strict-free preflight

`GROQ_ADAPTER_ENABLED` and `CLOUDFLARE_ADAPTER_ENABLED` default to `false`.
Enabling either adapter requires its API credential, selected model, verified
free-tier eligibility, privacy approval, and a non-empty preflight reference.
The reference should identify a dated record for the same account and model.
That record needs to show current account/tier eligibility, cost behavior,
provider data-use suitability, and the supported request/terminal/usage
behavior. `GROQ_PRIVACY_MAX_SENSITIVITY` and
`CLOUDFLARE_PRIVACY_MAX_SENSITIVITY` record the approved sensitivity ceiling
for that configured account/model. Dispatch rejects an effective request
sensitivity above the ceiling before transport; the ceiling defaults to
`public`. The configured exact response-model aliases are part of that same
preflight and have no effect on the request model sent to the provider.

`CLOUDFLARE_FREE_TIER_VERIFIED` specifically attests that the selected model is
available to the account's free tier without a paid billing method or prepaid
credits. Cloudflare's live model eligibility changes over time, so no model
catalog or paid-model list is hard-coded. Check the current [Workers AI pricing
and model billing requirements](https://developers.cloudflare.com/workers-ai/platform/pricing/)
as part of each preflight.

Structured generation is a separate declared capability. It is available only
when `GROQ_STRUCTURED_OUTPUT_VERIFIED` or
`CLOUDFLARE_STRUCTURED_OUTPUT_VERIFIED` confirms JSON Schema behavior for the
selected model. Setting the generic adapter-enable flag does not grant this
capability.

No provider account/tier, model, privacy, or live compatibility checks were
performed for this implementation. The committed example leaves all new gates
off. Offline HTTPX fixtures use synthetic credentials and never call paid
endpoints. Free-tier and privacy booleans are operator attestations, not an
automated account-discovery service; the Phase 18 registry remains future work.

## Current application boundary

The application continues to construct Gemini generation, counting, summaries,
and memory capabilities. Groq and Cloudflare adapters expose generation and
structured generation only; they do not implement endpoint-authoritative token
counting or embeddings. Current chat and standalone task preparation require an
authoritative count from the same provider/model/serializer as generation, so
the new adapters are not wired into those workflows. This preserves the Phase
16 admission rule and prevents an adapter flag from silently sending current
application traffic to a different endpoint.

## Future-provider extension

The explicit `build_generation_adapter` constructor accepts the three reference
adapter IDs and is not a router or a discovery surface. A future adapter should
keep transport and provider types inside `personal_ai.llm`, declare only
verified capabilities, include deterministic transport-contract coverage, add
account/model cost and privacy preflight, and record safe identity/usage
metadata. A future provider may be added to the constructor without changing
context or domain control flow. No quality benchmarking, quota-aware selection,
cascades, provider marketplace, or fourth live adapter is part of Phase 17.
