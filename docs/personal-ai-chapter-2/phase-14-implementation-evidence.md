# Phase 14 implementation evidence — Provenance and context inspection

Date: 2026-10-07 (America/Los_Angeles)

## Tested tree and implementation

The implementation was verified in the working tree based on commit `7571f40`
(`fix(context): address phase 13 review`), before the Phase 14 implementation
commit. The tree includes bounded `context-trace-v1` manifests, owner/app/
workspace-scoped DynamoDB repository code, trace capture during chat context
preparation, account-export inclusion, the development-only inspector API and
frontend, and status/contract documentation updates. The repository root
`README.md` was reviewed; no README-visible setup, provider, deployment, or
user-facing runtime fact changed, so no edit was required.

Traces omit prompts, source payloads, credentials, and hidden reasoning. Source
and item identifiers are fingerprinted. Per-conversation retention is capped
at 32 records and each serialized payload at 48 KiB. Inspection presents a
retained actual chat build separately from the estimated current view; absent
traces are reported explicitly. Traces include version labels, not snapshots of
the policy or source implementation bodies. Standalone research, proposal, and
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

Frontend checks used the bundled Node `v24.19.0` and pnpm `v11.25.0` runtime on
`PATH`, because the shell did not have `node` available. The root README's
pinned Node 22 and pnpm 11.19.0 were not available in this environment; that
version mismatch is recorded rather than represented as the pinned setup.

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
