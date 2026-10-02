# Phase 3 simple memory — local verification record

Date: 2026-10-02 (America/Los_Angeles).
Tested implementation tree: `f0c004cadf52cbe8d35c100255f7bc14427c1fb5`.
The checks below ran on the source tree committed at that revision; the synthetic
memory evaluation was also rerun after commit when writing this record.

Phase 3 is implemented and verified offline. Credentialed provider, emulator,
production vector-index and deployed acceptance remain pending. Gates default off;
Phase 4 has not started. See the [guide](../phase-3-implementation-guide.md),
[plan](../phase-3-implementation-plan.md) and [ADR](../decisions/0009-simple-attributable-memory.md).

## Commit boundaries

| Revision | Scope |
| --- | --- |
| `b517de8` | Memory contracts/decisions, fake and Firestore persistence, Gemini adapters, extraction/retrieval, bounded context/chat integration and backend tests |
| `f0c004c` | Gated inspector UI/proxy, config/index manifest/CI, failure evaluations, completion/timeout checks, budget accounting and implementation documentation |
| This evidence commit | Dated verification record and synthetic results |

## Environment and commands

Python 3.11 backend virtual environment; uv 0.11.13; Node 22.17.0; pnpm 11.19.0.
The bundled runtime was Node 24, so the final frontend checks used a temporary
Node 22 runtime downloaded from nodejs.org and verified against its official
SHA-256 manifest. Dependencies/lockfiles were unchanged. `pnpm exec node --version`
confirmed Node 22.17.0 for the frontend environment.

| Check | Result |
| --- | --- |
| `make backend-test` | 179 passed, 5 opt-in tests skipped |
| `make backend-lint` | Passed |
| `make context-eval` | All 5 Phase 2 synthetic fixtures passed |
| `make memory-eval` | All 14 Phase 3 synthetic fixtures passed |
| `make frontend-test` | 34 passed across 5 files |
| `make frontend-lint` | Passed |
| `make frontend-typecheck` | Passed |
| `make backend-build` | Source distribution and wheel built successfully; memory fixture JSON included in wheel |
| `make frontend-build` | Next.js production build passed |
| `bash -n infrastructure/gcp/deploy.sh` | Passed |
| Local documentation link/content review | Passed |
| `git diff --check` | Passed |
| Docker image builds | Not run; Docker unavailable on this host |

Existing non-failing warnings remain: FastAPI/Starlette's httpx test-client
deprecation, Vite's CJS API warning, and the Next.js ESLint plugin-detection warning.
No real credentials, private chats, production vectors, Gemini calls or Firestore
calls were used in automated tests/evaluations. SDK request tests used mocked HTTP;
Firestore adapter tests used mocked client/RPC objects.

## Acceptance coverage

Shared synthetic fixtures exercise preferences across separate conversations,
matching episodic observations, explicit user generalizations, corrections,
newer temporal statements, irrelevant semantic neighbors, duplicate extraction,
edited source branches, foreign owners, whole-record context exclusion,
sensitive-statement rejection, embedding/retrieval failure and no-match behavior.
The [result artifact](phase-3-memory-evaluation.json) records baseline/selected IDs,
fake model/dimension class, candidate scores, created/skipped IDs, safe reasons and
context budgets. Results are deterministic and contain no private text/vectors.

Repository/provider tests cover type/content/confidence/time/vector/schema validation,
owner isolation, deterministic identities/order, active-only compatible vectors,
atomic source/ancestor checks, SDK embedding batching/task types/schema bounds,
and safe timeout/error translation. Live index quality is not inferred from these tests.

Integration tests verify the unchanged SSE order, query persistence before
retrieval, normal/regenerate/edit branch paths, retrieval/embedding/counting/budget
fallback, successful post-terminal extraction and extraction/provider failure
isolation. Client cancellation before completion creates no memory. Late extractor
results cannot embed or persist; memory creation rechecks source state. A long
conversation test includes a compatible Phase 2 summary, whole memory records,
recent complete turns and the latest user prompt within one counted budget.

Read-only inspection tests verify gates, supplied-ID provenance, selected versus
excluded records, ownership, malformed/missing IDs and absence of provider calls,
raw content or writes. It estimates fit for supplied records; it does not assert
semantic relevance or recreate an earlier live request.

## Remaining verification and limitations

- Run the three opt-in memory tests described in the guide: synthetic Gemini
  embedding/extraction, emulator persistence/idempotency, and an actual streamed
  synthetic turn followed by cross-conversation retrieval. They remain skipped.
- Provision the configured composite vector index, wait for READY, and verify
  production KNN/threshold behavior. Index candidates are bounded; deterministic
  application sorting applies to returned candidates. Exact ties at the index
  cutoff and live embedding relevance need credentialed verification.
- Recheck deployed SSE cancellation and post-terminal extraction lifecycle.
  In-process extraction can be skipped by disconnect/process termination and has
  no durable queue or replay guarantee. Commit acknowledgement failures can be
  ambiguous; deterministic IDs permit safe retry.
- Earlier Phase 1/2 emulator, live provider, Docker CI and deployment checks remain
  open. This implementation does not close them using fake tests.
- Exact excerpts and conservative first-person markers intentionally miss many
  plausible memories; sensitive-category deny rules are not exhaustive. Review
  provider-data suitability and ownership/authentication before personal use.
- Current requests/corrections take precedence over historical statements. Older
  independent statements remain auditable and potentially eligible; no automatic
  contradiction resolution, supersession, editing, decay or forgetting is added.
- No authentication, search/evidence, domain agent, consolidation or worker/Pub/Sub
  behavior was introduced. Normal bootstrap deploys explicitly disable all memory
  gates and omit optional memory-index provisioning.
