# Phase 28 implementation plan — Integrated evaluation and hardening

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Validate the complete multi-app, multi-provider, two-tier-storage platform.

### Normative commitments from the integrated roadmap

- Evaluate app/workspace isolation, context relevance/omission, provenance, authority confusion, mutation safety, strict-free enforcement, provider failure handling, quota exhaustion, cascade correctness, sensitive routing, Firestore/GCS growth and retention, artifact authorization, deletion/export propagation, and provider removal/change.
- Add ChatGPT hardening for credential absence, bridge caller security, revoked/expired auth, account switching, model disappearance, consent/ineligibility/usage limits, interrupted streams, explicit-only routing, explicit provider switching, domain context minimization, provider attribution, and Copy/Insert/Apply boundaries.

### Phase acceptance criteria

- No known cross-app isolation failure.
- No known paid-overflow path.
- No sensitivity-unsafe fallback.
- No public/unauthorized artifact path.
- Firestore does not retain avoidable bulky raw evaluation/trace data.
- Provider failures degrade explicitly.
- Regression suites cover quality and resource behavior.

### Explicitly out of scope

- new domain features
- new provider families
- major architecture rewrites
- claims of regulatory compliance

## Current state and reuse

Established fake evaluations and partial existing Phase 9 release safeguards are reusable. Integrated matrix, physical account deletion, full owner migration and operational/provider/cloud closeout remain incomplete.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/evaluation/context.py`
- `backend/src/personal_ai/evaluation/memory.py`
- `backend/src/personal_ai/evaluation/memory_lifecycle.py`
- `backend/src/personal_ai/evaluation/research.py`
- `backend/src/personal_ai/evaluation/decision.py`
- `backend/src/personal_ai/evaluation/domain.py`
- `backend/src/personal_ai/evaluation/iterative_research.py`
- `backend/src/personal_ai/evaluation/itinerary_proposals.py`
- `backend/src/personal_ai/auth/account_data.py`
- `backend/src/personal_ai/auth/owner_data.py`
- `backend/src/personal_ai/auth/safeguards.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 12, 17.4, 22, 23, 24, 25, 26, 27. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Cloud/provider/emulator checks remain opt-in and must be reported separately from offline deterministic results.
- Strict-$0 guardrails cover supporting GCP infrastructure as well as model inference.
- Security/privacy failures block release rather than being papered over with a feature flag.

## Work packages

### P28.0 — Integrated negative and quality matrix

**Depends on:** required phases above.

Exercise all app/workspace isolation, relevance/omission, provenance/authority confusion, mutation confirmation/idempotency, sensitivity-preserving routing/fallback/cascades, strict-free exhaustion and Gemini/Groq/Cloudflare changes/removal. Include Firestore/GCS growth, retention, authorization, required/optional artifact failure and export/deletion propagation. Establish held-out quality/resource thresholds and independent offline versus external evidence. Add itinerary-proposal evaluation to CI if still absent; the Make target currently exists but CI does not run it.

**Acceptance:** Integrated fixtures cover every required domain/provider/storage/permission/mutation/resource boundary and include the itinerary-eval CI gap.

### P28.1 — Close existing operational obligations

**Depends on:** P28.0.

Extend `backend/scripts/migrate_local_owner.py` using its current chat-only safety refusals, plus `auth/account_data.py` and `auth/owner_data.py`. Use existing Phase 9 plan/evidence/release checklist as the owner of legacy owner migration and account physical-deletion/recovery work, updating its evidence rather than marking duplicate phases complete. Implement missing lifecycle propagation across messages/summaries/vector memories/derived/jobs/evidence/decisions/proposals/account metadata and Phase 12 artifacts as required by that contract; preserve explicitly justified bounded replay/audit tombstones and explain them. Verify provider accounting coverage from 11 and strict-$0 deployment after removing unconditional paid TTL/other forbidden features. Review IAM/service tokens, secrets, telemetry, backup/restore and resource admission before release.

**Acceptance:** Existing Phase 9 migration/deletion/accounting/recovery obligations have truthful completion evidence or remain explicit release blockers.

### P28.2 — ChatGPT/domain safety and release

**Depends on:** P28.1.

Test credential absence, exact bridge callers, auth/account changes, missing models/scopes/eligibility/usage, interrupted completion, explicit-only lane, no silent billing/provider switch, context minimization/revocation and Copy/Insert/Apply boundaries across domains. Check distribution approval, plan-only billing and transport on supported clients before promoting their gates. Required release checks cannot be waived by turning a flag off and calling them passed; affected capability remains unavailable and verification gaps explicit. No new domain/provider product scope.

**Acceptance:** ChatGPT and domain clients cannot be promoted with failed eligibility, billing, caller, privacy or mutation checks.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R28.1: Evaluate app/workspace isolation, context relevance/omission, provenance, authority confusion, mutation safety, strict-free enforcement, provider failure handling, quota exhaustion, cascade correctness, sensitive routing, Firestore/GCS growth and retention, artifact authorization, deletion/export propagation, and provider removal/change. | P28.0 |
| R28.2: Add ChatGPT hardening for credential absence, bridge caller security, revoked/expired auth, account switching, model disappearance, consent/ineligibility/usage limits, interrupted streams, explicit-only routing, explicit provider switching, domain context minimization, provider attribution, and Copy/Insert/Apply boundaries. | P28.2 |

## Targeted verification and closeout

Run all established backend/frontend checks and eight evaluation targets, integrated fake storage/routing/bridge suites, negative scope/mutation/deletion tests and deploy syntax if changed. Add and document any new phase-specific runner before listing it as executable.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make memory-eval`, `make memory-lifecycle-eval`, `make research-eval`, `make decision-eval`, `make domain-eval`, `make iterative-research-eval`, `make itinerary-proposal-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Firestore Emulator, live provider/auth, deployed Google IAM/private API/worker, GCS deletion/IAM, strict-$0 account controls, restore and mounted browser/native/domain acceptance are opt-in release gates with separately recorded revision/config/result. Skipped is unverified.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
