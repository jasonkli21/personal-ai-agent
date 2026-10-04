# Proposed itinerary proposal capability evidence

**Date:** 2026-10-04 (America/Los_Angeles)
**Verified revision:** `b2b9d4a` on `codex/phase-6-decision-support`
**Status:** implemented for independent review; contract remains proposed and unaccepted.

This upstream capability provides a separately gated `itinerary-proposal-v1`
request and result over bounded typed trip projections. It can add an item from
a caller-selected saved candidate, move an existing item, set or clear local
times, or remove an explicitly allowlisted item. All references use
request-scoped opaque handles. Travel remains authoritative for ownership,
current state, revisions, deterministic preview, and apply. The route defaults
off and performs no travel database reads or writes.

The implementation includes strict DTOs, a bounded generation service using the
existing shared context assembler and `GeminiLLMClient`, selected research
evidence adaptation, an owner-scoped Firestore result aggregate, idempotent
replay, GET-by-id and GET-by-idempotency-key reconciliation, safe failure
envelopes, owner export coverage, request and provider safeguards, and a
credential-free local fake. The exact consumer-shaped fixture is
[`itinerary-proposal-example.json`](../../backend/tests/fixtures/itinerary-proposal-example.json).
Policy v2 makes support provenance explicit on every result: `context_only`
when no research session was supplied, and `research_evidence` when one was.
Evidence-backed proposals cite every operation, while supplied evidence that
fails validation never falls back to context-only generation. Partial
`set_item_times` patches retain the distinction between omitted endpoints and
explicit `null` through the HTTP response, Firestore document, and replay.
One monotonic execution deadline begins before the durable claim and is passed
through evidence reads, synchronous context/token counting, provider streaming,
stream cleanup, and terminal persistence. Request receipt and parsing have
separate ingress deadlines, as recorded in the contract.
The contract and policy decision remain marked proposed in
[`itinerary-proposal-contract.md`](../itinerary-proposal-contract.md) and
[ADR 0019](../decisions/0019-itinerary-proposal-capability.md).

## Offline verification

All checks below were run against the source state committed as `b2b9d4a`.

| Check | Result |
| --- | --- |
| Full backend pytest suite | 537 passed, 12 skipped. |
| Full backend Ruff check | Passed. |
| Existing context, research, decision, domain, and iterative-research evaluations | Passed. |
| `make itinerary-proposal-eval` | Passed 6/6 deterministic cases. |
| Backend source/wheel build (`uv build --no-build-isolation` from `backend/`) | Passed. |
| `git diff --check` | Passed in both repositories. |

The itinerary evaluator and tests use synthetic data and no external calls. Its
six cases cover the consumer-shaped add fixture, cross-kind handles, protected
items, unknown model fields, unknown evidence handles, and a forbidden private
request field. Route tests exercise fake-backed POST, GET by proposal ID, GET
by idempotency key, and rejection of a request above the 262,144-byte cap.
Firestore transaction tests use SDK fakes to check replay, fingerprint
conflicts, owner scope, terminal result writes, and safe storage errors.

The 12 skips are existing manual/provider-backed tests: context (1), Gemini
(1), memory lifecycle (5), memory (3), and research (2). New boundary tests
exercise fake-backed HTTP POST, GET, and replay through a Firestore-shaped
document for start-only, end-only, and explicit-null time patches; they assert
that default schema and policy fields remain present and that `model_fields_set`
survives restoration. Deadline regressions cover a slow claim consuming part of
the stream budget, worker-thread counting with event-loop heartbeats, count
timeout without provider dispatch, terminal-write timeout, timeout/replay
fencing, cancellation, and explicit stream closure on cancellation, oversized
output, and non-text output. A standalone coordinator smoke fed the upstream
serialized operations through travel's `preview_proposal` for start-only,
end-only, clearing one endpoint, repeated edits, and a cross-day move; all
preserved travel preview schedules. The upstream runtime does not import travel
packages. No configured backend typecheck target or mypy configuration is
present. No frontend code changed.

## Remaining gates

The local credential-free endpoint and synthetic evaluations do not establish
live model quality, provider behavior, public authentication behavior,
Firestore emulator/deployment transaction behavior, or deployed index/TTL
readiness. No provider, Firestore emulator, GCP project, or deployment was
contacted. The one-deadline behavior is verified with bounded fakes and the
existing finite RPC deadlines; it does not claim hard cancellation of arbitrary
non-cooperative synchronous calls. The `retained_until` field is present for an
operator-reviewed Firestore TTL policy, but that external policy is not
configured here. Proposals are included in owner export coverage. Physical
deletion through account deletion requests remains incomplete and is not
claimed as delivered.

The upstream feature and provider gates remain disabled by default. The travel
consumer ADR 0010 was minimally aligned with the two support modes, but its
contract remains unpinned until independent coordinator review accepts it.

## Review checkpoint

The coordinator review findings are preserved in
[`itinerary-proposal-independent-review.md`](../itinerary-proposal-independent-review.md).
Both substantive findings were addressed in `b2b9d4a`; this checkpoint is
submitted for coordinator re-review. No travel lifecycle, UI, deployment, or
live-provider work was performed.
