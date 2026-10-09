# Phase 23 implementation evidence — Quota-aware routing

Date: 2026-10-09
Reviewed base revision: `ffb30154acadeae9b075667d46d76e03e97e1639`
Review patch SHA-256: `ad06c21aa52d53dacc33394423a81f1aa887c9ca44d2048868acc0f2b3ec755e`
Status: Local implementation and synthetic evaluation are complete. Workflow rollout and external acceptance remain gated.

The patch fingerprint is the SHA-256 of the binary Git diff against the reviewed base, excluding this evidence file to avoid a self-referential hash. The final commit SHA is recorded in the commit and reported with the review closeout.

## Review changes

- Routing now obtains runtime snapshots for all authorized candidates in one P19 transaction. It locks each applicable canonical quota window once, globally sorted by bucket ID, then locks endpoint health rows sorted by profile ID/version. This matches P19 reservation and settlement order and removes the cross-candidate deadlock cycle. Candidate sets exceeding 128 unique buckets fail closed before the P19 locks are acquired.
- Shared bucket facts contain only shared ledger state. Reservation units are stored on candidate-to-bucket requirements, so endpoints sharing one quota bucket can have different per-call costs without creating conflicting bucket facts.
- Zero-unit requirements no longer inherit uncertainty from an unknown bucket. Mixed known/unknown quota inputs preserve the mixed reason when they tie in ranking.
- New decisions use schema 5. Replay facts bind the strategy reference to its dependencies, implementation digest, configuration digest, and tie-break version. Schemas 2–4 remain readable; schema-4 edge requirements are reconstructed from its legacy bucket facts. Oversized decisions explicitly report replay facts unavailable instead of presenting stripped facts as replayable.
- The scarcity evaluator advances demand time across resets and freshness boundaries and applies promotion gates to each scenario as well as the aggregate. It reports per-scenario availability, quality, latency, quality-floor, hard-eligibility, and quota-conservation results.
- Added a real-PostgreSQL concurrency test for routing and finalization/reservation that exercises overlapping bucket sets and lock ordering. The test is opt-in and was not executed on this host because no PostgreSQL test DSN or Docker runtime is available.

## Verification performed

| Check | Result |
| --- | --- |
| `PATH=backend/.venv/bin:$PATH make backend-test` | **Initial full run passed:** 1,073 passed, 74 skipped, one existing Starlette/httpx deprecation warning. A final repeat had 1,072 passed, 74 skipped, and one unrelated itinerary timeout assertion fail (`0.360 s` observed against a `0.280 s` bound); that same test passed when rerun alone. All Phase 23 tests passed in both full runs. PostgreSQL persistence tests were skipped because `PERSISTENCE_TEST_POSTGRES_DSN` is unset. |
| `PATH=backend/.venv/bin:$PATH make backend-lint` | **Passed:** Ruff checks passed after fixing the test import order. |
| `UV_CACHE_DIR=/private/tmp/personal-ai-system-uv-cache make backend-build` | **Passed:** source distribution and wheel built successfully. |
| `PATH=backend/.venv/bin:$PATH make quota-scarcity-eval` | **Passed:** all configured scenario and aggregate gates passed across five scenarios; quality delta `-0.0225`, unavailable delta `0`, latency increase `8.333 ms/demand`, one protected send equivalent saved, and zero uncertain dispatches. |
| `git diff --check` | **Passed** after the final source, test, and documentation changes. |

The first default-PATH lint/evaluation invocation could not find `python`; rerunning with the repository virtual environment on `PATH` completed both checks. The build used a temporary UV cache path because the default cache is outside the writable workspace. The repeated full suite's sole failure is an existing elapsed-time assertion outside the changed files; its isolated rerun passed. No frontend files changed, so frontend checks were not run. No live provider, cloud, deployment, or production-security checks were performed.

## Architecture and correctness boundaries

- P19 remains authoritative for quota windows, reservations, health, and physical outcomes. P21 persists only bounded decision-time facts required for explanation and replay.
- Static eligibility, authorization, capability/privacy/cost mode, and quality constraints precede strategy input. P19 still performs the final atomic reservation before a physical send.
- Durable strategy provenance makes a replay fail closed when the current implementation, configuration, dependencies, or tie-break contract no longer matches the recorded decision.
- Unknown remaining capacity and reset horizons remain explicit. Evaluation reset/freshness transitions model elapsed demand time without inventing refreshed observations.
- Historical strategy identities remain readable for compatible records. Replay does not claim availability when decision facts were dropped due to the storage bound.

## Remaining verification and rollout gates

- Real PostgreSQL locking, concurrent capacity loss, JSONB replay, and migration behavior remain unverified here. Run the persistence integration suite against an isolated PostgreSQL DSN before accepting database concurrency behavior.
- No live Gemini, Groq, Cloudflare, BYOK, account/tier/privacy, cloud, deployment, or production-security checks were performed. Application workflows remain Gemini-only pending Phase 15 membership and end-to-end revocation acceptance.
- The synthetic evaluator is a local regression guard, not trusted production evidence. Strategy promotion remains subject to future evaluation against an independently governed baseline.

## Scope closeout

The change extends the existing routing and P19 accounting seams; it adds no second quota ledger, provider dispatch path, or database migration. Workflow routing remains gated by the existing Phase 15 authorization and revocation prerequisites. No root README update was needed because user-facing workflows and provider support did not change.
