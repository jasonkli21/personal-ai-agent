# ADR 0007 — Append-only branch-scoped working summaries

Status: Accepted (2026-10-01)

## Decision

A conversation summary is lossy working context, not a user fact, external
evidence, or Phase 3 memory. A usable summary records the ordered complete source turns and their SHA-256
fingerprint of IDs, roles, and content. Coverage IDs separately record the contiguous
raw branch prefix through the last source turn, including skipped incomplete turns,
with a fingerprint of IDs, roles, content, status, and parent links. A branch rewrite or content mismatch makes it ineligible. Records remain
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
snapshot and releases it. Preparation errors, including a failed post-reservation read, release only their
own reservation without requiring a history snapshot;
process-crash/storage failures recover on the next mutation after the provider
timeout plus 60 seconds. Counting and summary generation share one preparation deadline equal to
`REQUEST_TIMEOUT_SECONDS`, with remaining transport timeouts and no SDK retries.
An expired request cannot create a late assistant or
release a newer reservation. Regenerate operates on its post-supersession prefix.

## Consequences

A preparation failure can leave a durable user without an assistant, including
after edit/retry or regenerate. The browser refreshes that path and preserves the
safe error so the user can edit/retry. This deliberately extends Phase 1's atomic
whole-turn behavior: each persistence stage is atomic, but preparation happens
between stages. Summaries are auditable, lossy, and cannot promise perfect recall.
Permanent summary retention/export/deletion policies remain future work.

## Review amendment (2026-10-02)

Skipped incomplete turns are coverage metadata, never summarizer input. They emit
`summary_skipped_incomplete_turns` and cannot permanently block later summaries.
Existing summaries without explicit coverage fields retain the original strict
contiguous-complete-prefix interpretation. Inspection reports coverage and skipped
IDs independently from source IDs. A summary must add coverage without evicting
fitting recent turns; raw history wins when the complete history fits.

A replacement writes only its superseded root plus new records and the conversation
metadata in one transaction. Repository reads expose all descendants as superseded,
including conditional terminal-write checks; raw descendant content and links remain
unchanged. This supports long branches without a growing replacement write batch.
