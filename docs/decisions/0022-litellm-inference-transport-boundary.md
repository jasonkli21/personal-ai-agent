# ADR 0022: Use LiteLLM beneath the Personal AI inference boundary

- Status: accepted; runtime adoption is planned in Phase 17R
- Date: 2026-10-08
- Refines: [ADR 0001](0001-llm-provider-boundary.md)

## Context

ADR 0001 established the durable principle that application code depends on an internal provider-neutral inference boundary. Phase 16 implemented broader neutral generation, streaming, structured-output, counting, usage, embedding, cancellation, and result contracts. Phase 17 then proved those contracts against Gemini, Groq, and Cloudflare with concrete adapters and documented provider-specific behavior.

The commodity work of normalizing provider transport, SDK differences, serialization, streaming, and transport errors can be delegated to LiteLLM while Personal AI keeps the policy and semantic decisions specific to this system. The change is planned after Phase 17; it does not rewrite Phase 17's history or claim that LiteLLM is currently installed or used.

## Decision

- Keep Personal AI's neutral inference contracts authoritative and application-facing.
- Prefer the LiteLLM Python SDK/library as the provider transport-normalization implementation beneath a Personal AI inference gateway, adopted through Phase 17R after contract parity is demonstrated.
- Keep all LiteLLM types below that gateway. Context, domain, and application code do not call LiteLLM directly.
- Personal AI owns endpoint profiles and eligibility, hard privacy/sensitivity and cost admission, semantic routing, quota accounting, task evaluation, cascades, and later adaptive routing.
- Do not introduce LiteLLM Proxy/Gateway initially. Reconsider only if a demonstrated later multi-service/shared-governance need justifies it.
- Do not allow LiteLLM Router or automatic cross-provider/model fallback/load balancing to silently make semantic endpoint decisions. Any permitted execution retry is bounded, repeats only the already-selected endpoint, and is safe for the operation.
- Keep provider-specific code only for demonstrated LiteLLM compatibility gaps.
- Pin and review LiteLLM upgrades deliberately, and protect the Personal AI contract with parity tests.

This ADR refines and supersedes only ADR 0001's transport-implementation strategy. ADR 0001's core decision—an internal provider-neutral inference boundary—is retained.

## Consequences

- Phase 17 remains completed reference/parity evidence; Phase 17R plans Gemini, Groq, and Cloudflare migration behind existing contracts.
- Model/provider/endpoint/account/credential/cost identities remain Personal AI profile and policy facts rather than a mirror of LiteLLM's catalog.
- Personal AI can replace or compare semantic routing strategies without changing provider transport or application/domain/context orchestration.
- Live provider parity, privacy suitability, strict-free eligibility, and deployment acceptance remain separate evidence gates; offline contract checks alone do not establish them.
