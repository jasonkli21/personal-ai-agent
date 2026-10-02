# Phase 5 source-grounded research — 2026-10-02

Status: implemented and verified locally, default-off. The user explicitly
requested plan review, documentation updates, implementation and scoped commits.
The [reviewed plan](../phase-5-implementation-plan.md) and
[guide](../phase-5-implementation-guide.md) document the accepted bounded scope.

Tested implementation revision: `1ed99740255293e2e5e9662227152d7850ed0d05`.
Checks were run on the source content committed at that revision; this release
record is a subsequent documentation-only commit. No cloud/provider acceptance
is inferred from the offline suite or synthetic browser walkthrough.

## Commit grouping

| Commit | Delivered scope |
| --- | --- |
| `64971b2` | Plan review: execution/replay, atomic aggregates, licensed snippet policy, enforceable excerpt grounding and verification gaps |
| `403a79b` | Typed contracts, settings, owner-scoped atomic repositories, URL/content policy, ADR and index exemptions |
| `49432de` | Search provider, extraction/dedupe/TTL, selection, shared context, synthesis, SSE/API, full-pipeline fixtures and failure/disconnect tests |
| `1ed9974` | Research UI/proxy/client, request-time deployment gating, recovery and stale-answer handling, append-only attempt starts/terminals, cancellation-write ordering, inspection, CI, opt-in checks and handoff docs |

## Verification results

Environment: Python 3.11.15 in the backend virtual environment; uv 0.11.13;
Node 22.23.3 on PATH and pnpm 11.19.0 for final frontend verification. A temporary
Node 22 distribution from nodejs.org was checksum-verified because the bundled
runtime initially supplied Node 24. No repository runtime dependency changed.

| Check | Result |
| --- | --- |
| `make backend-test` | 323 passed, 12 opt-in external tests skipped; includes 53 offline Phase 5 tests |
| `make backend-lint` | Passed |
| `make context-eval` | Five synthetic fixtures passed |
| `make memory-eval` | Fourteen synthetic fixtures passed |
| `make memory-lifecycle-eval` | Twenty fixtures × three variants passed (60 results) |
| `make research-eval` | Thirteen synthetic full-pipeline fixtures passed |
| `make frontend-test` | 48 passed, including 14 new research client/proxy/UI tests |
| `make frontend-lint`, `make frontend-typecheck` | Passed with Node 22 on PATH |
| `make backend-build` | Source distribution and wheel built successfully |
| `make frontend-build` | Production build passed with Node 22 on PATH |
| Locked backend `uv sync` | Passed; direct HTTP client dependency declared and lockfile checked |
| `bash -n infrastructure/gcp/deploy.sh` | Passed |
| Documentation relative links/content, `git diff --check` | Passed |
| Docker image builds | Not run: Docker executable unavailable; CI remains configured for both images |

Existing non-failing warnings: Starlette's httpx TestClient deprecation; Vite's
CJS API deprecation; Next.js reports the existing ESLint configuration lacks
its Next plugin. These do not change the recorded pass results.

The [checked-in evaluation report](phase-5-research-evaluation.json) contains
synthetic query/source links, source/exclusion/citation counts and terminal
outcomes. Its baseline records that ordinary chat has no fresh external evidence;
this corpus does not establish broad semantic research quality. No actual
provider content, credentials or personal queries are included.

## Synthetic browser verification transcript

Performed locally during integration verification with the API on loopback
port 8005 and Next.js on port 3005. Backend: research enabled, memory repository,
fake search/fake synthesis, inspection enabled. Frontend gates matched. This
exercise required no Firestore, Brave or Gemini connection.

1. Open `/research`; the question/freshness form is available.
2. Enter **Synthetic research evidence?** and submit.
3. The separate SSE progress completes; the page shows **Cited evidence** and
   explicitly labels the result **Synthetic demo**.
4. The excerpt is: “This is synthetic research evidence for an offline demo.
   It makes no claim about the real world.” It has adjacent `[1]` and a source
   link to `https://example.org/synthetic-research`, with observation and
   24-hour expiry timestamps. The fixture URL was not fetched.
5. Reopen the saved session URL; the same durable-in-process result is shown.
6. Inspect research; it reports one query/source/evidence, `select-v1`, estimated
   token count, selected evidence ID, relevance/provider-order/freshness scores
   and no exclusions. The inspection path performs no search/model calls.
7. Close the temporary browser tab and stop both test servers. The in-memory
   demo is deliberately disposable and does not prove restart persistence.

A local screenshot was saved to `/private/tmp/phase5-research-demo.jpg` for the
session handoff; it is not a repository dependency or persistent cloud artifact.

## Local acceptance review and remaining gaps

The local contract checks prove owner isolation, matching-request replay and
conflicting-key rejection, single-run fencing, immutable attribution, exact-content
merge provenance, conservative retention of disagreements, explicit expiry,
context/output bounds, safe adapter/LLM failures, malformed/unknown/altered
citation rejection, terminal replay, ASGI/proxy cancellation and native-cancellation
ordering against an in-flight storage write. Research does not resolve chat or
memory storage. Existing chat/memory suites remain passing.

The result format is cited literal evidence excerpts with fixed uncertainty
language. It deliberately does not claim unrestricted prose entailment,
independent factual verification, semantic contradiction resolution or learned
ranking. Lexical selection can miss relevant paraphrases, and API retrieval
time is not publication time. Optional planner/reranker protocols are replaceable
and validated; no extra model implementation was required for this phase.

Still pending:

- Real Firestore/emulator transaction behavior, API restart persistence and
  provisioning/readiness of research field-index exemptions.
- Suitable Brave storage/AI-use rights, operator retention/deletion procedure,
  secret provisioning and actual provider smoke/attribution/timeout/quota checks.
- Real Gemini counting and strict synthesis-output acceptance/quality.
- Deployed browser/proxy cancellation, spend limits and distributed provider rate
  controls. The process-local limiter does not enforce project-wide quotas.
- Docker image verification on a Docker-capable host/CI.
- Earlier Phase 1–4 provider/emulator/deployment verification gaps.

The two Phase 5 external tests are opt-in and were not run. Research has no
authentication and stays off in the public bootstrap. Expiry is eligibility,
not automatic deletion; operators must retain/delete only as permitted by their
provider agreement. No Phase 6/8 work is included or authorized by this handoff.
