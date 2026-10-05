# Phase 20 implementation plan — Finance integration

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Validate high-value structured state with stricter privacy/provider policy.

### Normative commitments from the integrated roadmap

- Start with read-only Finance providers.
- Distinguish observed/calculated/assumed/AI-interpreted data.
- Use stricter provenance.
- Apply Finance-specific provider eligibility.
- Allow no implicit mutation.
- Add read-only sidecar to portfolio/security/research views with narrow default scope.
- Make broader portfolio/account context an explicit visible inclusion choice.
- Preserve semantic labels in ContextPackage.
- Support Copy/save-as-draft/research-note only where domain policy permits.
- Do not execute trades or transactions from generic sidecar output.

### Phase acceptance criteria

- Finance remains authoritative.
- Ineligible free providers never receive sensitive Finance context.

### Explicitly out of scope

- transaction execution
- portfolio ownership in Personal AI
- implicit whole-portfolio disclosure
- new financial advice product scope

## Current state and reuse

No Finance application/provider exists here. Shared evidence, typed claims and hard-constraint patterns are reusable; domain adapters are future, with files chosen after the external contract is known.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/domains/contracts.py`
- `backend/src/personal_ai/domains/registry.py`
- `backend/src/personal_ai/decisions/contracts.py`
- `backend/src/personal_ai/evidence/contracts.py`
- `backend/src/personal_ai/context/contracts.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 7, 13, 16. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

**Conditional prerequisite:** additive sidecar integration consumes Phase 17.4. Baseline domain/backend work does not depend on live ChatGPT approval. Keep blocked sidecar work explicitly pending; do not declare the entire phase complete while any intended package is pending.

## Phase-specific invariants

- Narrow selected-security/account scope is the default.
- No trade/transfer/order mutation path may be reachable from generic inference.
- Sensitive provider eligibility fails closed.

## Work packages

### P20.0 — Read-only Finance boundary

**Depends on:** required phases above.

Pin Finance application/revision, verified member authorization and bounded account/portfolio/security/research read APIs. Add minimal typed providers with observed/calculated/assumed/AI-interpreted semantic labels, units/currency/as-of/source/calculation version and unknown/conflict states. Do not persist authoritative account/portfolio snapshots as AI memory or invent currency conversions.

**Acceptance:** Read-only Finance fixtures preserve semantic/source/as-of labels and never fabricate conversions or domain truth.

### P20.1 — Sensitive preparation and routing

**Depends on:** P20.0.

Register Finance fields with strict disclosure rules, narrow entity/time windows and eligible provider policy. Reject when no permitted free/explicit endpoint exists; explicit plan choice does not waive privacy. Include query embedding, counting, summaries, artifacts and later history in disclosure checks. Measure source correctness/authority confusion and minimization with synthetic fixtures; retained verbose artifacts default minimal/no retention.

**Acceptance:** Ineligible generation and auxiliary disclosures are denied, including implicit whole-portfolio context.

### P20.2 — Read-only sidecar

**Depends on:** P20.1 and Phase 17.4 for sidecar work.

After 17.4, launch on portfolio/security/research views with narrow defaults and visible explicit broader inclusion. Preserve semantic labels in ContextPackage. Copy/save-as-draft/research-note only on approved non-authoritative surfaces; a domain-owned persisted note with authoritative effects uses Phase 23. No trades, transfers or transaction endpoint from generic output. Keep ChatGPT-dependent hooks pending independently of baseline read contracts.

**Acceptance:** Narrow shared sidecar cannot reach trades/transactions or auto-save authoritative state.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R20.1: Start with read-only Finance providers. | P20.0 |
| R20.2: Distinguish observed/calculated/assumed/AI-interpreted data. | P20.0 |
| R20.3: Use stricter provenance. | P20.0 |
| R20.4: Apply Finance-specific provider eligibility. | P20.1 |
| R20.5: Allow no implicit mutation. | P20.1 |
| R20.6: Add read-only sidecar to portfolio/security/research views with narrow default scope. | P20.2 |
| R20.7: Make broader portfolio/account context an explicit visible inclusion choice. | P20.2 |
| R20.8: Preserve semantic labels in ContextPackage. | P20.0 |
| R20.9: Support Copy/save-as-draft/research-note only where domain policy permits. | P20.2 |
| R20.10: Do not execute trades or transactions from generic sidecar output. | P20.2 |

## Targeted verification and closeout

Test exact permitted fields, whole-portfolio denial, label preservation, stale/as-of provenance, ineligible provider/counter/embedding, mixed sensitivity, artifact redaction and no transaction/write capability.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make decision-eval`, `make domain-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Finance repository/auth/data-use contracts and actual private-data readiness remain external blockers; do not infer compliance or financial-data permission from local tests.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
