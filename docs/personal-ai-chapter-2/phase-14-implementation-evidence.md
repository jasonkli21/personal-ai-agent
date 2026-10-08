# Phase 14 implementation evidence — Provenance and context inspection

Date: 2026-10-07 (America/Los_Angeles)

## Tested tree and implementation

The initial implementation was verified in the working tree based on commit
`7571f40` (`fix(context): address phase 13 review`), before the Phase 14
implementation commit. A subsequent review correction pass adds preparation
deadline enforcement after trace persistence and explicit handling for
unsupported historical trace schemas. The tree includes bounded
`context-trace-v1` manifests, owner/app/
workspace-scoped DynamoDB repository code, trace capture during chat context
preparation, account-export inclusion, the development-only inspector API and
frontend, and status/contract documentation updates. The repository root
`README.md` was reviewed; no README-visible setup, provider, deployment, or
user-facing runtime fact changed, so no edit was required.

Traces omit prompts, source payloads, credentials, and hidden reasoning. Source
and item identifiers are fingerprinted. Per-conversation retention is capped
at 32 records and each serialized payload at 48 KiB. Inspection presents a
retained actual chat build separately from the estimated current view; absent
and unsupported historical schemas are reported explicitly. Traces include
version labels, not snapshots of the policy or source implementation bodies.
These labels are not immutable Postgres policy/source-version references, as
required by the Phase 10 storage contract. That is an unresolved local
acceptance gap: Phase 10 also says to preserve code-defined manifests and not
create a new registry product, so the version-reference design must be resolved
before Phase 14 can be marked complete. Standalone research, proposal, and
booking builds are not retained by this conversation trace store.

## Checks

The backend virtual environment was active for backend commands.

| Command | Result |
| --- | --- |
| `python -m pytest backend/tests/test_context_traces.py backend/tests/test_context_routes.py backend/tests/test_conversation_routes.py backend/tests/test_memory_integration.py backend/tests/test_account_data.py -q` | Passed: 52 tests. |
| `python -m pytest backend/tests/test_context_traces.py backend/tests/persistence/test_account_export.py -q` | Passed: 6 tests. |
| `make backend-test` | Passed: 714 passed, 26 skipped. The skips include opt-in local persistence, cloud smoke, and manual-provider/context cases. |
| `make backend-lint` | Passed. |
| `make context-eval context-plan-eval memory-eval memory-lifecycle-eval research-eval` | Passed: all five deterministic offline evaluation targets. Synthetic/fake results only. |
| `make frontend-test` | Passed: 98 tests across 19 files. |
| `make frontend-lint` | Passed. |
| `make frontend-typecheck` | Passed. |
| `git diff --check` | Passed. |

Following the independent review, the new preparation-deadline and historical
schema fixtures passed in the focused context suite (18 tests), and the changed
backend files passed Ruff. The review also checked request correlation, scope
checks, read-only inspection, export inclusion, and the accuracy of the initial
check record. It identified the immutable Postgres version-reference gap above;
current-state documentation now marks Phase 14 partial rather than complete.

Frontend checks used the bundled Node `v24.19.0` and pnpm `v11.25.0` runtime on
`PATH`, because the shell did not have `node` available. The root README's
pinned Node 22 and pnpm 11.19.0 were not available in this environment; that
version mismatch is recorded rather than represented as the pinned setup.

## Post-review correction verification

After the independent review, the deadline and historical-schema fixes were
verified in the working tree with these full checks:

| Command | Result |
| --- | --- |
| `make backend-test` | Passed: 717 passed, 26 skipped, 1 warning. |
| `make backend-lint` | Passed. |
| `make context-eval context-plan-eval memory-eval memory-lifecycle-eval research-eval` | Passed: all five deterministic offline evaluation targets; synthetic/fake results only. |
| `make frontend-test` | Passed: 98 tests across 19 files. |
| `make frontend-lint` | Passed. |
| `make frontend-typecheck` | Passed. |
| `git diff --check` | Passed after documentation updates. |

The independent review found two implementation issues, both fixed and covered
by tests: preparation deadlines now include trace persistence, and unsupported
historical trace schemas degrade to an explicit estimated view. Its third
finding identified the immutable Postgres policy/source-reference requirement.
That gap remains open because Phase 10 also forbids adding a new registry
product; repository status and guides now describe Phase 14 as partial.

## Remaining gates and limits

- The DynamoDB repository behavior was exercised with deterministic in-memory
  fakes; DynamoDB Local was not configured or run. This does not establish
  DynamoDB transaction behavior, deployed retention, IAM, or cloud operation.
- Live provider, Neon/AWS/GCP, production security, and deployed development
  gate behavior were not checked.
- Source and policy version labels are recorded, but immutable policy/source
  bodies are not snapshotted. Trace persistence covers conversation chat turns;
  standalone research, proposal, and booking manifests remain in-memory.
- Offline evaluation targets use synthetic/fake fixtures and do not verify
  provider behavior.

## Current review-closure verification

The later Phase 15 review-closure pass reran the full backend suite on a working
tree based on `78d1de9ae9f7b1a6c2b73b5eaabd642eae2bfafd`, including the Phase 14
trace persistence deadline and unsupported historical schema regressions:
735 passed, 26 skipped, and one warning (761 collected). Ruff and
`git diff --check` also passed. Exact commands and the scope limits are recorded
in the [Phase 15 evidence](phase-15-implementation-evidence.md). This does not
close Phase 14's immutable Postgres policy/source-version reference prerequisite
or its DynamoDB Local and external verification gates.
