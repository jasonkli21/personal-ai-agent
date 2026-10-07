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

## Independent review follow-up

Date: 2026-10-07 (America/Los_Angeles)

Review: [Phase 12 independent review](../phase-12-independent-review-2026-10-07.md).
Implementation tested at revision `d37bd883aafc883b32ce7dc0103f1b561917b15a`;
documentation updates in this follow-up are recorded after that code commit.

All nine review findings were addressed with focused fixes and regression tests:

- Conversation provider selection now excludes invalid turns and preserves each
  complete turn through result limits and token fitting. Counter cleanup spans
  standalone preparation, and nested deadlines forward the shortest remaining
  timeout.
- Memory retrieval limits apply after eligibility and fit decisions, allowing
  fitting consolidated backups to be used. Required items are fitted before
  optional inputs, and required status follows the selected provider operation.
- Expiry is checked again at final assembly, including for standalone research
  and proposal evidence. Final manifests are emitted by the owning preparation
  boundary and retain message/summary attribution, operation/provider failures,
  and source versions while omitting content. Booking preparation fit failures
  return the existing `context_too_large` result.

Verification against the implementation revision:

- `./.venv/bin/python -m pytest`: **672 passed, 26 skipped**. Skips remain the
  opt-in local Postgres/DynamoDB, cloud smoke, and manual provider/context cases.
- `./.venv/bin/python -m ruff check .`: **passed**.
- `make context-eval`, `make memory-eval`, `make research-eval`, and
  `make itinerary-proposal-eval`: **passed**, using deterministic synthetic
  fixtures only.
- `git diff --check`: **passed**.

These checks establish local behavior and offline contracts only. Provider
token-count accuracy, live source integrations, Postgres/DynamoDB behavior,
cloud/IAM, deployment, and production security remain unverified. The inspector
still estimates the current view and cannot reconstruct the exact prompt from a
past generation. Phase 13 automatic source planning remains out of scope.

## Verification pass

Date: 2026-10-07 (America/Los_Angeles)

Verified revision: `24502e4ea9463da68e0e3736c9b5befb45ba141c` (documentation-only
follow-up to implementation revision `d37bd883aafc883b32ce7dc0103f1b561917b15a`).
The current code matches the review remediation; no remaining Phase 12 review
finding was identified.

- Backend suite: **672 passed, 26 skipped**.
- Ruff: **passed**.
- Context, memory, research, and itinerary-proposal evaluations: **passed**;
  these use synthetic/offline fixtures.
- `git diff --check`: **passed**.

The Makefile targets could not launch because `python` is absent from this
shell's `PATH`; equivalent Python modules were run with `backend/.venv/bin/python`.
Skipped local persistence, cloud, and manual provider checks remain unverified.
