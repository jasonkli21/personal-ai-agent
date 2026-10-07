# Phase 13 implementation evidence — Deterministic context planner

Date: 2026-10-07 (America/Los_Angeles)

Tested source: Phase 13 remediation working tree based on
`9e5ec35d54078f8203604662b4b59ba52a2c57c7`; the fixes and this evidence are
included in the single follow-up commit created after verification.

## Delivered

- Default memory planning now requires a bounded personal-recall question.
  General “remember” instructions, general knowledge questions, and negative
  recall language do not select memory, call the retriever, or inject memory.
- Rules merged for one provider operation retain complete requested profile
  field coverage. The profile contract defines one result per field, subject to
  registered and global limits. Required fields reserve planning budget before
  optional fields; displaced optional rules receive explicit omission reasons.
- The builder enforces each planned provider/operation token allocation along
  with source-class and whole-request ceilings. An oversized optional selection
  is omitted without spending another selection's allocation; an oversized
  required selection fails closed.
- Typed memory items preserve original `user_asserted` and `derived`
  authorities. Validated derived-memory source IDs pass through to the builder;
  represented originals are suppressed only after the derivation is admitted,
  so originals and unrelated memories remain eligible if it does not fit.
- Actual chat retrieval uses the minimum of the selected memory-operation
  timeout, configured memory timeout, and remaining request deadline. Unselected
  memory does not trigger retrieval.
- The offline planner evaluator exercises the built-in memory and shared-profile
  adapters, including current sharing checks. It verifies exact provider
  operations and bounds, distinguishes planned/retrieved/injected support, fails
  positive-support fixtures when permission or budget removes that support, and
  exits nonzero for any failed fixture. Its byte-based envelope counter is an
  offline estimate; provider token-count accuracy was not evaluated live.

## Verification

Commands ran with the repository backend virtual environment on the tested
source tree:

- `make backend-test`: **710 passed, 26 skipped**. The skips are 23 opt-in local
  Postgres/DynamoDB checks, one cloud smoke check, one manual context check, and
  one manual Gemini check.
- `make backend-lint`: **passed**.
- `make context-plan-eval`: **passed**, including all nine planner fixtures
  against built-in memory/profile adapters and synthetic domain providers.
- `make context-eval memory-eval research-eval domain-eval
  memory-lifecycle-eval`: **passed** with deterministic offline fixtures.
- `git diff --check`: **passed** after the final implementation and evidence
  edits.

These results establish local behavior and offline contracts only. They do not
establish local Postgres or DynamoDB behavior, cloud/IAM behavior, real provider
behavior, deployed source grants, production security, live token-count
accuracy, or live domain integrations. The skipped local persistence, cloud
smoke, and manual provider/context checks remain unverified. Synthetic domain
providers remain evaluation fixtures rather than production integrations.
