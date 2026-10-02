# Phase 4 experimental memory — local verification record

Date: **2026-10-02**. Tested source revision:
`978c50a542408f34ef74a60979dd57f0d48d16a2`. The documentation closeout commit
contains this evidence and phase-status updates; it does not change runtime behavior.

Phase 4 is implemented locally and verified offline. Fixed retrieval and all
mutation/inspection gates retain their disabled defaults. No experiment was promoted,
no cloud deployment ran, and Phase 5 remains unauthorized. External acceptance
checks below remain open. See the [guide](../phase-4-implementation-guide.md),
[plan](../phase-4-implementation-plan.md) and [ADR 0010](../decisions/0010-experimental-memory-lifecycle.md).

## Coherent commit map

| Commit | Delivered slice |
| --- | --- |
| `5a1792b` | Planning review, execution defaults and gap resolution |
| `d159834` | Lifecycle contracts, derived provenance, scoring configuration and storage foundations |
| `2b181b5` | Worker, retrieval, chat accounting and read-only inspection integration |
| `978c50a` | Bounded atomic transactions, dependency/reservation guards, crash/recovery behavior, measured variant fixtures, CI and opt-in checks |
| Documentation closeout | Guide, deployment/API/privacy boundaries, updated phase status and this evidence |

The Luna Extra High agent delivered the first two implementation commits. At the
user's later instruction it stopped after its current commit; the main session
completed the remaining implementation, acceptance fixes and verification.

## Recorded checks

The locked backend virtual environment and Node 22/pnpm environment were used.
All ordinary tests used synthetic inputs and external fakes.

| Command/check | Result |
| --- | --- |
| `make backend-test` | **270 passed, 10 skipped**; opt-in external tests skipped |
| `make backend-lint` | Passed |
| `make context-eval` | All 5 context fixtures passed |
| `make memory-eval` | All 14 Phase 3 memory fixtures passed |
| `make memory-lifecycle-eval` | **20 fixtures × 3 variants = 60 passed** |
| `make frontend-test` | **34 passed** |
| `make frontend-lint` | Passed |
| `make frontend-typecheck` | Passed |
| `make backend-build` | Source distribution and wheel built |
| `make frontend-build` | Next.js production build passed |
| `bash -n infrastructure/gcp/deploy.sh` | Passed |
| Index manifest JSON parsing, documentation links/content, `git diff --check` | Passed |

The full backend run included mocked installed-SDK Firestore transaction tests and
private worker transport tests. Backend output includes an existing Starlette/httpx
migration warning; frontend tooling reports existing Vite CJS and Next.js ESLint
plugin notices. They did not fail checks. Docker is unavailable on this host, so
container builds were not run; CI retains both container build jobs.

## Measured comparison and acceptance evidence

The [comparison JSON](phase-4-memory-lifecycle-evaluation.json) records fixture IDs,
variant/policy identities, candidates, rank/injected IDs, component scores, event IDs,
job attempts/states, lifecycle exclusions, budgets and safe failure reasons. It
contains no raw memory text, vectors, prompts or provider output. Results replay
exactly across repeated runs with an injected clock; shared fixtures are reused by
worker, policy, transaction and context tests.

- Fixed ordering retains Phase 3 baseline behavior under initial states; all
  existing context/memory evaluations pass. Scoring moves a slightly less similar
  explicit correction ahead of a higher-similarity episode in the named importance
  fixture. This is a specified ranking outcome, not a claim of general model quality.
- Consolidation creates fully attributed repeated-preference/episode records;
  consolidated retrieval injects one derived representation rather than both
  supporting sources. A budget fixture proves sources remain available when the
  derived record cannot fit. Mixed topics and branch-invalid sources create none.
- Zero fixture forbidden selections, automatic actions on ambiguous negation,
  protected forgetting, owner violations or budget violations were observed.
  Strict-newer corrections/temporal replacements supersede old state while exact
  original records remain unchanged. Low-confidence old episodes can be forgotten;
  internal reactivation requires valid sources and cannot undo supersession.
- Lifecycle/scoring/provider failure fixtures preserve empty or validated-fixed
  fallback. A scorer failure cannot revive a superseded source. Source mutation,
  current conversation reservation and unknown eligibility block lifecycle writes.
- Duplicate delivery and a crash after atomic apply before completion preserve a
  single derived record and source events after lease reclaim. Stale lease holders
  cannot write. Durability precedes publication, lost notification recovery is
  explicit and bounded, and replayed enqueue intent does not recreate mutable jobs.
- Mocked Firestore tests assert source/ancestor reads occur in the same transaction
  as event/projection/derived/reverse-link writes, with retry-free bounded RPCs and
  no writes after a stale source/reservation. Forgetting checks reverse dependencies
  again during commit. These tests do not certify a real Firestore transaction.
- All variants enter the existing context assembler; summary/recent-turn/newest-prompt
  preservation is tested under one total budget. Public chat/SSE contracts stay
  unchanged. Post-terminal accounting receives actual injected IDs; no inspection
  provider, queue or write calls are introduced.
- Lifecycle mutation routes are absent from the public API; the separate worker
  app is deployed privately in the script with authenticated Pub/Sub push and distinct
  identities. Source/security configuration was checked locally, not against Cloud Run.
- No search/evidence/entity/ranking/domain modules, end-user authentication,
  personal-data deletion/export or Phase 5+ feature was added.

## Remaining external verification

Not run, and not implied by the checks above:

- Real Firestore Emulator event/projection/job/consolidation persistence/restart,
  contention and projection rebuild checks. Opt-in entry points exist.
- Production Firestore vector/maintenance/event/job index readiness and actual KNN.
- Live Gemini embedding quality or provider-data suitability for memory/derived text.
- Pub/Sub authenticated delivery, actual Cloud Run IAM rejection of unauthorized
  callers, lease redelivery/crash recovery and topic/runtime permissions.
- Docker/container builds and deployed browser disconnect/cancellation propagation.
- Earlier Phase 1–3 provider, emulator and deployment closeout gaps.

The normal bootstrap remains public chat with fixed `local` ownership, unsuitable
for sensitive personal content. Private task transport does not fix that boundary.
Forgetting is a fallible retrieval policy, not deletion. No private chats, keys or
provider responses were used in fixtures or evidence. Keep all gates off until an
intentional synthetic external verification and provider/security review, and retain
these gaps in any future deployment handoff.
