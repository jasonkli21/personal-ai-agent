# Phase 25.1 — user-local ChatGPT execution bridge

This phase implements a separately started local runtime and offline contract
coverage. **Live ChatGPT-plan acceptance remains unavailable/unverified.** There is
no application provider selector, cloud context-package issuer, external-turn
prepare/finalize, manual import, or continuation UI in this phase. Read the
[architecture model](phase-25-1-architecture.md) and [evidence](phase-25-1-implementation-evidence.md).

## Interfaces and ownership

| Seam | Implementation and ownership |
| --- | --- |
| Neutral output | `llm.client.ExecutionProvenance`, `ExternalCompletion`, and additive optional `GenerationMetadata.provenance`. Connected observations and manual user declarations cannot be interchanged. Existing Phase 16 generation behavior remains compatible. |
| Prepared value | `llm.external.PreparedExecution` contains immutable bounded messages, scope/reservation/branch/source digests, selected provider/model/connection revision, sensitivity/policy and byte/deadline limits. It neither builds context nor persists turns. |
| Dispatch proof | `auth.dispatch_grants` verifies domain-separated canonical Ed25519 signatures against locally pinned issuer/key/audience. Hashes bind the entire prepared value. Caller, connection, provider/model, policy/sensitivity and a maximum 120-second validity are checked explicitly. No cloud issuer is implemented. |
| Provider protocol | `llm.chatgpt.OpenAIOAuth` and `ChatGPTResponses` own fixed public endpoints, OIDC/JWKS verification, account model discovery, supported serialization, HTTP/SSE bounds and safe error normalization. They are not registered in the managed automatic-provider factory. |
| Local lifecycle | `local_bridge.lifecycle.CredentialLifecycle` owns pending sign-in, selected registration identity, refresh/reauth/revocation and safe connection projections. |
| Local transport fence | `local_bridge.store.ProtectedLocalStore` owns atomic protected credentials/registrations and hash/status-only send receipts. No prompt, response or quota value is stored. |
| Local caller surface | `LocalChatGPTBridge`, `create_loopback_app`, and the CLI own pairing, expiry, proof checking and one physical send. Local operator commands own sign-in/out and pairing approval. |
| Future cloud orchestration | Phase 25.2 must use existing shared policy/planner/builder and DynamoDB turn transactions for prepare/finalize, Postgres for allowed safe control metadata, and authenticated grant issuance. Browser completion remains a local-client observation, not cloud-verified billing evidence. |

There is no new provider registry, quota ledger, cloud credential store or conversation
state machine. `ChatGPTPlanBridge` is a narrow prepared-request execution contract.
The shared proof/provenance contracts are provider-neutral; the concrete SIWC OAuth
and serializer deliberately remain provider-owned. Other applications use the same
scope/proof contract without application-name control-flow branches.

## Installation and local operator commands

Install the locked backend dependencies using the root README. The current protected
store implementation requires POSIX owner-only files and `flock`. Windows/mobile
credential storage is unsupported/unverified; it has no permissive fallback.

With the backend virtual environment active:

```bash
python -m personal_ai.local_bridge --origin http://127.0.0.1:3000
```

This starts only a loopback prototype on `127.0.0.1:8765`; it does not connect the
existing web UI. For hosted origins, use an exact HTTPS origin, and separately
obtain distribution and browser-transport acceptance before live use. HTTP caller
origins must themselves use literal `127.0.0.1`. Never forward Google/IAM tokens.

The native terminal supports:

```text
sign-in
status
reauth CONNECTION_UUID
sign-out CONNECTION_UUID
pair EXACT_ORIGIN CONNECTION_UUID
quit
```

`sign-in` starts an ephemeral callback listener before opening the system browser.
State, nonce and PKCE are fresh and consumed once. The listener accepts only its
literal Host/peer/path, rejects duplicate parameters and returns a static no-cache,
no-referrer result. Authorization URLs/codes/verifiers are not logged or returned
through execution IPC. Optional `id_token_hint` is omitted so retained ID tokens
never enter authorization URLs; returning sign-in uses the account selector and
must still match the selected verified identity/client. The provider-bound client
registration represents the selected ChatGPT workspace; no workspace ID is invented
from subject/email. Personal AI workspace scope remains separate.

Default local storage is `~/.local/state/personal-ai-bridge` (directory `0700`, files
`0600`). A custom `--directory` must be protected, outside any Git checkout and outside
managed Cloud Run. Symlinks, unsafe permissions, hard-linked files, unsupported
schemas and corrupt state fail explicitly. Keep this directory out of cloud sync,
managed backups, support bundles and exports. Permissions are not an OS keychain or
disk-encryption guarantee; protection of the user's device is an external gate.
Do not delete state to recover an uncertain send or refresh. Reauthorize instead.

Pairing approval is a local terminal action for an allowlisted origin and one
connection revision. It produces a random five-minute caller capability and safe
caller/runtime/connection UUIDs. Keep that capability in transient client memory;
there is no browser-storage implementation here. Restarting drops caller sessions.
Pair again after account reauthorization or disconnect. Host UUID is never caller
authentication. No HTTP route starts OAuth, approves pairing or exposes credentials.

## Compatibility configuration and closed gates

Without protected `compatibility.json`, the runtime has no trusted cloud signing
keys or eligible inference gate. Sign-in/discovery do not imply plan-only billing
eligibility. Do not construct a positive attestation from this guide or synthetic
fixtures: this project has not verified an enforceable no-credit control or hosted
distribution approval.

The optional local file is `0600` and has exactly these top-level keys:

| Key | Contract |
| --- | --- |
| `issuer` | Reviewed context-grant issuer identity. No public cloud issuance exists yet. |
| `keys` | Map of reviewed key IDs to hex-encoded 32-byte Ed25519 public keys, pinned out of band. No browser-supplied key, dynamic JWKS URL or signing secret. |
| `gates` | `CompatibilityGate` records binding local connection/client, reviewed distribution, model-specific compatibility/plan-only evidence, data-use approval/sensitivity ceiling, verification time and expiry (at most seven days). Hosted web requires a distribution-approval reference. `plan_only_verified` defaults false. |
| `private_network_verified` | Defaults false. True requires actual browser/PNA acceptance; synthetic preflight tests do not establish it. |

New models are discovered dynamically, with server ordering and visible slugs/display
names preserved. Discovery is refreshed for every send and selected account. New
models require their own compatibility evidence before inference, and disappearing
models fail before a send. No model/account/provider/billing fallback exists.

## Dispatch, streaming and recovery

IPC supports paired `GET /connection`, `GET /models`, and `POST /execute` containing
`package` and `proof`. Every request checks literal loopback peer, exact Host/Origin,
absence of forwarded or ordinary Authorization headers/query credentials, duplicate
security headers, and `X-Bridge-Authorization`. POST requires `application/json`,
bounded bytes and duplicate-key-free JSON; validation failures never echo input.
CORS allows only the exact approved origin/method/header set. PNA preflight is denied
unless separately verified. HTTPS-to-loopback mixed-content/browser behavior remains
an external capability check, not something CORS alone proves.

The runtime verifies the proof before credential access, then checks local compatibility
and privacy, refreshes if needed, discovers the selected model, and rechecks all
dispatch authority around the durable claim. Tokens must outlive the bounded request.
Claim identity is the owner/app/workspace/conversation/reservation digest, independent
of proof ID; resigning or editing a reservation cannot resend it. A claimed send is
an admitted in-flight effect: sign-out cannot undo a request already admitted to IO.
Connection revision and proof/caller expiry are checked before further output.

The text-only serializer sets `store: false` and `stream: true`, maps system instructions
to developer messages, and supplies the full authorized history as input. It accepts
no arbitrary Responses fields, tools, consumer session/history, previous-response ID,
API key, temperature, provider output-token limit or service-tier override. Request
size is 256 KiB, output at most 256 KiB, stream wire size at most 2 MiB, and total
duration at most 120 seconds (also clipped to proof/caller expiry). SSE line/event
bounds apply before JSON parsing. Compression, duplicate/nonfinite JSON, unknown
features, tools, terminal text/model/status mismatch, and post-terminal events fail
explicitly. Byte truncation is a local safety bound, not a guarantee of provider
token consumption. Credential-echo guards cover model labels and split text deltas.

Only valid `response.completed` plus matching final text becomes success. Explicit
incomplete/failure/admission/usage results have bounded normalized codes. No reset
time or quota availability is inferred. Lost terminal events, transport interruptions,
timeouts, generic server/gateway errors, cancellation, protocol violations or local
output cutoff leave the physical
receipt unknown and single-use. Partial output remains transient. Receipts hold no
output to replay; a lost completion cannot be regenerated under another identity.
Capacity exhaustion (4,096 retained claims or 2 MiB state) stops dispatch instead of
evicting uncertainty. There is no automated receipt reset/pruning procedure.

Refresh records an in-flight marker before IO under the same cross-process lock and
atomically replaces the token set. Confirmed terminal refresh errors clear unusable
tokens; temporary failures retain them. A crash, uncertain rotation or failed
post-rotation persistence requires reauthorization. Disconnect persists a stop before
revocation, then clears tokens while retaining registration/host identity. Remote
revocation failure is explicitly `unconfirmed`; the user can disconnect the app in
ChatGPT settings. No hidden revocation or inference retries run.

## Verification and later phases

Run the existing `make backend-test`, `backend-lint`, and build commands. Focused
offline coverage is in `test_external_execution_contracts.py` and `test_chatgpt_*`.
No provider credentials, browser, cloud, emulator or private domain data are required.
There is no new evaluation runner or live acceptance claim.

Phase 25.2 must supply real authenticated issuance and canonical external-turn
prepare/finalize, source/branch revocation checks and safe coarse connection/usage
projections. It must not treat bridge-observed metadata as server-authenticated facts.
Phase 25.3 owns real browser integration, pairing UX, provider selection, manual
copy/import and continuation. Phase 25.4 composes domain hooks; Phases 30/31 still
own revocation propagation and authoritative domain mutation. Manual declarations
remain credential-free compatibility values here, not an implemented import workflow.
