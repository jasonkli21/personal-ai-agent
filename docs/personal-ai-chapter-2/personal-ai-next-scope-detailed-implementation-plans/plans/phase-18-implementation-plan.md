# Phase 18 implementation plan — Endpoint registry and strict-free eligibility

Renumbered from former Phase 10 with scope preserved. The Phase 18 phase-local registry/admission implementation is complete after the [Phase 17R LiteLLM reconciliation gate](phase-17r-implementation-plan.md). Full Phase 18 integration acceptance remains open: Phase 15 is still partial, the Phase 18 Postgres migration has not been applied, and Postgres integration verification has not run. Do not connect this registry to request-workflow provider selection until Phase 15 authorization/membership and revocation prerequisites are accepted. See the [Phase 18 implementation evidence](../../phase-18-implementation-evidence.md) for delivered behavior and remaining gates.

## Scope boundary

**Goal:** Describe callable endpoint capability, privacy, and free eligibility independently of routing preference.

### Normative commitments

- Define versioned endpoint-profile facts and keep model, provider, endpoint, credential/account, and cost/billing identity distinct.
- Represent enabled/strict-free eligibility, capabilities, context/output limits, provider data policy, endpoint-specific count compatibility/confidence, and typed quota-bucket membership/reset metadata.
- Add initial profiles for configured Gemini free-tier, Groq Free-plan, and Cloudflare Workers Free endpoints.
- Add a deterministic strict-free admission guard.

### Phase acceptance criteria

- Paid/ineligible endpoints cannot enter strict-free candidate sets.
- Unknown data policy can conservatively exclude sensitive use.
- Current quota numbers are not application constants.
- A logical model exposed through different endpoint/account/credential/cost combinations yields distinct profiles and eligibility while profiles may reference the same verified quota-authority bucket.
- Every required input-count operation has an approved endpoint/serializer/counter mapping; generation-only Groq/Cloudflare profiles without authoritative counters cannot enter tasks that require them.

### Explicitly out of scope

- routing scores or provider/model priority chains;
- provider benchmarking;
- automatic quota scarcity policy;
- paid fallback or live BYOK execution;
- mirroring LiteLLM's model catalog or adding dynamic provider discovery.

## Current state and reuse

`AI_MODEL` and fixed Gemini budgets remain the active application configuration. The local endpoint registry and strict-free eligibility guard are implemented, but request workflows do not yet use them for provider selection. They reuse the neutral inference boundary and the implemented LiteLLM-backed gateway. Persist registry facts, where durable, under Phase 10's Postgres ownership. The Personal AI registry describes semantic endpoint and policy facts; LiteLLM model names remain execution metadata.

## Phase 10 storage dependency

Registry policy/version records use Phase 10 ownership and do not duplicate canonical state across stores. No secrets enter endpoint profiles.

## Prerequisites and work ordering

Required phases for full integration acceptance: 15, 17R, and 10. Phase 17R itself requires Phases 16 and 17. The Phase 15 policy/sensitivity subset already consumed by the phase-local registry does not establish completion of Phase 15's authoritative membership and end-to-end revocation work; those remain hard prerequisites before routing is connected to request workflows. Work packages run in order.

## Phase-specific invariants

- Volatile pricing/quota/model availability is not hard-coded into business logic.
- Eligibility is endpoint-, credential-, and account/tier-specific, not provider-wide.
- The Personal AI registry is not a mirror of LiteLLM's model catalog.
- One logical model may correspond to multiple callable endpoints; a free credential and a BYOK credential for the same provider/model are different choices.
- Profiles contain no secrets. `STRICT_FREE`, `EXPLICIT_BYOK`, and `CHATGPT_PLAN` remain separate, and free exhaustion cannot select paid/BYOK capacity.
- Registry returns endpoint facts and eligible/rejected candidates, not preference scores. Semantic selection belongs to Phase 21.

## Work packages

### P18.0 — Versioned endpoint profiles

Define a versioned `EndpointProfile` (or repository-equivalent) whose routable unit describes the callable combination: provider, logical/underlying model, deployment/endpoint, safe credential source/scope, account/project/tier, execution mode, cost/billing classification, serializer/runtime identity where relevant, capabilities, context/output limits, privacy/data-use eligibility, approved counter identity/provenance/confidence/schema coverage, and references to all authoritative quota bucket IDs with unit/window/reset/source/confidence/freshness. Keep endpoint/credential attribution separate from quota-authority identity: distinct endpoint profiles can share one bucket, and credential rotation under the same quota authority does not reset it. Independently scoped accounts/modes never borrow capacity. If bucket membership is unknown or ambiguous, automatic strict-free admission excludes the endpoint unless a verified conservative shared bucket resolves it. Profile fields contain safe references and metadata only, never credentials.

Consume the [execution identity and cost modes](../../03-free-tier-inference-and-routing.md#execution-identity-and-cost-modes). BYOK-compatible metadata is representable without secrets or live BYOK execution. User-billed capacity is explicit-only initially; unknown cost cannot be verified free. No hosted vault is added.

**Acceptance:** Profiles encode versions, capabilities, count/embedding compatibility, quota-authority bucket relationships, and account-scoped facts without secrets. Two profiles for the same provider/model but different credential/account/cost scopes retain distinct attribution and privacy/eligibility facts while aggregating only when the authoritative quota bucket ID is the same.

### P18.1 — Strict-free admission

Filter by endpoint and account/tier and by required sensitivity/capability before dispatch. Admit only independently verified zero-cost eligible Gemini/Groq/Workers Free paths. Unknown eligibility or possible automatic paid overflow denies. Unknown quota or ambiguous bucket membership cannot justify a billable path or an invented independent capacity pool. A task's required pre-dispatch count confidence, exact counter/provider/model/serializer match, and structured-schema coverage are hard compatibility facts; candidates without them are excluded before disclosure. Embeddings/count/search auxiliaries receive their own endpoint eligibility and operation-specific quota-bucket checks. Phase 18 does not reserve or settle quota for physical sends; Phase 19 owns usage accounting, atomic reservation, and settlement.

The configured three are initial profiles, not an allowlist in generic admission. A synthetic verified-free endpoint passes the same fact-based guard; paid, unknown-cost, explicit-only, and sensitivity-ineligible variants fail. Future live enablement still requires independent preflight and evidence.

**Acceptance:** Paid/unknown-eligibility, sensitivity-ineligible, counter-incompatible, and quota-bucket-ambiguous paths cannot enter candidates or dispatch. A generation-capable profile without an approved authoritative counter is rejected for tasks that require authoritative counts.

### P18.2 — Profile lifecycle and candidate API

Seed only configured verified profiles, explicitly marking unavailable or unverified ones. Removing/updating profiles invalidates stale candidates; freeze registry version per decision and recheck eligibility at dispatch. The candidate API returns the complete endpoint fact/rejection set without scores and bounds each task/mode candidate set to 32; reject an over-limit profile configuration rather than silently returning a partial set. No ChatGPT-plan endpoint appears in automatic sets; its explicit-only metadata is extended in Phase 25.2.

**Acceptance:** Profile removal invalidates candidates, registry lookup does not introduce routing scores or provider-name ordering, and candidate overflow is rejected before strategy selection without truncation.

## Requirement coverage

| Requirement | Work packages |
| --- | --- |
| R18.1 versioned endpoint-profile schema | P18.0 |
| R18.2 enabled/strict-free flags | P18.0 |
| R18.3 capabilities/context/output limits | P18.0 |
| R18.4 provider data-policy metadata | P18.0 |
| R18.5 quota/reset metadata | P18.0 |
| R18.6 initial configured free profiles | P18.2 |
| R18.7 strict-free admission guard | P18.1 |

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only when this phase changes the truth of user-visible capabilities, architecture, tech stack, setup, deployment, provider support, or project status. Keep implementation details in `docs/`; if no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the phase-specific deterministic checks plus applicable backend/frontend tests, lint, type checks, and builds. Finish with `git diff --check`. External/provider/cloud checks are opt-in; skipped checks remain **unverified**, never passed. Record actual files/interfaces, tested revision/configuration, command results, disabled gates, and unresolved external checks in implementation evidence.
