# Phase 21 implementation evidence — deterministic task-aware routing

**Date:** 2026-10-08 (America/Los_Angeles).

**Tested revision:** working tree based on `c65fa7a` (`Fix artifact lifecycle review findings`). Runtime/config/test SHA-256: `bd53b101562292c766c4074c30b4b6eb6e2372b14e9dbffbed4ad1746d87603c`.

The digest covers sorted unique Git tracked/non-ignored file paths under `backend/src`, `backend/tests`, `frontend/src`, `frontend/tests`, plus `backend/pyproject.toml`, `backend/uv.lock`, `.github/workflows/quality.yml` and `Makefile`. For each file it hashes its UTF-8 relative path, a NUL byte, then the binary SHA-256 of its contents. Markdown documentation is excluded.

## Delivered local boundary

| Package | Delivered behavior |
| --- | --- |
| P21.0 task/strategy/plan contracts | `routing/phase21.py` defines the known task taxonomy, typed requirements and quality policy, freshness-bounded runtime/quality/signal facts, safe request metadata, strategy input/result identities, endpoint-specific preparation, quota reservation references, explicit provisional/ready plans, and bounded observation/event records. `RoutingStrategy` is replaceable; the deterministic baseline ranks by configured priority and opted-in fresh evidence with a stable profile-ID/version tie break. |
| P21.1 admission/finalization | `RoutingDecisionService` applies Phase 18 profile admission and current runtime, quality-floor, authorization/credential, health/cooldown, and exhaustion filters before strategy input. Rejected profiles and priorities cannot be selected by a strategy. Finalization checks preparation identity and fit, count confidence/schema where required, fresh dispatch revalidation, source authorization, current profile, and all applicable quota buckets. The service has no provider client and returns a ready plan only after its lifecycle event is durable. |
| P21.2 observation/replay | `persistence/postgres_routing_observations.py` and migration `020_routing_decisions.sql` store scoped immutable decision facts with append-only bounded outcome events, linked reselection lineage, request/run/time/invocation/attempt/evaluation lookup, owner deletion fencing, and 90-day-bounded replay. Explicit overflow records are incomplete/no-route and are not silently truncated. Owner export inventory includes these canonical rows; scheduled maintenance purges expired observations. |
| Tests and packaging | `tests/test_routing_phase21.py` covers chat, research synthesis, and structured proposal task profiles through the shared service, admission-before-strategy, freshness and quality filters, replay, overflow, fit/revocation/reservation checks, finite linked reselection, SQL repository scope/lineage/list behavior, export inventory and migration contracts. `tests/persistence/test_routing_decisions.py` adds opt-in real-Postgres migration, scoped access, owner-fence, expiration and purge cases and is included in the existing Postgres CI step. The built wheel contains the new routing modules and migration 020. |

The phase plan requires Phase 15's authoritative membership and end-to-end revocation acceptance before connecting request workflows to automatic endpoint selection. That prerequisite remains open. The implementation therefore delivers the reusable routing and persistence core without wiring chat, research, proposals, or other actual workflows to it. Current app workflows remain Gemini-only; actual producing-endpoint attribution, shared builder integration, and Phase 19 invocation/reservation integration are not claimed. This follows the plan's stated work ordering and is a material remaining Phase 21 acceptance gate.

The repository-root `README.md` was reviewed. No README edit was needed because this local internal foundation does not change user-visible runtime capability, setup, supported providers, or deployment status.

## Verification

Environment: local macOS, existing backend Python 3.11.15 virtual environment and pinned dependencies. No provider or cloud calls were made.

| Command/check | Result |
| --- | --- |
| `.venv/bin/python -m pytest -q tests/test_routing_phase21.py tests/test_phase9_controls.py tests/persistence/test_routing_decisions.py` (run from `backend/`) | **Passed: 37 tests; skipped 2 opt-in Postgres tests** without `PERSISTENCE_TEST_POSTGRES_DSN`. One existing Starlette/httpx deprecation warning. |
| `.venv/bin/python -m pytest -q` (run from `backend/`) | **Passed: 994 tests, 48 skipped.** One existing Starlette/httpx deprecation warning. |
| `.venv/bin/python -m ruff check .` (run from `backend/`) | **Passed.** |
| `UV_CACHE_DIR=/tmp/personal-ai-phase21-uv-cache uv build --no-build-isolation` (run from `backend/`) | **Passed:** source distribution and wheel built. Wheel contents include all Phase 21 Python modules and `020_routing_decisions.sql`. |
| Documentation links/content review | **Passed:** Phase 21 links/status and the Phase 15 workflow gate were checked against code, plan and tests. |
| `git diff --check` | **Passed.** |
| Frontend tests/lint/typecheck/build | **Not run:** this phase changes no frontend files or UI behavior. |

The offline tests use synthetic profiles and fake Postgres behavior. They establish local contracts only.

## Open acceptance and verification gates

- Phase 15 authoritative membership and end-to-end revocation through derived context remain incomplete. Automatic workflow selection and actual turn attribution remain gated; app workflows are Gemini-only.
- Migration 020 was packaged but not applied. No real Postgres/DynamoDB engine or migration race/integration test was run locally. Docker and the configured persistence integration DSNs were not exercised.
- The two opt-in Phase 21 real-Postgres cases are part of the CI persistence command, but no CI run is claimed here.
- No live provider, account/tier, privacy/data-use, quota/billing, cloud IAM, or deployed behavior was checked. Strict-free attestations, reservation controls, and the current fake runtime facts do not establish live eligibility.
- Linked reselection and lifecycle logic are tested offline. Crash reconciliation across canonical P decisions, Phase 19 reservations/attempts, and future D turn attribution remains unverified and depends on later workflow integration.
- No dedicated backend type-check target is defined in the repository's Makefile; Ruff, tests, and package build are the applicable local backend checks.

Phase 21's **local deterministic routing foundation is delivered**. Full phase acceptance remains open at the explicit Phase 15 prerequisite and external persistence/provider/workflow gates. See the [guide](phase-21-implementation-guide.md) and [current state](../current-state.md).
