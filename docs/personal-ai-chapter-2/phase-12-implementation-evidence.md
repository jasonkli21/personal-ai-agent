# Phase 12 implementation evidence — Context builder refactor

Date: 2026-10-07 (America/Los_Angeles)

Tested source base: `983cbab857ecd1214e75244012de34c392492b43`. Final verification
ran against the complete Phase 12 implementation and documentation working tree
based on this revision, immediately before commit.

## Delivered

- Added one shared model-input builder with validated global and per-source
  token ceilings, deterministic source priorities, wrapper-aware fitting,
  whole-item omission, and explicit required-source failures.
- Preserved mandatory newest-user input, complete active-branch turns,
  compatible branch-scoped summaries, memory eligibility, memory priority, and
  existing task validators and timeouts.
- Combined chat conversation and memory with typed items from explicitly
  selected context providers. Rechecked item expiry and permission dependencies
  at the assembly boundary; missing permission revalidation fails closed.
- Added deterministic effective sensitivity and a safe actual-build manifest
  with source authority, message/summary attribution, counter kind/version,
  per-source counts, injected IDs, and omission reasons.
- Routed standalone research, itinerary proposal, and booking extraction input
  through the same builder while preserving their task-specific selection,
  validation, evidence, deadline, and replay behavior.
- Updated the read-only context inspector to label its result as an estimated
  current view, not historical reconstruction. Added Phase 12 regression tests
  and updated the root README and living status documentation.

## Verification

Commands were run with the repository backend virtual environment activated:

- `make backend-test`: **652 passed, 26 skipped**. The skips were 23 opt-in
  local Postgres/DynamoDB cases, one cloud smoke case, one manual context case,
  and one manual Gemini case.
- `make backend-lint`: **passed**.
- `make context-eval memory-eval research-eval itinerary-proposal-eval`:
  **passed** with deterministic synthetic fixtures only.
- Focused context, memory, research, proposal, and booking tests passed as part
  of the backend suite.
- `git diff --check`: passed after final documentation edits.

These checks do not establish provider token-count accuracy, local Postgres or
DynamoDB behavior, cloud/IAM behavior, external provider behavior, or production
security. The Phase 10/11 opt-in persistence and deployment acceptance gates
remain open. No frontend, cloud, provider, or browser checks were required or
claimed for this backend change.

## Remaining boundaries

- Context selections remain explicit; deterministic source planning is Phase 13.
- Provider token counts, real domain-source grants, deployed source freshness,
  and cloud behavior still need their separately configured acceptance checks.
- The inspector estimates the current view and cannot prove the exact historical
  prompt for an earlier generation.
