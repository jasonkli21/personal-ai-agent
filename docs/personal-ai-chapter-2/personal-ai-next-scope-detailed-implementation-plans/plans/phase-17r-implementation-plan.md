# Phase 17R implementation plan — LiteLLM execution substrate reconciliation

Phase 17R is implemented locally as the LiteLLM transport reconciliation gate after completed Phase 17 and before Phase 18. See the [Phase 17R implementation evidence](../../phase-17r-implementation-evidence.md) for the tested revision and remaining live-provider gates. This status covers local implementation; it does not establish live provider, account/tier, privacy, cloud, or production acceptance. Read the [provider-neutral Phase 16 plan](phase-16-implementation-plan.md), the [completed Phase 17 plan](phase-17-implementation-plan.md) and [evidence](../../phase-17-implementation-evidence.md), the [target architecture](../../02-target-architecture.md#9-provider-runtime), the [inference and routing contract](../../03-free-tier-inference-and-routing.md), and the [shared execution contract](../execution-contract.md) first.

## Scope boundary

**Goal:** Adopt the LiteLLM Python SDK as the default provider-transport normalization layer behind Personal AI's existing neutral inference contracts, prove parity against Phase 17 behavior, and retire redundant custom transport code where safe. This gate preserves the current provider-authoritative counting requirement; it does not by itself make Groq or Cloudflare eligible for current application workflows.

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

The implemented gateway uses a pinned LiteLLM Python SDK with explicit upgrade review/version-pinning discipline. It maps neutral generation, streaming, structured-output, counting, embedding, usage, cancellation, status/error, sensitivity, execution identity, and embedding-space contracts to/from LiteLLM. Provider SDK objects, LiteLLM request/response types, and serialization stay inside this execution layer. Bind provider/base endpoint, model, credential reference, and account scope explicitly per invocation; do not mutate shared environment/global credential state to choose an account. Disable content logging, external content callbacks, and content caches unless a separately authorized policy permits them. Any allowed hook is metadata-only and explicitly configured. Sanitize SDK exceptions/debug output so prompts, responses, and secrets cannot enter logs or safe error metadata. Required capability, structured-output, and bounded-request parameters must survive mapping; reject unsupported parameters instead of dropping them. Concrete SDK settings are pinned-version-specific, not a stable contract. Do not deploy LiteLLM Proxy/Gateway; reconsider that only after a demonstrated multi-service/shared-governance need.

**Acceptance:** Higher-level callers continue to depend only on Personal AI contracts; no LiteLLM types escape the gateway, and no runtime proxy service is introduced. Synthetic concurrent calls for one model under different account credentials remain isolated; ambient keys/global hooks cannot change the approved endpoint; prompt/response/secret canaries do not appear in logs, callbacks, caches, or safe errors; unsupported required parameters fail closed.

### P17R.1 — Migrate the selected providers in order

Migrate through the gateway in this order:

1. Gemini, preserving the currently active behavior;
2. Groq;
3. Cloudflare Workers AI.

Use explicit endpoint configuration for the already-selected provider/model/endpoint. Do not add OpenRouter in this phase. Keep account/tier, credential reference/scope, cost, privacy, capability, and eligibility facts in Personal AI policy/profile inputs, not in transport-library defaults.

**Acceptance:** Each provider passes both the neutral wrapper-contract checks and the pinned SDK execution/serialization checks with intercepted synthetic network responses before its prior transport implementation is reduced or removed. Explicit generation serialization must include the system instructions and any structured schema that the approved counter attests.

### P17R.2 — Preserve Personal AI semantic ownership

Personal AI continues to own privacy and sensitivity admission, strict-free and execution-mode policy, endpoint selection, task-quality evidence, quota semantics, cross-provider cascades, and future adaptive routing. Do not enable LiteLLM semantic Router, automatic cross-endpoint fallback, or load balancing. Configure LiteLLM, provider clients, and underlying HTTP clients for zero implicit retries in Phase 17R. This preserves current Phase 17 behavior and ensures one facade invocation cannot hide multiple provider sends. Do not retry a timeout/unknown outcome. A future explicit same-endpoint retry may be added only after Phase 19 assigns a distinct physical attempt identity and admission/reservation to every send; it cannot change provider, model, endpoint, credential scope, cost mode, or consent.

**Acceptance:** Intercepted synthetic 429, known failure, timeout, and unknown-outcome cases show at most one provider send per Phase 17R facade call; no SDK/provider/HTTP retry setting can multiply sends. Transport failure cannot silently select a different semantic endpoint or execution mode. Any later explicitly accounted retry is gated on the Phase 19 attempt contract.

### P17R.3 — Contract parity and retained guards

Inventory Phase 16/17 contracts, tests, and documented invariants before retiring transports. Require two complementary test layers: neutral wrapper fixtures and the pinned LiteLLM execution/serialization path with intercepted synthetic network responses. Preserve pre-parse completion/body/stream/event/line bounds, or document and test the smallest transport shim that enforces them before SDK parsing; keep an operation disabled if the pinned SDK cannot establish the bound. Preserve Personal AI guarantees for privacy/sensitivity admission, verified endpoint/model provenance, terminal/cancellation semantics, usage-source/confidence labels, safe error normalization, and embedding-space identity. SDK-synthesized identity is not verified provider-returned identity, and synthesized usage is not provider-reported usage. Structured-output requirements must survive serialization. Preserve the persisted embedding-space identity independently of LiteLLM labels, including model, dimensions, normalization, document/query task mapping, and version. Retain contract tests of Personal AI behavior; replace provider-wire tests only when the real SDK path covers their invariant. Do not treat LiteLLM's internal tests as proof of Personal AI contract compliance.

**Acceptance:** In addition to neutral wrapper fixtures, the pinned real SDK path proves oversized completion/stream/event inputs are stopped with bounded resources; missing, conflicting, or unapproved returned model identity and missing terminal status fail; provider-reported, synthesized, and unknown usage remain distinguishable; structured requirements survive transformation; embedding document/query tasks, dimensions, normalization, and the legacy logical space remain compatible. Gemini remains compatible with active behavior; unsupported capabilities fail explicitly; all required Personal AI guards remain covered. Live compatibility remains a separate opt-in gate.

### P17R.4 — Retire duplicate transports after parity

After the relevant parity checks pass, remove or reduce custom OpenAI-compatible HTTP/SSE plumbing, Groq transport code, Cloudflare transport code, and Gemini SDK/transport code that LiteLLM replaces. Keep only minimal provider-specific shims for a demonstrated compatibility gap, with a documented contract-level reason and bounded scope. Do not retain permanent parallel transports solely as a precaution.

**Acceptance:** Redundant provider transport code is retired only after parity; any remaining provider-specific code identifies the LiteLLM gap it covers.

### P17R.5 — Preserve count confidence and provenance

LiteLLM does not by itself establish authoritative pre-dispatch token counting. Preserve the current `TokenCount` contract: current callers require `kind=provider`, `confidence=authoritative`, and matching provider/model/serializer identity for the generation operation. `reported`, `estimated`, absent, or mismatched count metadata cannot satisfy those callers. The existing contract does not define an exact-local count kind; do not imply one is admitted by this transport migration. A later exact-local or otherwise relaxed count policy is outside Phase 17R and requires a separately authorized Phase 16 contract/caller-policy change with its own evidence gate; completed Phase 16 evidence is not rewritten to imply the relaxed policy was already delivered. Do not turn unavailable provider counts into invented precision.

The implementation completes this operation/counter compatibility matrix for the pinned SDK and tested serializer before marking a row supported:

| Operation/profile | Current generation/embedding identity | Approved pre-dispatch counter and provenance | Structured-schema coverage | Current caller dispatch |
| --- | --- | --- | --- | --- |
| Gemini bounded/streaming generation | `gemini` + configured model + `gemini-content-v1` | Gemini provider `countTokens`; `provider` / `authoritative`, exact provider/model/serializer match; LiteLLM-transformed request must be attested | The system instruction and serialized response schema must both be included in the counted request | Active workflows only after parity preserves this row |
| Gemini structured generation | Same Gemini identity | Same matching authoritative Gemini counter | Required schema must be counted and serialized without loss | Active only after schema-specific parity |
| Groq generation | `groq` + configured model + `groq-chat-completions-v1` | No approved same-endpoint authoritative counter today | No schema coverage can be inferred from generation support | No current task requiring authoritative counts may dispatch |
| Cloudflare Workers AI generation | `cloudflare_workers_ai` + configured model + `cloudflare-workers-ai-chat-v1` | No approved same-endpoint authoritative counter today | No schema coverage can be inferred from generation support | No current task requiring authoritative counts may dispatch |
| Gemini embeddings | Persisted logical space `google_genai`, configured model, dimensions, L2 normalization, document/query task, and space version | Not a generation-token-count operation | N/A | Preserve only with embedding-space parity; transport labels do not replace the persisted space |

**Acceptance:** The matrix records exact tested SDK/serializer/counter versions and request shape. Matching/mismatching identities are tested; schema-near-ceiling requests are rejected using a count that covers the schema; reported, estimated, absent, or unknown counts fail for current authoritative tasks; a generation-capable endpoint without an approved counter is excluded before disclosure. Evidence distinguishes transport migration from application eligibility. Groq and Cloudflare remain unavailable to tasks needing authoritative counts until this row is proven.

## Phase 17R acceptance criteria

- Gemini active behavior remains contract-compatible.
- Groq and Cloudflare pass relevant neutral-contract/parity checks.
- LiteLLM SDK types remain below the Personal AI inference gateway.
- Personal AI owns privacy, admission, semantic routing, cost modes, quota, evaluation, and cascades.
- LiteLLM Router cannot silently choose an alternate semantic endpoint.
- SDK/provider/HTTP implicit retries are zero until Phase 19 accounts for physical sends.
- SDK account/credential isolation, no-content-callback/cache/logging defaults, and safe error normalization are covered at the pinned version.
- The operation/counter matrix demonstrates exact transformed-request counting for eligible current callers; Groq/Cloudflare remain excluded where authoritative counts are missing.
- Wrapper fixtures and intercepted pinned-SDK execution/serialization tests preserve resource bounds, provenance, structured-output, usage-label, terminal, cancellation, and embedding-space invariants.
- Redundant transports are retired after parity; demonstrated gaps are the only reason to retain provider-specific shims.
- No OpenRouter dependency, paid fallback, BYOK dispatch, or LiteLLM Proxy/Gateway is introduced.
- Phase 17 remains completed history; this gate is complete only after its own implementation evidence and acceptance are recorded.

## README maintenance

The repository-root `README.md` and current-state docs describe the locally implemented migration. Keep that status scoped to the delivered transport boundary and local evidence; live provider support, account/tier eligibility, privacy, cloud deployment, and production readiness remain separate gates. Update those docs only when a verified user-visible capability or project status changes.

## Targeted verification and closeout

The implementing phase must run neutral-contract parity checks, applicable backend tests/lint/type checks/build checks, and `git diff --check`. Use deterministic fakes offline; live provider compatibility, account/tier eligibility, privacy suitability, strict-free behavior, and paid-path behavior require separate evidence. Skipped external checks remain unverified. Record the tested revision, pinned LiteLLM version, providers migrated, tests/results, disabled gates, any retained shim and its demonstrated gap, and unresolved external checks in implementation evidence.
