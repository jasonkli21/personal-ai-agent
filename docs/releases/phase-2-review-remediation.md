# Phase 2 review remediation

Date: 2026-10-02 (America/Los_Angeles).
Tested state: remediation working tree based on `cd1a4bf`; this record ships in
its single follow-up commit. Phase 3 has not started.

## Corrections and regression evidence

- Locked `editables==0.5` in both build declarations. The exact two-step README
  install now succeeds with uv 0.11.13 and Python 3.11.15, including editable installation.
- Complete-turn boundary search replaces linear provider counting. A fully fitting
  100-turn fixture makes two actual mocked SDK transport calls instead of 101,
  reuses one owned client, and closes it at assembly completion. Counting and summary
  generation share one preparation deadline, forwarding remaining transport time
  with retries disabled; a simulated expiration starts no assistant/model stream.
- Snapshot-independent owner/reservation-conditional release handles a failed
  post-reservation history read. Regression checks immediate retry and protection
  of another request's reservation.
- Raw fitting context takes priority. Summary selection preserves fitting recent
  turns and must add older coverage; tests cover fitting and overflowing histories.
- Separate source/coverage provenance allows refresh across failed turns. Only
  complete sources enter summarization; raw coverage includes skipped records and
  fingerprints their state/content/parents. Tests cover incremental refresh,
  corrected facts after a gap, and invalidation when skipped records change.
  Legacy summaries retain their original compatibility rule.
- Both repositories implement durable root cuts. A 600-message edit or regenerate
  writes at most three records in initial preparation, preserves historical content
  and links, and exposes descendants as superseded. Terminal updates validate
  ancestry transactionally. Tests cover both adapters and reservation ownership.
- Fixture version 2 seeds an original summary, executes edit-and-retry, then
  verifies corrected facts, exclusion of obsolete facts, superseded audit records,
  and original-summary invalidation. The updated synthetic evaluation output is
  [recorded separately](phase-2-context-evaluation.json).

## Verification

- Backend: 117 passed, 2 credentialed checks skipped; Ruff passed.
- Context evaluation: all five fixtures passed using fake token units, without provider calls.
- Backend source distribution and wheel build passed.
- Frontend: 32 tests passed; lint, type checks, and production build passed using
  available Node 24.19.0 and pnpm 11.19.0. Node 22 verification remains pending;
  the temporary-runtime download was not approved.
- Deployment shell syntax, local documentation links, evaluation JSON, and
  `git diff --check` passed.

Docker is unavailable locally. Docker/CI execution, real Firestore transactions
and restart persistence, live Gemini quality/counts, and deployed browser behavior
remain unverified. Fake repositories and mocked transport do not close those gaps.
