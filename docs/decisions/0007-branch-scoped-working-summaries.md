# ADR 0007 — Append-only branch-scoped working summaries

Status: Accepted (2026-10-01)

## Decision

A conversation summary is lossy working context, not a user fact, external
evidence, or Phase 3 memory. A usable summary must record an ordered contiguous
prefix of complete active turns and a SHA-256 fingerprint of IDs, roles, and
content. A branch rewrite or content mismatch makes it ineligible. Records remain
append-only and source messages are never superseded merely to summarize them.

Summary generation is synchronous only when omitted older history reaches
`SUMMARY_TRIGGER_TOKENS` (12,000 by default). The largest prefix that fits the
shared summary-input budget is used. Later refreshes can combine the compatible
prior summary with additional complete turns; each record fingerprints all raw
source messages it covers. No Pub/Sub jobs or background workers are introduced.

The generation output ceiling is `MAX_SUMMARY_TOKENS` (2,048 by default). Empty,
malformed, and oversized outputs are rejected before persistence. The prompt
preserves uncertainty and corrections, prohibits invented facts/preferences or
external evidence, and treats source text as data. A failed refresh reports a
safe diagnostic and falls back to fitting recent context; mandatory overflow
still rejects the turn.

User persistence/branch mutation reserves a conversation before counting or
summarizing. Assistant creation atomically checks the same reservation and active
snapshot and releases it. Preparation errors release only their own reservation;
process-crash/storage failures recover on the next mutation after the provider
timeout plus 60 seconds. An expired request cannot create a late assistant or
release a newer reservation. Regenerate operates on its post-supersession prefix.

## Consequences

A preparation failure can leave a durable user without an assistant, including
after edit/retry or regenerate. The browser refreshes that path and preserves the
safe error so the user can edit/retry. This deliberately extends Phase 1's atomic
whole-turn behavior: each persistence stage is atomic, but preparation happens
between stages. Summaries are auditable, lossy, and cannot promise perfect recall.
Permanent summary retention/export/deletion policies remain future work.
