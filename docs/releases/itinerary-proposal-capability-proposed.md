# Proposed itinerary proposal capability evidence

**Date:** 2026-10-03 (America/Los_Angeles)
**Verified revision:** `efcd481` on `codex/phase-6-decision-support`
**Status:** implemented for independent review; contract remains proposed and unaccepted.

This upstream capability provides a separately gated `itinerary-proposal-v1`
request and result over bounded typed trip projections. It can add an item from
a caller-selected saved candidate, move an existing item, set or clear local
times, or remove an explicitly allowlisted item. All references use
request-scoped opaque handles. Travel remains authoritative for ownership,
current state, revisions, deterministic preview, and apply. The route defaults
off and performs no travel database reads or writes.

The implementation includes strict DTOs, a bounded generation service using
the existing shared context assembler and `GeminiLLMClient`, selected research
evidence adaptation, an owner-scoped Firestore result aggregate, idempotent
replay, GET-by-id and GET-by-idempotency-key reconciliation, safe failure
envelopes, owner export coverage, request and provider safeguards, and a
credential-free local fake. The exact consumer-shaped fixture is
[`itinerary-proposal-example.json`](../../backend/tests/fixtures/itinerary-proposal-example.json).
The contract and policy decision remain marked proposed in
[`itinerary-proposal-contract.md`](../itinerary-proposal-contract.md) and
[ADR 0019](../decisions/0019-itinerary-proposal-capability.md).

## Offline verification

All checks below were run against the source state committed as `efcd481`.

| Check | Result |
| --- | --- |
| Full backend pytest suite | 526 passed, 12 skipped. |
| Full backend Ruff check | Passed. |
| Context evaluation | Passed. |
| Existing research evaluation | Passed. |
| Decision evaluation | Passed. |
| Domain evaluation | Passed. |
| Iterative-research evaluation | Passed. |
| `make itinerary-proposal-eval` | Passed 6/6 deterministic cases. |
| Backend source/wheel build (`uv build --no-build-isolation` from `backend/`) | Passed. |
| `git diff --check` | Passed. |

The itinerary evaluator and tests use synthetic data and no external calls. Its
six cases cover the consumer-shaped add fixture, cross-kind handles, protected
items, unknown model fields, unknown evidence handles, and a forbidden private
request field. Route tests exercise fake-backed POST, GET by proposal ID, GET
by idempotency key, and rejection of a request above the 262,144-byte cap.
Firestore transaction tests use SDK fakes to check replay, fingerprint
conflicts, owner scope, terminal result writes, and safe storage errors.

The 12 skips are existing manual/provider-backed tests: context (1), Gemini
(1), memory lifecycle (5), memory (3), and research (2). No configured backend
typecheck target or mypy configuration is present. No frontend code changed.

## Remaining gates

The local credential-free endpoint and synthetic evaluations do not establish
live model quality, provider behavior, public authentication behavior,
Firestore emulator/deployment transaction behavior, or deployed index/TTL
readiness. No provider, Firestore emulator, GCP project, or deployment was
contacted. The `retained_until` field is present for an operator-reviewed
Firestore TTL policy, but that external policy is not configured here.
Proposals are included in owner export coverage. Physical deletion through
account deletion requests remains incomplete and is not claimed as delivered.

The upstream feature and provider gates remain disabled by default. The travel
consumer contract must remain unpinned until independent coordinator review
accepts it.
