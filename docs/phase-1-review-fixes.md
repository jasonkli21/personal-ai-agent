# Phase 1 independent-review remediation

The independent review of `7fb4ca2` identified six correctness defects and two
additional concurrency/cancellation gaps. The remediation remains within Phase 1;
no context budgeting, summaries, memory, or other Phase 2 behavior was added.

## Delivered corrections

| Finding | Correction | Regression evidence |
| --- | --- | --- |
| Disconnect leaves streaming state | Managed body iterator plus response teardown closes prepared turns, including before iteration starts; partial output is retained and terminal states are protected | `backend/tests/test_chat_stream_lifecycle.py` tests actual ASGI 2.3/2.4 send/disconnect paths |
| `.env` emulator host ignored | Each Firestore client receives its configured emulator endpoint and anonymous credentials without changing global environment | `backend/tests/test_firestore_storage.py` checks settings and actual lazy gRPC channel target |
| Failed replacement hides old branch | Transactional preparation validates the active snapshot and commits supersession plus new records together | Storage failure-injection tests verify rollback and preservation of the previous active path |
| Empty model response poisons history | Empty/whitespace-only output fails safely instead of becoming completed context | Conversation route tests verify failure and later usable turns |
| Lazy Firestore errors escape mapping | Query construction and iteration occur inside the typed storage error boundary | Adapter tests inject query construction and lazy iteration failures |
| Premature SSE EOF accepted | Parser requires a valid terminal event and cancels/releases its reader on completion or failure; UI retains partial text with retry | `frontend/src/lib/api.test.ts` and `frontend/src/app/page.test.tsx` |
| Overlapping turns use inconsistent context | Fresh active streams and stale snapshots reject mutations with HTTP 409; preparation is serialized at the Firestore transaction boundary | Concurrent-snapshot and overlap tests |
| Browser abort not explicitly forwarded | UI unmount aborts its request; incoming request abort and downstream body cancellation abort/cancel the proxy's upstream fetch/reader | `frontend/src/lib/conversation-proxy.test.ts` and UI unmount test |

Regenerate/edit-and-retry build model context only from the retained prefix and
replacement prompt. History caps apply to that context rather than the discarded
branch. Old content remains available for audit, and already-superseded records
are excluded from replacement writes so repeated retries do not exhaust the
Firestore transaction write limit.

An abandoned streaming placeholder is recovered on the next mutating request
after its age exceeds `REQUEST_TIMEOUT_SECONDS + 60` seconds. Recovery sets
`failed`/`turn_interrupted`; conditional terminal writes prevent a late old
request from changing it back to completed. Fresh streams continue to block
overlapping mutations. Recovery requires available storage; it is not a
background maintenance job.

Provider iteration stays in one task across all chunks so SDK timeout scopes
remain effective after partial output. Demand-driven iteration pauses while
a frame is delivered, and cleanup explicitly closes owned streams and per-turn Gemini clients;
injected shared clients remain caller-owned. Cleanup logs contain correlation
IDs/error classes rather than provider exception details.

## Verification boundary

See the [release record](releases/phase-1-vertical-slice.md) for exact local check
results. Offline adapter tests simulate Firestore transactions and failures;
they do not prove emulator or deployed Firestore behavior. Proxy tests simulate
request/body cancellation; they do not prove browser cancellation on Cloud Run.

The remaining [closeout plan](phase-1-verification-plan.md) still requires real
emulator persistence across API restart, opt-in Gemini smoke testing, Docker CI
results, and deployed synthetic browser flows. Phase 2 is now implemented locally; its later root-cut supersession and
preparation changes are documented in the [Phase 2 guide](phase-2-implementation-guide.md).
