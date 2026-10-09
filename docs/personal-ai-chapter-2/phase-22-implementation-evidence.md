# Phase 22 implementation evidence — Cross-provider task evaluation matrix

Date: 2026-10-09
Tested revision: `70519cf-working-tree`
Status: Local harness, persistence contracts, and offline integration implemented. Live-provider and target-store acceptance remain open.

## Delivered boundary

- `ProviderMatrixRunner` iterates generic task fixtures and registered endpoint profiles. It uses the shared Phase 12 `ContextBuilder` with a versioned estimated counter, then routes through Phase 21 dispatch; Phase 19 reservation/settlement remains authoritative for physical attempts.
- The run-scoped quality gate is bound to one fixture, request ID, exact prepared-message digest, run, task configuration, endpoint configuration, quality profile, policy, and evidence source. P21 rejects a prepared-message digest mismatch before P19 reservation. The gate waives only missing measured-quality evidence; other P21 eligibility and authorization checks still apply.
- Deterministic fixtures, metrics, evidence identities, explicit promotion thresholds, and freshness checks are defined in `personal_ai.evaluation.provider_matrix` and its contracts. Synthetic-only cases cannot produce live quality profiles.
- Postgres migration 023 and `PostgresProviderMatrixRepository` own compact run/case summaries, exact case gates, immutable quality-profile versions, and explicit publication. Case identity locking and stable run ordering protect concurrent duplicate measurements; unresolved P19 sends block subsequent runs.
- Raw output retention defaults to deny. Approved output-only batches use the Phase 20 artifact service and typed `evaluation-raw-outputs-v1` schema. Fixture prompts and reference outputs are not written to summaries or raw-output batches.
- The runner uses the existing neutral generation adapter and has no provider-specific dispatch logic. A generic additional provider/task is exercised by the harness test.

## Verification performed

| Check | Result |
| --- | --- |
| `PATH=backend/.venv/bin:$PATH make backend-test` | **Passed:** 1,051 passed, 70 skipped, 1 existing Starlette/httpx deprecation warning. Includes deterministic matrix scoring and synthetic harness through P21/P19. |
| `PATH=backend/.venv/bin:$PATH make backend-lint` | **Passed:** Ruff reports all checks passed. |
| `UV_CACHE_DIR=/private/tmp/personal-ai-phase22-uv-cache PATH=backend/.venv/bin:$PATH make backend-build` | **Passed:** sdist and wheel built. The wheel contains the runner, fixture JSON, and migration 023. |
| `git diff --check` | **Passed** after final implementation and evidence updates. |
| Local links in updated documentation | **Passed:** all local links in the router, current-state snapshot, Chapter 2 overview, guide, and evidence resolve. |
| Backend type check | No backend mypy/pyright/ty target is configured in this repository. Frontend files were not changed, so frontend checks were not applicable. |
| Postgres opt-in tests | **Skipped/unverified:** `PERSISTENCE_TEST_POSTGRES_DSN` is unset and Docker is unavailable. Three provider-matrix Postgres tests cover persisted P21/P19 dispatch, unresolved-send denial, and concurrent case arbitration when run in the persistence environment. |

The initial plain `make backend-build` could not initialize uv's cache under the sandbox-protected home directory. Re-running with `UV_CACHE_DIR` under `/private/tmp` completed successfully.

## External and integration gates

- Migration 023 was packaged but not applied to PostgreSQL; SQL behavior and the advisory-lock race test remain unverified against a real database here.
- No Gemini, Groq, or Cloudflare provider call was made. Provider account/tier/privacy/quota facts remain registry-controlled, and alternate live paths remain disabled by current configuration because authoritative same-endpoint counters and preflight facts are not established.
- No GCS/IAM or provider output-rights check was performed. Live raw retention has no default approval authority and remains off unless an exact run/profile/source/account/expiry approval is supplied.
- No API/UI or scheduled job invokes the runner. Phase 15 end-to-end revocation and deployed service identity acceptance remain prerequisites for any live job composition. The local fixed system evaluation scope is only a local internal boundary; it does not establish deployed identity.
- No cloud, emulator, deployment, or production-security behavior is claimed as passed.

## Architecture audit and plan review

The phase reuses the established Phase 12 context builder, Phase 18 endpoint registry, Phase 21 route/finalize/dispatch path, Phase 19 attempt and quota accounting, and Phase 20 artifact service. Run/profile summaries have one Postgres owner; provider attempts remain owned by P19; optional raw bodies remain owned by P20. The evaluation gate cannot relax strict-free cost, authorization, privacy, capability, limit, quota, deadline, or one-use dispatch checks. Exact endpoint/task/policy/scorer/revision identities prevent quality evidence from carrying across configuration changes.

The harness adds no application/provider branches, duplicate quota ledger, direct provider SDK, alternate send path, or unbounded retry path. Runs are sequential and bounded; a pending, unknown, or timed-out physical attempt is not retried by a new run. Quality publication is explicit and uses same-manifest baseline comparison rather than automatic promotion. Later domain phases can supply their implemented task contracts and synthetic fixtures through the same runner; this phase adds no domain authority or domain-specific fixture behavior.

The root `README.md` was reviewed and left unchanged: its existing overview already describes the internal evaluation capability and opt-in artifact tier, while Phase 22 adds no UI, user-facing provider support, or application workflow routing. The documentation router, Chapter 2 overview, current-state snapshot, guide, and this evidence record were updated.
