# Booking document extraction contract

**Status:** local implementation candidate; travel integration and independent whole-phase review pending  
**Schema:** `booking-document-extraction-v1`  
**Date:** 2026-10-04

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
`synthetic_fixture: true` marker and is intended for synthetic local/test
fixtures only.

`GET /{extraction_id}` and `GET /by-key/{idempotency_key}` recover the result
for the same verified owner. Same-key/same-fingerprint requests replay the
same durable outcome. Changed content under an existing key returns 409.
Concurrent requests share a durable `running` fence and do not dispatch a
second model call. Timeout, cancellation, or a lost terminal write stays
fenced; callers read by the same key before deciding how to proceed.

`DELETE /{extraction_id}` and `DELETE /by-key/{idempotency_key}` remove the
candidate result and leave an owner/key tombstone through the retention window.
Delete-by-key takes the expected source hash and creates a tombstone if the
request has not arrived yet, fencing a late POST. The original key remains the
only recovery identity; no new-key alias is created. Raw document text is never
written to Firestore, logs, or telemetry. The result may contain at most ten
typed candidates, literal source offsets and a source excerpt no longer than
240 characters. The bounded cleanup command clears expired candidates and
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
citation.

Dates and times remain verbatim text. A timezone is returned only when the
document states it explicitly. Missing/ambiguous fields are marked uncertain.
The travel owner must resolve timezone and schedule interpretation and review
every field before reservation confirmation.

The capability and provider gates default off independently. Local tests use
the fake generator and explicit synthetic fixtures. Real model use still needs
provider data-use/retention review, verified service authentication, Firestore
TTL policy, and whole-Phase 6 coordinator acceptance. No live provider, Google
IAM, cloud project, or real private document was used for this candidate.
