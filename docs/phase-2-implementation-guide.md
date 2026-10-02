# Phase 2 implementation guide

The [Phase 2 plan](phase-2-implementation-plan.md) is implemented locally. Real
provider quality, emulator persistence, Docker CI, and deployed behavior remain
explicit verification gaps. Phase 3 has not started. The Phase 1 fixes that were
already in the working tree are preserved.

## Plan-to-code map

| Plan | Implementation | Evidence |
| --- | --- | --- |
| P2.0 | `evaluation/context-fixtures.json`, synthetic builders and baseline/result format | Five fixtures compare fixed-cap behavior to bounded selection, old facts, edited branch, and mandatory overflow |
| P2.1 | ADRs 0006–0008, `context/contracts.py`, validated settings | Contract/configuration, ownership, prefix/fingerprint tests |
| P2.2 | Estimated/fake counters and Gemini REST counting adapter | Exact-fit/overflow tests and installed-SDK mock transport verifies complete instruction/summary request shape |
| P2.3 | `context/assembler.py` | Chronological complete turns, mandatory prompt retention, exclusion and branch isolation tests |
| P2.4 | Append-only Firestore/in-memory summary repositories and bounded summarizer | First/incremental refresh, invalidation, output rejection, fallback, owner scoping, and lazy adapter failure tests |
| P2.5 | Reserved two-stage `ChatTurnService` preparation and dependency composition | Successful SSE order, durable overflow/retry, overlap, safe counting failures, and retained Phase 1 lifecycle tests |
| P2.6 | Read-only context endpoint and gated `/development/context` page/proxy | Disabled/default, enabled metadata, malformed/foreign/unknown resource, and no-write/provider-call tests |
| P2.7 | `make context-eval`, offline CI step, opt-in manual test, release record | Local quality/build results in the [release record](releases/phase-2-context-management.md) |

## Configuration and use

| Environment setting | Default |
| --- | --- |
| `MAX_CONTEXT_TOKENS` | 32768 |
| `MAX_RESPONSE_TOKENS` | 4096 |
| `CONTEXT_SAFETY_MARGIN_TOKENS` | 1024 |
| `SUMMARY_TRIGGER_TOKENS` | 12000 |
| `MAX_SUMMARY_TOKENS` | 2048 |
| `CONTEXT_INSPECTION_ENABLED` | false |

The application ceilings are deliberately smaller than typical model windows;
verify the configured model's capabilities when changing `AI_MODEL`. Settings
reject impossible reserves/thresholds. `MAX_PHASE_1_HISTORY_MESSAGES` no longer
controls request acceptance. The existing 20,000-character message/output bound
still applies separately from the token budget.

For local inspection, set `CONTEXT_INSPECTION_ENABLED=true` in both untracked
`backend/.env` and `frontend/.env.local`, restart both servers, and visit
`http://localhost:3000/development/context`. Paste a synthetic conversation UUID.
The report is labelled estimated and does not invoke any provider. Persisted
summary token counts additionally identify their original counter kind. Keep both
flags false in deployment; verify the inspector page/proxy/backend return 404.

`context_message_too_large` means the latest prompt plus mandatory instruction
cannot fit. The user message remains persisted without a streaming assistant;
the browser reloads it and offers edit-and-retry. Provider-count failure is a safe
503 before streaming. Summary failure permits smaller recent context when it
fits. Successful SSE event names/order and terminal durability remain unchanged.

## Summary lifecycle and persistence

`conversation_summaries` records store ID, owner/conversation IDs, content, ordered
source IDs, fingerprint, coverage ID, source/summary token counts, counter kind,
model, and UTC creation time. Owner+conversation lookup uses the provisioned
composite index. Compatibility is verified in code rather than trusting text;
newest compatible records are preferred and old records stay auditable.

Sources contain only contiguous complete turns on the active branch. Refreshes
are bounded synchronous operations under the conversation preparation
reservation. Each refresh may cover only part of omitted history when the source
input is large; later turns can extend it incrementally. Summary failure and
incomplete historical turns can lose older context. Summaries never promise
perfect recall, never become durable user memory, and use no background worker.

## Verification commands

Follow the locked environment setup in the root README, then run:

```sh
make backend-test backend-lint
make frontend-test frontend-lint frontend-typecheck
make context-eval
make backend-build frontend-build
bash -n infrastructure/gcp/deploy.sh
git diff --check
```

All automated tests/evaluations use synthetic inputs and require no credentials
or network. The provider adapter tests use the installed SDK with mocked HTTP
transport. This verifies the request contract, not a live Gemini endpoint.

With deliberately supplied Gemini settings, the additional manual check is:

```sh
cd backend
RUN_CONTEXT_MANUAL_TEST=1 python -m pytest tests/test_context_manual.py -q
```

It deliberately narrows the application budget for a synthetic long conversation,
checks provider-authoritative counts, a compatible summary with the old fact,
retained recent turns, and the streamed answer. Record model ID, configuration,
revision, date, and pass/fail only; do not record credentials or chat content.
