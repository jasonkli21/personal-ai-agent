# Booking document extraction contract

**Status:** accepted for the reviewed local travel Phase 6 integration; external private-input gates remain closed
**Schema:** `booking-document-extraction-v1`  
**Date:** 2026-10-05

## Boundary

The owner is resolved from the verified API principal. A request contains no
owner, trip, or travel database identifiers. Travel remains authoritative for
source storage, candidate editing, timezone resolution, reservation matching,
and confirmation. This endpoint infers only a bounded review candidate list.

`POST /v1/travel/booking-extractions` accepts one UUID idempotency key, a
SHA-256 source hash, a media type, an explicit submission consent value, and
the UTF-8 extracted document text. Input is capped at 200,000 characters and
the authenticated route body reader at 1,300,000 bytes. The source hash must
match the supplied text. Fake generation additionally requires the explicit
`synthetic_fixture: true` marker and is available only in local/test
environments. Real Gemini extraction requires the capability/provider gates,
Firestore storage, and Google OIDC authentication even when the application is
configured for a local environment; local development identity never
authorizes private provider inference.

`GET /{extraction_id}` and `GET /by-key/{idempotency_key}` recover the result
for the same verified owner. Same-key/same-fingerprint requests replay the
same durable outcome. Changed content under an existing key returns 409.
Concurrent requests share a durable `running` fence and do not dispatch a
second model call. One monotonic deadline bounds request-body receipt, durable
claim, context assembly, provider inference, and terminal persistence. A body
deadline returns 408 before dispatch. Timeout, cancellation, or a lost
terminal write stays fenced; callers read by the same key before deciding how
to proceed. A conclusive pre-acceptance rejection does not reserve a key, so a
same-key retry may safely submit again; a running or completed key is never
dispatched twice.

`DELETE /{extraction_id}` and `DELETE /by-key/{idempotency_key}` remove the
candidate result and leave an owner/key tombstone through the retention window.
Delete-by-key takes the expected source hash and creates a tombstone if the
request has not arrived yet, fencing a late POST. The original key remains the
only recovery identity; no new-key alias is created. Raw document text is never
written to Firestore, logs, or telemetry. The result may contain at most ten
typed candidates, literal source offsets and a source excerpt no longer than
240 characters. Candidate IDs and evidence spans are unique. Non-completed
states contain no candidates; failure codes appear only on failed results.
Expiry must be after creation and no more than seven days later. The bounded
cleanup command clears expired candidates and
marks the result expired. A reviewed Firestore TTL policy on `retained_until`
removes the entire record after seven days; TTL remains an explicit operator
action. Delete is the explicit early-removal path.

## Data-only model boundary

The document is placed in a data-only block through the existing shared context
assembler and token budget, then sent through the existing `LLMClient` boundary.
The extraction prompt rejects document-supplied instructions. The capability
does not load memory, call search, use tools, follow links, fetch URLs, or access
travel state. Output is strict JSON with unknown/duplicate keys rejected.
The service checks every span against the exact request text and reconstructs
the excerpt from that text; a model cannot provide a remote source or arbitrary
citation. Repeated source spans are rejected. A candidate field is retained
only when supported by its literal excerpt; absent or unsupported values are
removed and added to the strict uncertainty-field set.

Dates and times remain verbatim text. A timezone is returned only when the
document states it explicitly. Missing/ambiguous fields are marked uncertain.
The travel owner must resolve timezone and schedule interpretation and review
every field before reservation confirmation.

The capability and provider gates default off independently. Local tests use
the fake generator and explicit synthetic fixtures. Real model use still needs
provider data-use/retention review, deployed verified user and service
authentication, Firestore TTL policy, and whole-Phase 6 coordinator
verification. No live provider, Google IAM, cloud project, or real private
document was used for this candidate. Verification currently covers the full
backend suite and synthetic API flows; it does not establish hosted readiness.

## Local coordinator acceptance — 2026-10-05

The travel coordinator independently reviewed the whole Phase 6 integration and
accepted code revision `ebd00a8e2fb2d8b59a5fb5fa3aa44268e5e79b63` after remediation.
The final upstream suite passed 561 tests with 12 opt-in skips. The travel
coordinator suite passed 231 migrated PostgreSQL tests with zero skips and 42
frontend tests. Synthetic plaintext/PDF mounted evidence and its final-clock-
amend caveat are recorded in the travel Phase 6 release. This acceptance is
for local code and contract behavior; live Google/IAM/provider data-use,
Firestore retention/deletion and deployment gates remain unverified and off.
No Phase 7 travel work was performed.
