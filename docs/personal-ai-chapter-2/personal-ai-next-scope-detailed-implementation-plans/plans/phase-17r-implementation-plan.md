# Phase 17R implementation plan — LiteLLM execution substrate reconciliation

This is a planned reconciliation gate after completed Phase 17 and before Phase 18. It does not claim that LiteLLM is installed or implemented. Read the [provider-neutral Phase 16 plan](phase-16-implementation-plan.md), the [completed Phase 17 plan](phase-17-implementation-plan.md) and [evidence](../../phase-17-implementation-evidence.md), the [target architecture](../../02-target-architecture.md#9-provider-runtime), the [inference and routing contract](../../03-free-tier-inference-and-routing.md), and the [shared execution contract](../execution-contract.md) first.

## Scope boundary

**Goal:** Adopt the LiteLLM Python SDK as the default provider-transport normalization layer behind Personal AI's existing neutral inference contracts, prove parity against Phase 17 behavior, and retire redundant custom transport code where safe.

Personal AI decides **what and where** to execute. LiteLLM handles **how** to execute the already-selected endpoint. Personal AI's neutral contracts remain authoritative; LiteLLM types must not cross the inference gateway.

### Explicitly out of scope

- LiteLLM Proxy/Gateway deployment;
- LiteLLM Router as the semantic provider/model router;
- cross-provider/model fallback, load balancing, task-quality or scarcity routing, or cascades in LiteLLM;
- OpenRouter integration, BYOK dispatch, paid fallback, or automatic budgeted spending;
- changing Phase 16 contracts, persistence schemas, or application/domain/context callers;
- deleting Phase 17 implementations before parity is demonstrated.

## Prerequisites and work ordering

Required phases: 16, 17, and 10. Phase 18 is not a prerequisite. Work packages run in order so each provider migration is checked against the same Personal AI contract before duplicate transport code is retired.

## Work packages

### P17R.0 — Dependency and gateway boundary

Plan a pinned LiteLLM Python SDK dependency in the existing runtime, with an explicit upgrade review/version-pinning discipline. Define or extend a Personal AI inference gateway that maps neutral generation, streaming, structured-output, counting, embedding, usage, cancellation, status/error, sensitivity, execution identity, and embedding-space contracts to/from LiteLLM. Provider SDK objects, LiteLLM request/response types, and serialization remain inside this execution layer. Do not deploy LiteLLM Proxy/Gateway; reconsider that only after a demonstrated multi-service/shared-governance need.

**Acceptance:** Higher-level callers continue to depend only on Personal AI contracts; no LiteLLM types escape the gateway, and no runtime proxy service is introduced.

### P17R.1 — Migrate the selected providers in order

Migrate through the gateway in this order:

1. Gemini, preserving the currently active behavior;
2. Groq;
3. Cloudflare Workers AI.

Use explicit endpoint configuration for the already-selected provider/model/endpoint. Do not add OpenRouter in this phase. Keep account/tier, credential reference/scope, cost, privacy, capability, and eligibility facts in Personal AI policy/profile inputs, not in transport-library defaults.

**Acceptance:** Each provider passes the applicable neutral-contract parity suite before its prior transport implementation is reduced or removed.

### P17R.2 — Preserve Personal AI semantic ownership

Personal AI continues to own privacy and sensitivity admission, strict-free and execution-mode policy, endpoint selection, task-quality evidence, quota semantics, cross-provider cascades, and future adaptive routing. Do not enable LiteLLM semantic Router, automatic cross-endpoint fallback, or load balancing. Permit only a narrowly configured retry of the same already-selected endpoint when the operation is safe to retry and the request outcome is known; uncertain outcomes and side-effecting operations keep their existing no-implicit-retry semantics. A transport retry must not change provider, model, endpoint, credential scope, cost mode, or consent.

**Acceptance:** A transport failure cannot silently select a different semantic endpoint or execution mode; any same-endpoint retry is bounded and represented in invocation lineage.

### P17R.3 — Contract parity and retained guards

Use Phase 17 contracts, tests, and documented invariants as the parity oracle. Preserve Personal AI guarantees for privacy/sensitivity admission, endpoint/model provenance, bounded output, terminal/cancellation semantics, required usage metadata, safe error normalization, embedding-space identity, and deterministic failure when required invariants cannot be established. Retain tests of Personal AI behavior; replace provider-wire-specific tests with neutral contract checks when LiteLLM owns that wire behavior. Do not treat LiteLLM's internal tests as proof of Personal AI contract compliance.

**Acceptance:** Gemini remains compatible with active behavior; Groq and Cloudflare satisfy their supported neutral contracts; unsupported capabilities fail explicitly; all required Personal AI guards remain covered.

### P17R.4 — Retire duplicate transports after parity

After the relevant parity checks pass, remove or reduce custom OpenAI-compatible HTTP/SSE plumbing, Groq transport code, Cloudflare transport code, and Gemini SDK/transport code that LiteLLM replaces. Keep only minimal provider-specific shims for a demonstrated compatibility gap, with a documented contract-level reason and bounded scope. Do not retain permanent parallel transports solely as a precaution.

**Acceptance:** Redundant provider transport code is retired only after parity; any remaining provider-specific code identifies the LiteLLM gap it covers.

### P17R.5 — Preserve count confidence and provenance

LiteLLM does not by itself establish authoritative pre-dispatch token counting. Preserve typed distinctions for authoritative provider counts, genuinely exact local/model-tokenizer counts, conservative estimates, and unknown counts, using existing repository names where available. Keep source/confidence attached to the count and apply task-specific confidence requirements later. Do not turn unavailable provider counts into invented precision.

**Acceptance:** Count confidence and source remain explicit end to end, and an unsupported/unknown count cannot satisfy a task that requires stronger evidence.

## Phase 17R acceptance criteria

- Gemini active behavior remains contract-compatible.
- Groq and Cloudflare pass relevant neutral-contract/parity checks.
- LiteLLM SDK types remain below the Personal AI inference gateway.
- Personal AI owns privacy, admission, semantic routing, cost modes, quota, evaluation, and cascades.
- LiteLLM Router cannot silently choose an alternate semantic endpoint.
- Redundant transports are retired after parity; demonstrated gaps are the only reason to retain provider-specific shims.
- No OpenRouter dependency, paid fallback, BYOK dispatch, or LiteLLM Proxy/Gateway is introduced.
- Phase 17 remains completed history; this gate is complete only after its own implementation evidence and acceptance are recorded.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if the implemented migration changes user-visible provider support, architecture, technology stack, prerequisites, local setup, cloud deployment, or current status. Do not describe LiteLLM as implemented before the migration is complete. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

The implementing phase must run neutral-contract parity checks, applicable backend tests/lint/type checks/build checks, and `git diff --check`. Use deterministic fakes offline; live provider compatibility, account/tier eligibility, privacy suitability, strict-free behavior, and paid-path behavior require separate evidence. Skipped external checks remain unverified. Record the tested revision, pinned LiteLLM version, providers migrated, tests/results, disabled gates, any retained shim and its demonstrated gap, and unresolved external checks in implementation evidence.
