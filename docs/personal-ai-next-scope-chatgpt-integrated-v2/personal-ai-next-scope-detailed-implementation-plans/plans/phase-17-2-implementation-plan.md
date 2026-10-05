# Phase 17.2 implementation plan — ChatGPT provider/runtime integration, policy, and usage handling

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Represent ChatGPT-plan usage inside Personal AI while keeping it outside automatic strict-free routing and ordinary free-provider quota semantics.

### Normative commitments from the integrated roadmap

- Add/verify provider metadata for auth mode, selection mode, credential runtime, account-specific model discovery, automation eligibility, and hosted conversation-state availability.
- Define `openai_chatgpt_plan` as explicit-user and not an automatic candidate.
- Add request-envelope fields for explicit provider/model choice.
- Ensure explicit provider selection does not bypass context/sensitivity authorization.
- Persist only safe provider/model attribution on completed turns.
- Prove ChatGPT models can never enter a strict-free automatic candidate set.
- Track safe connection and normalized usage state.
- Record per-turn provider/model/latency/status/error metadata.
- Add manage-usage/reconnect/switch-account hooks.
- Never infer reset timestamps from generic usage-limit errors.
- Add redaction tests for auth/account material.

### Phase acceptance criteria

- Automatic strict-free routing remains Gemini/Groq/Cloudflare only.
- ChatGPT requests require explicit user/session/request selection.
- No silent fallback occurs in either direction.
- Provider/model attribution is preserved on conversation turns.
- ChatGPT failures produce actionable normalized states.
- The strict-free quota ledger remains semantically separate.
- No auth secret is emitted into tracing/evaluation artifacts.

### Explicitly out of scope

- sidecar UI implementation
- automatic ChatGPT routing
- quota reset prediction
- domain-specific sidecar behavior

## Current state and reuse

Safe automatic-provider attribution is delivered by 8/13 at this point. Explicit user lane policy, local usage state and external turn prepare/finalize are new.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/llm/client.py`
- `backend/src/personal_ai/api/schemas.py`
- `backend/src/personal_ai/api/dependencies.py`
- `backend/src/personal_ai/services/chat_turns.py`
- `backend/src/personal_ai/entities/conversation.py`
- `backend/src/personal_ai/storage/repositories.py`
- `backend/src/personal_ai/storage/firestore.py`
- `backend/src/personal_ai/auth/owner_data.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 11, 13, 17.1. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- A ChatGPT error never silently selects API-key billing, credits, another account, or an automatic free provider.
- Connection/usage state is deliberately coarser than the strict-free quota ledger.
- Provider sensitivity policy still applies after explicit selection.

## Work packages

### P17_2.0 — Explicit provider policy and usage state

**Depends on:** required phases above.

Extend Phase 10 profiles with auth mode, explicit selection, local credential runtime, account-model visibility, automation exclusion and no hosted conversation-state inheritance. Add non-secret request fields for provider/model/context selection. openai_chatgpt_plan never enters strict-free candidate/fallback/evaluation automation. Apply full source/provider sensitivity policy after user choice; no fallback in either direction without explicit new user action. Keep connected/disconnected/reauth/unavailable and coarse available/limit/unavailable/unknown usage separate from free-provider quota buckets.

**Acceptance:** Automatic candidate tests always exclude ChatGPT; explicit selection cannot bypass privacy or silently switch routes.

### P17_2.1 — Scoped external-turn prepare/finalize

**Depends on:** P17_2.0.

Extend existing chat service/branch transactions with one prepared turn, active-branch/source-grant snapshot, package fingerprint/expiry, bounded output, selected provider/model and durable idempotency. Finalize only the reserved owner/app/workspace/conversation branch, rechecking grants and terminal intent. Issue a short-lived verifiable dispatch grant bound to paired caller, package content hash, provider/model, sensitivity/policy versions and expiry; use the Phase 17.1 proof/verifier contract so the bridge rejects forged or edited browser manifests without receiving Google/IAM credentials. Context/model changes require fresh preparation. Duplicate completion replays; foreign/stale/expired/changed output fails safely. Interrupted output is transient or explicit labelled draft while safe failure metadata remains durable. No browser-asserted provider output can authorize a domain write or erase superseded messages.

**Acceptance:** Only a valid scoped active reservation can finalize, with idempotent replay and explicit expired/superseded failure.

### P17_2.2 — Attribution trust and recovery hooks

**Depends on:** P17_2.1.

Persist safe per-turn model/provider/task/latency/error/usage with client-reported versus server-observed provenance; never trust browser completion as verified provider billing or model proof. Reuse 8/13 metadata, do not create a second attribution store. Normalize usage-limit states without guessed resets; expose reconnect/manage-usage/switch-account hooks for 17.3. Clear transient state on account/scope change and never replace prior turn attribution.

**Acceptance:** Turn metadata distinguishes client reports from trusted observations; recovery uses coarse usage states without guessed resets.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R17.2.1: Add/verify provider metadata for auth mode, selection mode, credential runtime, account-specific model discovery, automation eligibility, and hosted conversation-state availability. | P17_2.0 |
| R17.2.2: Define `openai_chatgpt_plan` as explicit-user and not an automatic candidate. | P17_2.0 |
| R17.2.3: Add request-envelope fields for explicit provider/model choice. | P17_2.0 |
| R17.2.4: Ensure explicit provider selection does not bypass context/sensitivity authorization. | P17_2.0 |
| R17.2.5: Persist only safe provider/model attribution on completed turns. | P17_2.1 |
| R17.2.6: Prove ChatGPT models can never enter a strict-free automatic candidate set. | P17_2.0 |
| R17.2.7: Track safe connection and normalized usage state. | P17_2.0 |
| R17.2.8: Record per-turn provider/model/latency/status/error metadata. | P17_2.2 |
| R17.2.9: Add manage-usage/reconnect/switch-account hooks. | P17_2.2 |
| R17.2.10: Never infer reset timestamps from generic usage-limit errors. | P17_2.2 |
| R17.2.11: Add redaction tests for auth/account material. | P17_2.2 |

## Targeted verification and closeout

Test explicit-only candidate exclusion, both fallback directions, sensitivity denial before dispatch, branch changes/revocation before finalize, same-key replay/conflict, bounds/expiry, forged attribution/usage, disconnect recovery, safe failure metadata and token/account redaction.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Plan-only control and live bridge completion remain unverified until 17.1 compatibility gates pass.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
