# Phase 17.1 implementation plan — ChatGPT authentication and local bridge

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Add the user-controlled execution boundary required for ChatGPT-plan usage without storing ChatGPT credentials in the managed Personal AI cloud backend.

### Normative commitments from the integrated roadmap

- Re-verify current Sign in with ChatGPT open-source/local-runtime requirements before implementation.
- Define `ChatGPTPlanBridge` / local-client contract using normalized Personal AI request/output types where practical.
- Implement supported OAuth/OIDC/PKCE registration/sign-in flow.
- Persist stable host/client registration metadata and credentials only in protected local/user-controlled storage.
- Validate ID token identity and required ChatGPT-plan usage scope.
- Implement token refresh, sign-out/disconnect, and revocation/recovery behavior.
- Implement account-specific model discovery.
- Implement direct Responses API streaming behind the bridge using current required request semantics.
- Normalize completed/incomplete/auth/eligibility/usage-limit errors.
- Add fake bridge and contract tests.
- Ensure the bridge never returns reusable OAuth tokens to browser/cloud callers.
- For hosted web integration, define loopback/local-IPC transport with origin allowlisting and anti-CSRF/request authorization.
- Treat native-mobile support as capability to verify rather than assuming desktop loopback mechanics.

### Phase acceptance criteria

- Eligible signed-in user can complete a streamed ChatGPT-plan request through the local/user-controlled runtime.
- No persistent ChatGPT credential appears in Firestore, GCS, Secret Manager, browser storage, logs, traces, analytics, or exports.
- Managed Cloud Run services can operate with zero knowledge of ChatGPT access/refresh tokens.
- Account model list is discovered rather than hard-coded.
- Existing Gemini behavior and Phase 8 neutral contracts remain functional.

### Explicitly out of scope

- automatic strict-free routing through ChatGPT
- OpenAI API-key billing fallback
- ChatGPT conversation-history import
- native-mobile credential design before capability verification

## Current state and reuse

The ChatGPT credential runtime, OAuth flow and discovery are missing. This is a new local runtime boundary; it is not a Cloud Run provider credential or the existing Google browser sign-in.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/llm/client.py`
- `backend/src/personal_ai/llm/errors.py`
- `backend/src/personal_ai/llm/fake.py`
- `backend/src/personal_ai/settings.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 8, 10. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Reusable credentials stay exclusively in protected user-controlled storage.
- Browser JavaScript and managed cloud services never receive access/refresh tokens.
- Treat preview/operational OpenAI requirements as revalidated configuration/compatibility facts, not permanent assumptions.

## Work packages

### P17_1.0 — Eligibility and transport decision

**Depends on:** required phases above.

Revalidate the dated SIWC snapshot in source 08 before live work. Classify hosted web plus installed bridge distribution and obtain any required approval; verify plan-only controls without silent credit use. Prototype supported loopback/local IPC with exact Origin/Host checks, pairing and expiring caller authorization, DNS-rebinding prevention and bounded streams. Browser compatibility/PNA/mixed-content and native mobile support are explicit external gates, not assumptions. No Google/IAM tokens are forwarded to bridge.

**Acceptance:** The distribution/transport/plan-only decision is documented; failed external gates leave live inference unavailable.

### P17_1.1 — Local identity and credential lifecycle

**Depends on:** P17_1.0.

Define future ChatGPTPlanBridge types using Phase 8 neutral records and an independently tested fake. Implement documented public-client OAuth/OIDC/PKCE with per-attempt state/nonce, validated issued client identity and granted plan-use scopes; stable host ID alone never authenticates a caller. Keep account/client/workspace registrations separate in protected local storage. Serialize rotating refresh, atomically replace credentials, stop on confirmed revocation, sign out/disconnect locally and distinguish unconfirmed remote revocation. Browser/cloud see only safe connection state. Define the package-bound dispatch-grant format, verifier and fake issuer here; Phase 17.2 consumes this contract to implement authenticated cloud issuance. Cloud ContextPackages are not enabled before that issuance exists. Synthetic native/provider compatibility checks in this subphase do not claim live cloud/private-domain integration.

**Acceptance:** OAuth and rotating refresh fixtures reject account/state/scope mismatches and expose no reusable tokens.

### P17_1.2 — Discovery and supported inference

**Depends on:** P17_1.1.

Discover account-specific models with supported models[]/visibility/display/slug semantics and refresh on account change. A versioned bridge serializer implements supported Responses fields, input/instructions and required HTTP non-persistence/streaming; reject unsupported fields/tools instead of forwarding the normal API body. Consume terminal completion, classify interrupted/auth/admission/eligibility/usage failures, and bound input/output bytes and total deadline. No max_output_tokens assumption, credits/API-key fallback, conversation import or implicit retry after uncertain dispatch.

**Acceptance:** Discovery and supported serialization handle terminal loss and usage/admission errors without billing fallback.

### P17_1.3 — Security and compatibility closeout

**Depends on:** P17_1.2.

Test the bridge/fake contract and synthetic auth transports independently of cloud services. Assert no token or authorization URL enters returned objects, browser storage, Firestore, GCS, Secret Manager, telemetry/export or committed fixtures. Document installation, pairing, lifecycle states, supported desktop transport and opt-in provider flow; mobile remains a capability check. Live eligibility failure leaves additive work pending rather than changing automatic providers.

**Acceptance:** Local-runtime tests and redaction scans cover every credential persistence/output path; skipped compatibility remains unverified.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R17.1.1: Re-verify current Sign in with ChatGPT open-source/local-runtime requirements before implementation. | P17_1.0 |
| R17.1.2: Define `ChatGPTPlanBridge` / local-client contract using normalized Personal AI request/output types where practical. | P17_1.1 |
| R17.1.3: Implement supported OAuth/OIDC/PKCE registration/sign-in flow. | P17_1.1 |
| R17.1.4: Persist stable host/client registration metadata and credentials only in protected local/user-controlled storage. | P17_1.1 |
| R17.1.5: Validate ID token identity and required ChatGPT-plan usage scope. | P17_1.1 |
| R17.1.6: Implement token refresh, sign-out/disconnect, and revocation/recovery behavior. | P17_1.1 |
| R17.1.7: Implement account-specific model discovery. | P17_1.2 |
| R17.1.8: Implement direct Responses API streaming behind the bridge using current required request semantics. | P17_1.2 |
| R17.1.9: Normalize completed/incomplete/auth/eligibility/usage-limit errors. | P17_1.2 |
| R17.1.10: Add fake bridge and contract tests. | P17_1.3 |
| R17.1.11: Ensure the bridge never returns reusable OAuth tokens to browser/cloud callers. | P17_1.3 |
| R17.1.12: For hosted web integration, define loopback/local-IPC transport with origin allowlisting and anti-CSRF/request authorization. | P17_1.0 |
| R17.1.13: Treat native-mobile support as capability to verify rather than assuming desktop loopback mechanics. | P17_1.0 |

## Targeted verification and closeout

Test OAuth state/nonce/issuer/audience/expiry/scope failures, swapped account/client credentials, concurrent refresh, storage failure, revoked versus temporarily unavailable auth, model churn, malformed stream/terminal loss, caller-origin/Host attacks, cancellation and secret redaction. Add a real documented local-runtime test command when its language/package is selected; it does not exist today.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Distribution approval, OAuth/model access, plan-only billing controls, loopback browser behavior and native-mobile mechanics must be independently verified before enabling the affected clients.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
