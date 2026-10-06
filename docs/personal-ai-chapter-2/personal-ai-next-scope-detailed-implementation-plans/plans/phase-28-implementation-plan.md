# Phase 28 implementation plan — Finance integration

Renumbered from former Phase 20 with its high-sensitivity read-only and sidecar boundaries preserved.

## Scope boundary

**Goal:** Validate high-value structured state with stricter provenance, minimization, and provider policy.

### Normative commitments

- Start with read-only Finance providers.
- Distinguish observed/calculated/assumed/AI-interpreted data and use stricter provenance.
- Apply Finance-specific provider eligibility and allow no implicit mutation.
- Add read-only sidecar to portfolio/security/research views with narrow default scope.
- Make broader portfolio/account context an explicit visible inclusion choice.
- Preserve semantic labels in ContextPackage.
- Support Copy/save-as-draft/research-note only where domain policy permits.
- Do not execute trades or transactions from generic sidecar output.

### Acceptance criteria

Finance remains authoritative and ineligible endpoints never receive sensitive Finance context.

## Current state and reuse

No authoritative Finance app/provider is implemented in this repository. Reuse shared evidence/claims/decision/context contracts and add adapters only after the external Finance contract is pinned.

## Prerequisites

Required phases: 15, 21, 24; sidecar work additionally requires Phase 25.4. Phase 10 remains the storage foundation.

## Invariants

Narrow selected-security/account scope is default; no trade/transfer/order mutation path is reachable from generic inference; provider eligibility fails closed.

## Work packages

### P28.0 — Read-only Finance boundary

Pin Finance application/revision, member authorization, and bounded account/portfolio/security/research APIs. Expose minimal typed providers with observed/calculated/assumed/AI-interpreted labels, units/currency/as-of/source/calculation version, and unknown/conflict states. Never store authoritative account/portfolio snapshots as generic AI memory or invent currency conversions.

**Acceptance:** read-only fixtures preserve semantic/source/as-of labels and domain truth.

### P28.1 — Sensitive preparation and routing

Register strict field disclosure rules, narrow windows/entity scope, and eligible-provider policy. Explicit ChatGPT choice does not waive privacy. Include generation, counting, embeddings, summaries, artifacts, and history in disclosure checks. Reject when no authorized endpoint exists. Retained verbose artifacts default to minimal/no retention.

**Acceptance:** ineligible primary or auxiliary disclosures and implicit whole-portfolio context are denied.

### P28.2 — Read-only sidecar

After Phase 25.4, launch with narrow defaults and visible explicit broader inclusion. Preserve semantic labels in packages. Copy/save-as-draft/research-note only on non-authoritative approved surfaces; authoritative persisted actions require Phase 31. No trade/transfer/transaction endpoint is reachable.

**Acceptance:** sidecar cannot execute transactions or auto-save authoritative Finance state.

## Requirement coverage

All ten former Phase 20 commitments remain represented across P28.0–P28.2.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
