# Phase 18 implementation plan — Endpoint registry and strict-free eligibility

Renumbered from former Phase 10 with scope preserved. Phase 10 persistence remains a standing prerequisite. Phase 18 must follow the [Phase 17R LiteLLM reconciliation gate](phase-17r-implementation-plan.md); it cannot proceed directly from Phase 17.

## Scope boundary

**Goal:** Describe callable endpoint capability, privacy, and free eligibility independently of routing preference.

### Normative commitments

- Define versioned endpoint-profile facts and keep model, provider, endpoint, credential/account, and cost/billing identity distinct.
- Represent enabled/strict-free eligibility, capabilities, context/output limits, provider data policy, and typed quota/reset metadata.
- Add initial profiles for configured Gemini free-tier, Groq Free-plan, and Cloudflare Workers Free endpoints.
- Add a deterministic strict-free admission guard.

### Phase acceptance criteria

- Paid/ineligible endpoints cannot enter strict-free candidate sets.
- Unknown data policy can conservatively exclude sensitive use.
- Current quota numbers are not application constants.
- A logical model exposed through different endpoint/account/credential/cost combinations yields distinct profiles and eligibility.

### Explicitly out of scope

- routing scores or provider/model priority chains;
- provider benchmarking;
- automatic quota scarcity policy;
- paid fallback or live BYOK execution;
- mirroring LiteLLM's model catalog or adding dynamic provider discovery.

## Current state and reuse

`AI_MODEL` and fixed Gemini budgets are configuration; no endpoint registry or strict-free eligibility guard exists. Reuse the neutral inference boundary and the LiteLLM-backed gateway planned by Phase 17R. Persist registry facts, where durable, under Phase 10's Postgres ownership. The Personal AI registry describes semantic endpoint and policy facts; LiteLLM model names remain execution metadata.

## Phase 10 storage dependency

Registry policy/version records use Phase 10 ownership and do not duplicate canonical state across stores. No secrets enter endpoint profiles.

## Prerequisites and work ordering

Required phases: 15, 17R, and 10. Phase 17R itself requires Phases 16 and 17. Work packages run in order.

## Phase-specific invariants

- Volatile pricing/quota/model availability is not hard-coded into business logic.
- Eligibility is endpoint-, credential-, and account/tier-specific, not provider-wide.
- The Personal AI registry is not a mirror of LiteLLM's model catalog.
- One logical model may correspond to multiple callable endpoints; a free credential and a BYOK credential for the same provider/model are different choices.
- Profiles contain no secrets. `STRICT_FREE`, `EXPLICIT_BYOK`, and `CHATGPT_PLAN` remain separate, and free exhaustion cannot select paid/BYOK capacity.
- Registry returns endpoint facts and eligible/rejected candidates, not preference scores. Semantic selection belongs to Phase 21.

## Work packages

### P18.0 — Versioned endpoint profiles

Define a versioned `EndpointProfile` (or repository-equivalent) whose routable unit describes the callable combination: provider, logical/underlying model, deployment/endpoint, safe credential source/scope, account/project/tier, execution mode, cost/billing classification, serializer/runtime identity where relevant, capabilities, context/output limits, privacy/data-use eligibility, and quota unit/window/reset/source/confidence/freshness. Keep these concepts separately addressable rather than flattening provider and model into one identity. Profile fields contain safe references and metadata only, never credentials.

Consume the [execution identity and cost modes](../../03-free-tier-inference-and-routing.md#execution-identity-and-cost-modes). BYOK-compatible metadata is representable without secrets or live BYOK execution. User-billed capacity is explicit-only initially; unknown cost cannot be verified free. No hosted vault is added.

**Acceptance:** Profiles encode versions, capabilities, count/embedding compatibility, and account-scoped facts without secrets. Two profiles for the same provider/model but different credential/account/cost scopes retain separate quota, privacy, and eligibility facts.

### P18.1 — Strict-free admission

Filter by endpoint and account/tier and by required sensitivity/capability before dispatch. Admit only independently verified zero-cost eligible Gemini/Groq/Workers Free paths. Unknown eligibility or possible automatic paid overflow denies. Unknown quota remains unknown and cannot justify a billable path. Embeddings/count/search auxiliaries receive their own endpoint eligibility admission.

The configured three are initial profiles, not an allowlist in generic admission. A synthetic verified-free endpoint passes the same fact-based guard; paid, unknown-cost, explicit-only, and sensitivity-ineligible variants fail. Future live enablement still requires independent preflight and evidence.

**Acceptance:** Paid/unknown-eligibility and sensitivity-ineligible paths cannot enter candidates or dispatch.

### P18.2 — Profile lifecycle and candidate API

Seed only configured verified profiles, explicitly marking unavailable or unverified ones. Removing/updating profiles invalidates stale candidates; freeze registry version per decision and recheck eligibility at dispatch. The candidate API returns facts and rejection reasons without scores. No ChatGPT-plan endpoint appears in automatic sets; its explicit-only metadata is extended in Phase 25.2.

**Acceptance:** Profile removal invalidates candidates, and registry lookup does not introduce routing scores or provider-name ordering.

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
