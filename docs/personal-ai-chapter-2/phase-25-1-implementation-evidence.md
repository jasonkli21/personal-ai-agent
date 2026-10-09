# Phase 25.1 implementation and acceptance evidence

Date: 2026-10-09. Tested runtime revision: **4ff5ee445b1f3c2779dd29a723e01afacd675d45**.
Contract/design commit: 6fe8898. Subsequent evidence/status edits are documentation-only.
Existing untracked independent-review documents were preserved.

**Disposition: local implementation verified; full Phase 25.1/live acceptance remains
open.** No real ChatGPT account, reusable provider credential, provider request, cloud
resource, database migration, or application workflow was used or enabled.

## Architectural model and rewrite-risk review

Read the [architecture model](phase-25-1-architecture.md), written before substantive
runtime implementation, and [operator/interface guide](phase-25-1-implementation-guide.md).
The implementation was checked against the current P10 persistence cutover, P11–15
context/policy boundaries, P16 neutral inference contracts, P18–24 routing/accounting
ownership, and downstream P25.2–25.4 plans.

The bridge consumes a bounded prepared value and emits neutral generation events.
It does not build context, authorize cloud sources, persist conversations, route
automatically, manage a quota ledger, or orchestrate domain actions. Shared policy
and the P12 builder remain future cloud preparation authority. Existing DynamoDB
turn transactions remain canonical conversation authority. Postgres remains the
future store for permitted safe connection/control metadata; no managed store was added.

Generic seams extended additively:

- ChatMessage accepts developer instructions; existing messages/adapters remain functional.
- GenerationMetadata has optional execution provenance. ExecutionProvenance and
  ExternalCompletion distinguish connected observations from credential-free manual
  declarations and reject fabricated connected identity/usage for manual results.
- PreparedExecution extends existing application scope and validates InferenceContext.
  It binds branch/source-authority digests, scoped reservation, provider/model/connection
  revision, exact messages, sensitivity/policy and limits. This is a connected execution
  value, not a new prepared-turn repository or prerequisite for manual persistence.
- DispatchGrantVerifier checks a provider-neutral, domain-separated Ed25519 format
  against pinned local issuer/key/runtime/caller authority. It revalidates typed values
  and binds the whole canonical package. Cloud issuance is absent until Phase 25.2
  can authorize and reserve the canonical turn.

No foundational orchestration or persistence abstraction changed. The local receipt
is an execution-boundary replay fence, not a second cloud turn state machine.
P25.2 must bind it to existing scoped turn reservations and treat client-reported
output as an observation rather than server-verified billing evidence.

Alternatives considered: ordinary LiteLLM API-body translation cannot safely represent
restricted SIWC requests without unverified semantics; Codex app-server adds unneeded
tools/history orchestration. Direct supported Responses transport therefore lives in
the provider adapter behind the narrow bridge. Protected POSIX files use the documented
local storage option; unsupported platforms fail explicitly. Pinned asymmetric proofs
avoid sharing a cloud signing secret or forwarding Google/IAM tokens. Optional ID-token
hints are omitted rather than putting retained tokens into browser URLs/history.
Distribution, plan-only billing and native transport uncertainties leave live gates closed.

Rewrite-risk conclusions: responsibility remains in the appropriate layer; applications
can use the same scoped proof/output contracts, and future connected providers can supply
their own adapted transport without changing cloud conversation control flow. Manual
results need no bridge/account. Provider protocol stays out of generic policy/routing.
Future phases must extend shared policy/context/conversation seams rather than copying
the bridge into managed services. Proof/package versioning and conservative receipt
retention remain explicit compatibility/operational concerns, not retry permission.

## State, concurrency and external effects

| State | Canonical owner / behavior |
| --- | --- |
| Host/runtime UUID, client and verified issuer/subject | Protected local store. Host identifies installation; client binds provider registration/workspace; subject identifies verified account. Random connection/runtime references alone cross the caller boundary. |
| Access/refresh/ID tokens and scopes | Protected local credentials. No browser/cloud response, API key, Secret Manager or managed repository path. |
| OAuth state/nonce/PKCE | Process-local, bounded, expiring and one-use. Returning sign-in matches selected client/account/revision; disconnect invalidates pending reauthorization. |
| Rotating refresh | Cross-process lock, durable marker before IO, atomic full replacement. Terminal revocation clears tokens; temporary failure retains them; uncertain rotation/crash/persistence requires reauthorization. |
| Connection lifecycle | Connected, disconnected, permission-required, unavailable or reauth. Reauthorization/disconnect advance revision; rotation preserves it. Local disconnect and remote revocation confirmation are separate. |
| Caller pairing | Local approval for exact origin/connection revision; five-minute capability; hashed memory-only lookup. Restart drops sessions. |
| Compatibility/privacy | Protected local evidence tied to connection/client/model/distribution/expiry. Package denial precedes refresh; verified client is checked after credential resolution. Defaults deny. |
| Physical send | Scoped owner/app/workspace/conversation/reservation digest, independent of proof ID. Durable unknown claim precedes IO; concurrent/reissued requests cannot send twice. |
| Send settlement | Only known provider terminal/admission outcomes settle. Generic server/gateway failures, terminal loss, timeout, cancellation, protocol/output cutoff or credential echo remain unknown. No retry/fallback/output replay. |
| Turn, active branch, source authority and domain actions | Existing cloud/application owners. No bridge implementation or bypass; cloud issuance/finalization remains P25.2 work. |

Atomic replacement plus file/directory fsync is tested through injected persistence
failure; real power-loss/filesystem behavior remains unverified. Hash/status receipts
cap at 4,096 and never evict unknown sends. Deleting state is not recovery. A durable
admitted send cannot be undone by disconnect; revision/expiry checks stop further output.

## Work-package coverage

| Plan package | Local code/evidence | Remaining acceptance |
| --- | --- | --- |
| P25_1.0 | Dated official SIWC revalidation, restricted transport decision, exact peer/Host/Origin/pairing/capability checks; closed PNA and plan/distribution gates. | Hosted approval, enforceable account/model plan-only/no-credit control, real browser mixed-content/PNA and native mobile. |
| P25_1.1 | Provider OAuth; protected store/lifecycle; pinned dispatch proof; independent fake; generated JWT/JWK and lifecycle fixtures. | Real registration, scopes/identity/workspace, refresh and revocation interoperability. Cloud issuance belongs to P25.2. |
| P25_1.2 | Account-visible models; versioned text-only serializer; non-persisting streaming; bounded HTTP/SSE; strict terminal/model/text/usage validation and errors. | Real discovery/Responses/limits/wire compatibility and billing eligibility. |
| P25_1.3 | Safe outputs/representations/errors, split-delta echo guard, operator/callback fixtures, fake/neutral contracts, process contention/restart. | Native browser storage/history/logging/callback, device backup/disk protection, deployed no-token inspection and independent review. |

Implementation resides in backend/src/personal_ai/llm/chatgpt/, local_bridge/,
llm/external.py, llm/client.py and auth/dispatch_grants.py. Dependencies add maintained
PyJWT/cryptography support. No frontend code, managed composition, migrations, registry,
quota ledger, evaluation runner or application workflow changed.

## Verification

Configuration: macOS/POSIX, Python 3.11.15, locked backend dependencies; synthetic
accounts/keys/transports only. Local test directories and generated keys are ephemeral.
Frontend checks used the bundled Node runtime. Final backend/focused/lint/format/build
checks cover the runtime revision above. Frontend and existing evaluation commands
ran earlier in this work session against their unchanged surfaces; they were not
repeated after the final bridge-only security refinements.

| Command / check | Result |
| --- | --- |
| make backend-test | **1246 passed, 76 skipped**, 2 dependency warnings. Skipped persistence/provider/manual tests remain unverified. |
| Focused pytest tests/test_chatgpt* and tests/test_external_execution_contracts.py | **137 passed**, 1 Starlette/HTTPX deprecation warning. |
| make backend-lint | Passed. |
| Ruff formatting check on contracts/runtime/fixtures | Passed. |
| UV_CACHE_DIR=/tmp/personal-ai-uv-cache make backend-build | Passed: source distribution and wheel. Default user-cache sandbox access failed; writable cache resolved it. |
| make frontend-test | Passed: **98 tests / 19 files**. |
| make frontend-lint frontend-typecheck | Passed. |
| make frontend-build | Passed; existing Next ESLint-plugin warning remains. |
| make context-eval context-plan-eval quota-scarcity-eval cascade-eval | Passed existing synthetic baselines; no provider/emulator/cloud acceptance inferred. |
| python -m personal_ai.local_bridge --help | Passed CLI import/argument smoke check. |
| Composition/source inspection and safe-output fixtures | Bridge absent from managed API/worker/settings/automatic provider composition; returned state/provenance/events/errors exclude tested credentials/account material. |
| Documentation links/content and git diff --check | Passed for changed documents/diff. |

Fixtures cover nonce/state/issuer/audience/client/account/scope/key mismatch, public
PKCE/discovery capabilities, refresh/revocation/rotation persistence, denial before
refresh, literal IPC authorization/PNA denial, edited/expired/foreign proofs,
model churn, unsupported tools/fields, terminal loss/post-terminal events,
compression/oversized/malformed streams, deadlines/cancellation, split credential
echoes/model labels, and unknown-dispatch restart fences. Two real spawned local
processes contend for one durable claim; only one wins. Other provider/browser/HTTP
behavior uses synthetic transports/controllers.

During final review an older 503 fixture expected generic unavailability rather than
unknown physical outcome. It failed after the conservative semantics change, was
updated, and focused/full regressions above were rerun successfully. No unresolved
failure is suppressed.

## Open gates and reviewer challenges

- This repository has **not established an enforceable plan-only/no-credit control**.
  Never turn a documentation assumption or synthetic fixture into a positive attestation.
- Hosted distribution approval is unverified. Public-client code alone does not establish
  the project's open-source distribution eligibility. See the dated
  [official sources](phase-25-1-architecture.md#external-gates-and-alternatives).
- Challenge strict OIDC/JWKS/audience/client/scope/discovery and Responses assumptions
  against a real approved account/runtime. Drift fails explicitly, never via fallback.
- Native callback/loopback binding, Origin/Host, PNA/mixed-content, interruptions and
  token non-exposure require opt-in end-to-end testing. Synthetic CORS proves no
  browser capability. Mobile remains unverified.
- POSIX permissions are not a keychain, encryption, backup exclusion or protection
  against a compromised same-user process. Device and filesystem crash protections
  need independent review before personal data.
- Challenge refresh uncertainty and durable claim/send boundaries: crashes, clocks,
  disconnect races and receipt capacity. A local fence cannot atomically commit remote IO.
- P25.2 must issue grants only through current shared membership/source/sensitivity
  checks and canonical branch reservations. Replay/finalization/revocation remain in
  existing turn transactions. A valid signature is not itself policy.
- Bridge-observed provenance is trustworthy only inside the local boundary.
  Browser reports cannot establish server-authenticated identity, billing, quotas
  or retention rights.
- P25.3–25.4 must preserve credential-free manual provenance and shared authorized
  continuation/domain hooks; P30/31 retain derived-context revocation and authoritative
  domain mutation. No independent reviewer was run as a subagent in this task.

The root README, router and living current-state record were reconciled. The plan
remains a requirement document; unmet external acceptance is not recorded as delivery.
