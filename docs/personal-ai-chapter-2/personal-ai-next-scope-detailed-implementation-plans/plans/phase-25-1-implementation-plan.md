# Phase 25.1 implementation plan — ChatGPT authentication and local bridge

Renumbered on 2026-10-06 from former next-scope Phase 17.1. This file preserves the former detailed-plan scope and only changes numbering, prerequisites, post-Phase-10 persistence references, README-maintenance requirements, and additive compatibility foundations for later cross-provider/manual-external flows. It does not claim delivery.

## Scope boundary

**Goal:** Add the user-controlled execution boundary required for ChatGPT-plan usage without storing reusable ChatGPT credentials in the managed Personal AI cloud backend.

### Normative commitments preserved from former Phase 17.1

- Re-verify current Sign in with ChatGPT/open-source/local-runtime requirements before implementation.
- Define a `ChatGPTPlanBridge`/local-client contract using normalized Personal AI request/output types where practical.
- Implement the supported OAuth/OIDC/PKCE registration/sign-in flow.
- Persist stable host/client registration metadata and credentials only in protected local/user-controlled storage.
- Validate ID-token identity and required ChatGPT-plan usage scope.
- Implement token refresh, sign-out/disconnect, and revocation/recovery behavior.
- Implement account-specific model discovery rather than a hard-coded model list.
- Implement direct supported Responses API streaming behind the bridge using current required request semantics.
- Normalize completed/incomplete/auth/eligibility/usage-limit errors.
- Add a fake bridge and contract tests.
- Ensure the bridge never returns reusable OAuth tokens to browser/cloud callers.
- For hosted-web integration, define loopback/local-IPC transport with origin allowlisting and anti-CSRF/request authorization.
- Treat native-mobile support as a capability to verify rather than assuming desktop loopback mechanics.

### Additive compatibility commitments

These additions do not turn Phase 25.1 into the manual-external UX phase. They only ensure the bridge contracts do not block the later flows owned by Phases 25.2–25.4.

- Bridge output must use normalized completion/provenance types that can coexist with later non-bridge external results.
- Distinguish bridge-observed/connected-provider facts from user-declared or otherwise unverified provider/model metadata; later manual imports must never be misrepresented as authenticated bridge results.
- Do not make ChatGPT credentials, bridge registration, or bridge availability a prerequisite for generic conversation-turn persistence or later manual-external import.
- Preserve enough safe execution provenance for Phase 25.2 to distinguish connected ChatGPT-plan execution from manual external execution without exposing credentials.
- The bridge must not assume it exclusively owns conversation continuation: completed connected-provider turns may later be used as authorized context for another provider through the shared conversation/context pipeline.

### Phase acceptance criteria

- An eligible signed-in user can complete a streamed ChatGPT-plan request through the local/user-controlled runtime.
- No persistent ChatGPT credential appears in Postgres, DynamoDB, GCS, Secret Manager, browser storage, managed logs/traces, analytics, or exports.
- Managed Cloud Run services can operate with zero knowledge of ChatGPT access/refresh tokens.
- The account model list is discovered rather than hard-coded.
- Existing automatic-provider behavior and Phase 16 neutral inference contracts remain functional.
- Normalized bridge completion metadata can be persisted by Phase 25.2 without conflating authenticated/bridge-observed provenance with later user-declared/manual provenance.
- Absence of the bridge does not prevent the shared conversation model from supporting a later manual-external turn type.

### Explicitly out of scope

- automatic strict-free routing through ChatGPT;
- OpenAI API-key/credit billing fallback;
- ChatGPT consumer conversation-history import;
- native-mobile credential design before capability verification;
- manual external-model copy/import UI and workflow, which are owned by Phases 25.2–25.4;
- cross-provider continuation UX, which is owned by Phase 25.3.

## Current state and reuse

The ChatGPT credential runtime, OAuth flow, local bridge transport, and account-specific discovery are new. This is not the existing Google browser authentication flow and it is not a managed Cloud Run provider credential. Reuse Phase 16 inference/error/fake boundaries, Phase 18 provider metadata concepts, and the post-Phase-10 repository ownership rules only for safe non-secret attribution/state; reusable credentials never enter managed persistence.

The shared normalized output/provenance shape must remain provider-neutral enough that later manual-external results can enter the conversation system without pretending to have bridge-authenticated provider/model facts.

## Phase 10 storage dependency

Reusable credentials and local bridge registration remain in protected user-local storage. Only safe managed connection/attribution metadata may use Postgres; Phase 10 storage does not broaden the existing credential/export exclusions. See the [Phase 10 storage contract](../../phase-10-storage-ownership-and-access-patterns.md); existing work packages and acceptance remain unchanged.

## Prerequisites and work ordering

Required phases: 16 and 18. Phase 10 is the standing persistence/security foundation. Work packages run in order.

## Phase-specific invariants

- Reusable credentials stay exclusively in protected user-controlled storage.
- Browser JavaScript and managed cloud services never receive access/refresh tokens.
- Preview/operational OpenAI requirements are revalidated compatibility facts, not permanent assumptions.
- A ChatGPT-plan failure cannot silently use API-key credits, another account, or an automatic provider.
- Authenticated bridge execution and later manual external execution are distinct provenance modes.
- A later provider may consume a completed ChatGPT turn only through the shared authorized context pipeline; the bridge itself does not bypass source/sensitivity policy.

## Work packages

### P25_1.0 — Eligibility and transport decision

Revalidate the dated SIWC snapshot before live work. Classify hosted web plus installed-bridge distribution and obtain any required approval. Verify plan-only controls with no silent credit use. Prototype only supported loopback/local IPC with exact Origin/Host checks, pairing and expiring caller authorization, DNS-rebinding prevention, bounded streams, and explicit browser/PNA/mixed-content compatibility. Native mobile is an external capability gate, not an assumed transport. Never forward Google/IAM tokens to the bridge.

**Acceptance:** distribution, transport, and plan-only billing decisions are recorded; a failed external gate leaves live ChatGPT inference unavailable without weakening the rest of Personal AI.

### P25_1.1 — Local identity and credential lifecycle

Define bridge types on top of Phase 16 neutral records and an independently testable fake. Implement documented public-client OAuth/OIDC/PKCE with per-attempt state/nonce, validated client/account identity, and required granted scopes. Stable host identity alone never authenticates a caller. Keep host/client/account/workspace registrations distinct in protected local storage. Serialize rotating refresh, atomically replace credentials, stop on confirmed revocation, distinguish temporary unavailability from revocation, and expose only safe connection state to browser/cloud.

Define the signed/short-lived dispatch-grant proof format and verifier that Phase 25.2 will use for cloud-issued context packages. Cloud context packages are not live until authenticated issuance exists.

**Acceptance:** auth/refresh fixtures reject state/nonce/issuer/audience/account/scope mismatches and expose no reusable credential material.

### P25_1.2 — Account discovery and supported inference

Discover account-specific model visibility/display/slug metadata and refresh it when the account changes. Implement a versioned bridge serializer for only supported Responses fields, required non-persistence semantics, and bounded streaming. Reject unsupported tools/fields instead of forwarding an ordinary API body. Consume explicit terminal completion; classify interruptions/auth/admission/eligibility/usage errors; bound request/output bytes and total deadline. Do not assume unsupported output-limit fields and do not retry uncertain dispatch under a new identity.

Return only normalized completion/error data plus safe execution provenance needed by Phase 25.2. Connected-provider/model facts may be marked bridge-observed where justified; no bridge result shape may require later manual imports to claim the same trust level.

**Acceptance:** discovery and serializer tests handle model churn, unsupported requests, terminal loss, and usage/admission errors with no billing fallback; normalized results carry safe trust/provenance metadata without credentials.

### P25_1.3 — Security and compatibility closeout

Test bridge/fake contracts and synthetic auth transports independently of cloud services. Assert that no token, auth code, verifier, secret authorization URL, or reusable account material enters returned objects, browser storage, Postgres, DynamoDB, GCS, Secret Manager, logs/traces, analytics, exports, or committed fixtures. Document installation/pairing/lifecycle and supported desktop transport. Mobile remains explicitly unverified until separately proven.

Add contract coverage proving that generic normalized completion/provenance records do not require reusable ChatGPT credentials and can coexist with a separate manual-external provenance mode owned by Phase 25.2.

**Acceptance:** local-runtime tests and redaction scans cover every credential persistence/output path; skipped compatibility gates remain unverified; bridge-neutral completion contracts do not prevent later manual-external persistence.

## Requirement coverage

All former Phase 17.1 commitments remain normative. P25_1.0 owns external eligibility/transport/native capability; P25_1.1 owns OAuth/identity/credential lifecycle and dispatch proof; P25_1.2 owns account discovery and supported Responses streaming; P25_1.3 owns fake/security/redaction/compatibility closeout. The additive compatibility requirements only establish provenance/type boundaries for later phases and do not add manual-external UI or execution to this phase.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
