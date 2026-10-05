# ADR 0020 — Bounded booking document extraction

- **Status:** local implementation candidate; coordinator whole-Phase 6 verification pending
- **Date:** 2026-10-05
- **Scope:** upstream extraction prerequisite for the personal travel app

## Context

The travel application stores private source bytes behind its verified-owner
boundary. It needs bounded candidate extraction, but no upstream contract
currently handles private booking text, data use, replay, and retention.
Travel remains the authority for booking fields and confirmation.

## Decision candidate

Add the separately gated `booking-document-extraction-v1` API. Derive owner
identity only from the verified principal. Accept one hash-bound text source of
at most 200,000 characters, explicit submit consent, and one UUID idempotency
key. Raw input exists only in request/service memory. A single owner/key/fingerprint
Firestore aggregate fences model execution, stores a bounded typed result for
seven days, and supports same-key detail/recovery. Deletion removes candidates
while retaining a short-lived idempotency tombstone. Delete-by-key accepts the
expected source hash and can install that tombstone before a delayed POST; a
later request with that owner/key cannot dispatch a model call. The original
key remains the sole reconciliation key, with no alias to a new key. TTL
remains an explicit operator action.

Use the existing shared context assembler, token budget, provider-neutral
`LLMClient`, and Gemini adapter. Treat the source only as data. Do not consult
memory/search, invoke tools, fetch links, or expose travel identifiers. Return
no more than ten candidates; output includes explicit uncertainty, source
offsets, and a server-reconstructed literal excerpt. Keep dates and timezone
wording verbatim for the travel owner to resolve.

The capability and provider gates both default off. Local fake generation is
limited to local/test environments and requires an explicit synthetic-fixture
marker. Real Gemini inference requires Google OIDC even in a local application
environment. One monotonic deadline covers body receipt, durable claim, model
execution, and terminal persistence. Results enforce unique evidence spans,
literal field support, explicit uncertainty, valid bounded expiry, and an empty
candidate list for non-completed states. Provider quality/data-use review,
deployed identity and Firestore TTL remain unverified. This is a local
integration candidate; coordinator verification remains pending.

## Consequences

The durable store contains the typed candidate review result but never raw
document text. A lost result can be recovered by owner and stable key. A
timeout remains fenced rather than silently invoking another provider call.
Travel owns source retention consent and final schedule interpretation.
