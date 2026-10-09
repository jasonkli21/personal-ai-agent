# Phase 25.1 local execution boundary

Design date: 2026-10-09. This records the implementation model, not live acceptance.

## Ownership and extension seams

Phase 16 `ChatMessage`, `InferenceContext`, `GenerationEvent`, `GenerationMetadata`,
`GenerationResult`, `ProviderIdentity`, and `UsageMetadata` remain the inference
vocabulary. Add orthogonal execution provenance; a manual declaration must never
acquire a connected identity, account, usage, or billing assertion. A manual result
contract needs no bridge installation. No automatic provider factory, registry,
router, quota ledger, or application workflow gains a ChatGPT adapter in this phase.

`llm.chatgpt` owns documented OpenAI public-client OAuth, verified identity,
account discovery, restricted Responses serialization and bounded HTTP/SSE.
`local_bridge` owns local installation/registration/credential lifecycle, caller
pairing, proof consumption, and physical-send fences. It is a separately started
user process, never composed into `main`, the worker, or managed settings.
`auth.dispatch_grants` defines an asymmetric, pinned-key proof verifier; it does
not issue cloud grants or authenticate a cloud principal.

Cloud services retain shared membership/source/sensitivity policy, context
assembly, and canonical conversation orchestration. Phase 25.2 must prepare and
finalize through the existing DynamoDB conversation transaction and issue grants
only after authoritative checks. Postgres may later own safe connection metadata;
this phase writes none. No bridge code reads domain, conversation, memory, policy,
usage, or artifact repositories. The bridge cannot itself authorize cloud context.

## Trust and persistence

Host UUID identifies an installation; OAuth client ID identifies an account/workspace
registration. Verified issuer/subject identifies the user; email is not identity or
workspace. The provider's client registration binds workspace, so do not invent a
workspace ID from email/subject or opaque access-token claims. Personal AI workspace
is a separate package field. A local random connection UUID is the only account
reference exposed to callers. Tokens, retained ID token, client/host mapping and
pending registration are confined to a protected POSIX local store. Pending PKCE,
nonce/state and authorization URLs stay process-local and are never HTTP responses.

Pairing is explicitly approved at the local operator surface for one exact origin.
It yields a short-lived caller capability, distinct from OAuth/Google/IAM credentials.
Every local HTTP request checks literal loopback peer and exact Host; browser
operations additionally check exact Origin, method/content type and caller capability.
Cloud context is usable only with a pinned Ed25519 signature binding its canonical
content hash, selected connection/provider/model, policy/sensitivity, caller,
runtime audience and expiration. Browser edits cannot become policy authority.
There is no cloud signer in this phase. Browser storage is not used.

Local atomic JSON is the canonical store for credentials and send receipts. POSIX
owner-only directory/files, no symlinks, cross-process flock, atomic replacement and
fsync protect updates. Unsupported platforms/storage protections fail explicitly.
Local receipts store hashes/status only, never prompt/output. They are transport
replay fences, not a second cloud conversation ledger or quota system. Capacity
exhaustion fails closed rather than evicting an uncertain send.

## State and external effects

OAuth attempts expire and consume state once. New registration is retained before
code exchange but remains unverified until signed identity/scopes are checked;
failed sign-in never changes another active registration. Returning sign-in must
match issued client/issuer/subject exactly. Identity-only sign-in is retained but
cannot execute. Refresh is serialized across processes, records a durable in-flight
marker before IO and replaces the full token set atomically. Confirmed terminal
refresh failures clear unusable tokens; temporary failures retain them. An interrupted
rotating refresh requires reauthorization instead of replaying an uncertain token.
Disconnect stops locally and clears tokens even if remote revocation is unconfirmed.

Dispatch identity is the signed scoped reservation, independent of proof ID. Claim
is durable before provider IO. Duplicate, expired, edited, foreign, model-churn or
connection-revision requests fail without a send. Success requires an explicit valid
terminal event; interruption/deadline/cancellation retains an unknown/incomplete
fence and partial output is transient. No IO retry, account switch, API credit/key
fallback, provider fallback, or provider conversation-history inheritance exists.
Output bounds are local byte bounds, never unsupported Responses token-limit fields.

## External gates and alternatives

Official SIWC documentation was fetched on 2026-10-09: [overview](https://developers.openai.com/siwc/token-sharing-open-source),
[sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in),
[sessions](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions),
[inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference),
[tokens](https://developers.openai.com/siwc/token-sharing-open-source/token-reference),
[recovery](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery),
and [limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).
Public-client local registration is documented; remotely hosted distribution needs
separate eligibility review. No enforceable plan-only/no-credit control was verified
for this project. Live inference defaults unavailable; local attestation must name
the approved distribution and account/client/model-specific plan-only evidence.
Identity permission alone does not prove billing eligibility. Native mobile and
real browser PNA/mixed-content compatibility remain unverified.

Direct restricted Responses transport was selected over LiteLLM ordinary API-body
translation or Codex app-server (which would add tool/history orchestration).
POSIX protected files follow the documented local storage option; no plaintext
fallback for unsupported OS or unsafe paths. Asymmetric grants avoid forwarding
cloud identity tokens or sharing a cloud signing secret. No foundational orchestration
change is needed. Phases 25.2–25.4 extend existing policy/context/conversation seams;
Phases 30/31 must still propagate revocation and retain domain mutation authority.
