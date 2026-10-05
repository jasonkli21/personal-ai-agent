# Shared implementation and verification contract

Reconciled 2026-10-05. This file consolidates the repeated delivery, negative-test and evidence requirements from all detailed plans. It does not replace their product commitments or authorize implementation during Phase 0.

## Authority and implementation boundaries

- Actual code/tests and accepted ADRs define existing behavior. The top-level handoff defines intended scope; detailed plans define execution. Read the project brief, architecture, relevant existing phase guides and the comprehensive Phase 0 review before coding.
- Inspect git status and preserve unrelated changes. Extend services, repository protocols, domain modules, provider boundaries and deterministic fakes. Keep routes/UI thin; avoid rewrites, aesthetic module moves and parallel frameworks.
- Owner comes from verified server identity. Application/workspace/entity labels, client capabilities and provider choice do not confer authorization. Foreign IDs retain safe not-found behavior. Legacy records are standalone/null only, never implicitly shared across apps.
- Domain applications own domain schemas, records, transactions and validation. Core orchestration calls typed bounded providers/APIs, never domain databases. AI memory, conversation summaries, external evidence and generated artifacts remain distinct state classes with their own authority/lifetime.
- Shared context preparation preserves mandatory newest input, complete active-branch history, parent/supersedes links and lossy branch-scoped summary coverage. Every future generation path uses this preparation; current direct memory extraction is a documented Phase 8 gap. No model call bypasses permission, sensitivity or resource admission because it is called counting, embedding, planning, summarization or evaluation.
- SDK types remain inside provider/storage implementations. Separate generation, counting and embedding capabilities; do not require an oversized universal protocol. Retain Gemini vector compatibility until an explicit evaluated migration. Firestore is operational/vector storage; GCS is a private artifact tier, with non-atomic cross-store reconciliation.
- Strict-free hard filters precede selection/optimization and remain outside learned policy. No paid overflow, weakened privacy, ineligible counting/embedding disclosure, unknown-policy sensitive call or silent provider/billing switch. Known exhausted/cooldown routes cannot be selected. Volatile model/account/quota/privacy facts are versioned configuration/observations, not code constants.
- Reassembly on fallback stays within the same permitted sources and recounts for the target endpoint. Do not concatenate different providers after visible deltas. Unknown side effects remain fenced. Mutations are typed proposals validated and executed by the authoritative domain, with explicit user confirmation and durable idempotency/reconciliation.
- ChatGPT is an explicit local/user-controlled lane, excluded from automatic strict-free routing. Reusable credentials never enter browser/cloud persistence, traces or exports. Client-reported completion is labelled untrusted attribution, not proof of provider billing or domain authority. Distribution, plan-only billing and supported-client transport need verification before live enablement.

## Test obligations for each package

Use deterministic synthetic fixtures, fake repositories, clocks, counters, provider transports and LLM clients. Assert actual provider/field selections and exclusions, not merely that a class exists. Each new contract covers valid, missing/malformed, denied, unavailable, oversized and unknown/forward-version inputs. Relevant paths also cover concurrency, replay/conflict, deadline/cancellation, crash/partial persistence, disabled defaults and foreign scope. Unsupported operations fail explicitly rather than silently coerced.

Context tests include irrelevant, stale, conflicting, sensitive and over-budget sources; authority, provenance, effective sensitivity and permission dependencies must survive the whole path. Unauthorized data must not be fetched first. Inspection is read-only metadata by default and makes no provider calls. Persistence tests cover actual scope filters, indexes, operation identity, terminal states, retention/export/deletion inventory and recovery fences.

Record baseline fixture metrics before any optimization depends on them. Promotion criteria include quality/support, omission/over-fetch, privacy/authority regressions, token/quota use, latency and resource/storage effects as appropriate. A model judge is supplementary. Learned planning/routing stays gated until paired evidence demonstrates benefit; deterministic fallback/rollback remains available.

## Commands and evidence levels

Follow the root README: activate `backend/.venv`, use Python 3.11+, uv 0.11.13, Node 22 and pnpm 11.19.0. Repository targets currently exist for:

```sh
make backend-test
make backend-lint
make context-eval
make memory-eval
make memory-lifecycle-eval
make research-eval
make decision-eval
make domain-eval
make iterative-research-eval
make itinerary-proposal-eval
make frontend-test
make frontend-lint
make frontend-typecheck
git diff --check
```

Run only affected suites and evaluations, except Phase 28's integrated matrix. Changes spanning both applications require backend tests/lint and frontend tests/lint/typecheck. Dependency/build changes also require affected package/image builds when the environment is available. Deployment-script changes require `bash -n infrastructure/gcp/deploy.sh`. Documentation-only work requires content/link review and `git diff --check`.

There is currently no general routing, artifact or local-bridge evaluation command. Implement a real runner and document its invocation when its phase needs one. Existing pytest provider/Firestore tests may use fakes; their filenames do not establish external execution. CI currently runs seven evaluation targets; the itinerary-proposal target exists separately and needs integrated CI reconciliation in Phase 28.

Distinguish five evidence levels: deterministic offline; Firestore Emulator; live provider/OAuth; deployed cloud/domain/browser/native; external documentation/account facts. Each report records date, code revision, configuration/schema/policy/model versions, command, pass/failure/skip and unresolved gates. Official documentation verification is not an account compatibility test. No credentials, personal chats, private documents or private health/finance data belong in committed fixtures/reports.

## Completion and enablement

Each implementing phase produces actual interface/file maps, relevant tests/fakes, implementation guide and release evidence. Update ADRs only for durable behavioral decisions; routine details do not need a new ADR. Scope-changing discoveries must be reconciled at the source and propagated, not silently introduced in implementation.

Local implementation completion and live enablement are separate milestones. A local phase may record external checks pending while keeping the affected capability unavailable; all intended work packages remain tracked. Existing Phase 9 physical deletion, full owner migration, provider-data review and operational release closeout are still required. Next-scope Phases 11/12 supply accounting/artifact obligations and 28 requires integrated closure; no new numbering erases that work. Do not treat a skipped external test as passed or infer production/private-data readiness from fakes.
