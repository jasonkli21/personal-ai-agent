# Phase 18 implementation plan — Provider/model registry and strict-free eligibility

Renumbered from former Phase 10 with scope preserved. Phase 10 persistence is now a standing prerequisite and replaces obsolete Firestore infrastructure assumptions only; provider/model-registry scope is unchanged.

## Scope boundary

**Goal:** Describe endpoint capability/privacy/free eligibility independently of routing.

### Normative commitments
- Define model profile schema.
- Represent enabled/strict-free flags.
- Represent capabilities and context/output limits.
- Represent provider data-policy metadata.
- Represent quota/reset metadata.
- Add initial profiles for configured Gemini free-tier, Groq Free-plan, and Cloudflare Workers Free models.
- Add strict-free admission guard.

### Phase acceptance criteria
- Paid/ineligible endpoints cannot enter strict-free candidate sets.
- Unknown data policy can conservatively exclude sensitive use.
- Current quota numbers are not application constants.

### Explicitly out of scope
- routing scores
- provider benchmarking
- automatic quota scarcity policy
- paid fallback

## Current state and reuse
`AI_MODEL` and fixed Gemini budgets are configuration; no provider/model registry or strict-free eligibility guard exists at the pre-phase baseline. Reuse the neutral inference boundary, dependency wiring and settings; persistence of registry facts, where durable, follows Phase 10's Postgres ownership rather than Firestore.

## Prerequisites and work ordering
Required phases: 15 and 17 (former 7 and 9), plus standing Phase 10 persistence foundation.

## Phase-specific invariants
- Volatile pricing/quota/model availability is not hard-coded into business logic.
- Eligibility is model/account-specific, not provider-wide.
- Registry describes facts; Phase 21 routing owns selection policy.

## Work packages

### P18.0 — Versioned capability profiles
Add neutral endpoint profiles for enabled state, provider/model/serializer/counter, supported tasks/stream/structured/tools/vision as implemented, context/output limits, embedding compatibility, credential runtime/selection mode, account-tier identity, privacy/data-use, quota units/windows/reset provenance and fact freshness. Quotas/model lists remain configuration/operational observations, not hard-coded business constants.

Consume the [execution identity and cost modes](../../03-free-tier-inference-and-routing.md#execution-identity-and-cost-modes): distinguish provider, endpoint/model, credential source/reference/ownership, opaque account/project/tier, cost/billing-owner class, and automatic/explicit selection permission. Represent BYOK-compatible profiles without secrets or live BYOK execution. User-billed capacity is explicit-only initially; unknown cost cannot be verified free. No hosted vault is added.

**Acceptance:** Profiles encode versions, capabilities, count/embedding compatibility and account-scoped facts without secrets.

**Identity acceptance:** Two profiles for the same provider/model but different credential/account/cost scopes retain separate quotas, privacy facts, and eligibility. A configured BYOK profile is excluded from automatic candidates and cannot be enabled merely by free quota exhaustion.

### P18.1 — Strict-free admission
Filter by model AND account/tier and by required sensitivity/capability before dispatch. Verified zero-cost eligible Gemini/Groq/Workers Free paths only; unknown eligibility or possible automatic paid overflow denies. Unknown quota remains unknown but cannot justify a billable path. No credentials in profile IDs. Embeddings/count/search auxiliaries receive independent eligibility admission.

The configured three are initial profiles, not an allowlist baked into generic admission. An additional synthetic verified-free endpoint passes the same fact-based guard; paid, unknown-cost, and explicit-only variants fail. Future live enablement still requires independent preflight and evidence.

**Acceptance:** Paid/unknown-eligibility and sensitivity-ineligible paths cannot enter candidates or dispatch.

### P18.2 — Profile lifecycle and candidate API
Seed only configured verified profiles, explicitly marking unavailable or unverified ones. Removing/updating profiles invalidates stale candidates; freeze registry version per invocation and recheck eligibility at dispatch. Registry returns candidate facts, not scores. No ChatGPT candidate appears in automatic sets; its explicit-only metadata is extended in Phase 25.2.

**Acceptance:** Profile removal invalidates candidates, and registry lookup does not introduce routing scores.

## Requirement coverage
| Requirement | Work packages |
| --- | --- |
| R18.1 model profile schema | P18.0 |
| R18.2 enabled/strict-free flags | P18.0 |
| R18.3 capabilities/context/output limits | P18.0 |
| R18.4 provider data-policy metadata | P18.0 |
| R18.5 quota/reset metadata | P18.0 |
| R18.6 initial configured free profiles | P18.2 |
| R18.7 strict-free admission guard | P18.1 |
## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only when this phase changes the truth of user-visible capabilities, architecture, tech stack, setup, deployment, provider support, or project status. Keep implementation details in `docs/`; if no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the phase-specific deterministic tests plus applicable backend/frontend test, lint, typecheck and build checks. Finish with `git diff --check`. External/provider/cloud checks are opt-in and skipped checks remain **unverified**, never passed. Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation evidence.
