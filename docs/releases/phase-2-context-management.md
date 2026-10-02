# Phase 2 context-management verification record

Date: 2026-10-01 (America/Los_Angeles).
Tested state: uncommitted working tree on `7fb4ca2`, including the previously
verified Phase 1 review fixes. No commit or cloud deployment is claimed.

## Implemented behavior

All normal, regenerate, and edit/retry model turns use one bounded context
assembler. User/branch persistence reserves the conversation before counting or
summary refresh; assistant creation checks the same reservation and snapshot.
Mandatory overflow preserves the user without starting a model stream, and the
browser reloads that user for edit/retry. Provider failures retain safe envelopes.

Summaries are synchronous, bounded, append-only working context for a contiguous
complete branch prefix. Source IDs/fingerprints prevent reuse after incompatible
rewrites. Invalid/failed summaries fall back to recent context. The development
inspector is read-only and gated in both applications; normal/deployed settings
explicitly disable it. No Phase 3 memory, search, embeddings, evidence, domain,
or worker features were added.

## Local checks

- Backend: **103 passed, 2 skipped**. Both skips are explicitly credentialed
  Gemini smoke/long-thread quality checks. Existing Phase 1 lifecycle regressions
  remain covered, with the superseded count-cap expectations updated for Phase 2.
- Backend Ruff: passed.
- Frontend: **32 passed**; ESLint and TypeScript passed.
- Next.js production build: passed.
- Backend locked source-distribution/wheel build: passed; wheel contains the
  synthetic evaluation fixture data. Offline lockfile validation passed.
- Deployment shell syntax, local documentation links, workflow YAML parsing,
  fixture/result JSON parsing, and diff whitespace: passed.

Backend checks used the locked temporary Python 3.11 environment at
`/tmp/personal-ai-build-check`; frontend checks used the bundled Node runtime and
existing locked dependencies. Docker is unavailable locally, so image builds and
CI execution were not performed. Mock HTTP tests exercise the installed Gemini
SDK's counting/generation transport and request shape, not a live provider.

## Offline evaluation comparison

The [structured evaluation output](phase-2-context-evaluation.json) contains fixture
version/configuration, baseline input count/result, selected/excluded IDs,
synthetic summary ID, estimated/provider counts, budget, result, and failure
reason. IDs refer to deterministic synthetic messages and ephemeral fake summary
records. Every provider-token count is null: no online call was made.

| Fixture | Phase 1 input messages/result | Phase 2 input estimate/budget | Summary | Result |
| --- | --- | --- | --- | --- |
| short-control | 5 / accepted | 73 / 180 | No | Passed; complete recent turns and newest prompt retained |
| beyond-fixed-cap | 61 / fixed-cap rejection | 171 / 180 | Yes | Passed; explicit old launch-color fact retained |
| old-fact | 25 / accepted without a token gate | 174 / 180 | Yes | Passed; old fact and explicit uncertainty retained |
| edited-branch | 25 / accepted without summaries | 171 / 180 | Yes | Passed; corrected city retained and obsolete branch excluded |
| oversized-newest | 3 / accepted without a token gate | Mandatory content cannot fit | No | Passed; expected `context_message_too_large` before model streaming |

These use deterministic fake word units and a fact-preserving fixture compressor.
They establish selection/provenance/overflow correctness; they do not establish
Gemini summary quality or promise perfect recall. All accepted fixtures remain
within budget and select no superseded message content.

## Remaining external verification

- Opt-in live Gemini authoritative counting, summary quality, old-fact answer,
  and model-specific capacity/output compatibility.
- Firestore Emulator summary/user persistence across API restart and real
  transaction/index behavior.
- Docker image builds and Python 3.11/3.12 CI results.
- Synthetic deployed browser streaming/retry/cancellation and confirmation that
  inspector page/proxy/backend are disabled.

Use the [Phase 2 guide](../phase-2-implementation-guide.md) for commands and the
[deployment guidance](../gcp-deployment.md) for deployment checks. The earlier
[Phase 1 closeout](../phase-1-verification-plan.md) remains relevant. Phase 2 code
is delivered locally; credentialed/deployed acceptance is still unverified.
Phase 3 was not started.
