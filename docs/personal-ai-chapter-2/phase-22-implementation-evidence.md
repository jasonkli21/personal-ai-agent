# Phase 22 implementation evidence — Cross-provider task evaluation matrix

Date: 2026-10-09
Tested revision: `894d255-working-tree-19088ef89105`
Status: Local harness, persistence contracts, and offline integration implemented. Real PostgreSQL, live-provider, and deployed-identity acceptance remain open.

## Delivered boundary

- The packaged evaluation suite is versioned and contains 20 diverse synthetic-public fixtures. Each fixture exposes source IDs required by its scorer, and the loader validates suite, scorer, and sample-floor compatibility.
- Generic scoring owns schema, declared hard constraints, and privacy checks. Registered versioned scorers own task semantics. A numeric-result fixture verifies a different output schema and scorer without changing matrix orchestration.
- Absolute task-floor qualification is separate from comparative promotion. Comparison publication binds to the exact baseline endpoint and configuration declared in the run. The repository currently has no authoritative production single-provider baseline setting; callers can identify a reference configuration, but the code does not claim it is the current production baseline.
- Preparation evidence distinguishes the endpoint's registered counter capability from the counter actually used. Endpoint serializer identity, prepared input digest, actual estimated counter, suite/scorer/manifest, output bound, and source-tree revision are included in run or quality identity. Unsupported seed control remains `null`.
- Identical run IDs with identical configuration resume saved terminal cases. Deterministic P21 request identities and P19 one-use dispatch/unresolved-attempt fences prevent an already-settled or ambiguous send from being repeated. Recovery is caller-driven; the caller must retain and retry the same run ID.
- Only generation-capable profiles enter the matrix. Internal routing failures are recorded as failed cases. Compact summaries preserve per-endpoint artifact publication outcome and safe artifact IDs; raw bodies remain Phase 20-owned.
- The harness keeps strict-free admission, authorization, privacy/capability/limit filters, quota reservations, and P19 attempt settlement in force. It adds no API/UI wiring or live evaluation command while Phase 15 and deployed identity gates remain open.

## Verification performed

| Check | Result |
| --- | --- |
| `PATH=/Users/jasonkli/projects/personal-ai-system/backend/.venv/bin:$PATH make backend-test` | **Passed:** 1,058 passed, 71 skipped, one existing Starlette/httpx deprecation warning. The four provider-matrix PostgreSQL integration tests were skipped because no isolated DSN was configured. |
| `PATH=/Users/jasonkli/projects/personal-ai-system/backend/.venv/bin:$PATH make backend-lint` | **Passed:** Ruff reports all checks passed. |
| `UV_CACHE_DIR=/private/tmp/personal-ai-phase22-uv-cache PATH=/Users/jasonkli/projects/personal-ai-system/backend/.venv/bin:$PATH make backend-build` | **Passed:** source distribution and wheel built. |
| `git diff --check` | **Passed** after the implementation and documentation edits. |
| Updated documentation links | **Passed:** local links in the current-state page, guide, and evidence were checked. |
| Backend type check | No backend mypy/pyright/ty target is configured. Frontend files were not changed. |
| PostgreSQL integration | **Unverified:** `PERSISTENCE_TEST_POSTGRES_DSN` is unset and Docker is unavailable. A temporary PostgreSQL 16 cluster could not initialize because the host denied a SysV shared-memory allocation (`shmget`); no migration or real-engine concurrency test ran. |

The first `make backend-test` invocation used a relative virtualenv path that became invalid after Make changed into `backend/`; the rerun used the absolute virtualenv path and completed successfully. The backend build used a cache under `/private/tmp` to avoid the protected home cache path.

## External and integration gates

- Migration 023, PostgreSQL JSONB round-tripping, publication and quality lookup, and advisory-lock concurrency remain unverified against a running supported database. Opt-in tests now cover persisted P21/P19 dispatch, unresolved-send fencing, same-case arbitration, and absolute quality publication through P21 lookup when an isolated PostgreSQL DSN is available.
- The quality-publication persistence test uses fixture-backed fake generation to exercise database and P21 contract behavior. It does not establish live provider behavior.
- No Gemini, Groq, or Cloudflare provider call was made. Provider account/tier/privacy/quota facts remain registry-controlled; alternate live paths stay disabled until authoritative same-endpoint counters and preflight facts are established.
- No GCS/IAM or provider output-rights check was performed. Live raw retention remains default-deny and additionally requires an exact approval and a GCS-backed artifact store.
- No API/UI or scheduled job invokes the runner. Phase 15 end-to-end revocation and deployed evaluation identity acceptance remain prerequisites for a live job. The fixed local system evaluation scope does not establish deployed identity.
- The single-provider comparison baseline is caller-declared and configuration-bound. A versioned production baseline policy must be supplied by a trusted composition before comparative results can be represented as production-baseline evidence.
- No cloud, emulator, deployment, or production-security behavior is claimed as passed.

## Review follow-up

The independent review findings on suite size/fixture provenance, absolute floor qualification, scorer extensibility, preparation/counter identity, execution configuration identity, operation filtering, run restart behavior, baseline binding, artifact outcomes, and routing failure classification were addressed in code and offline tests. Added tests also caught and fixed endpoint serializer identity reuse across matrix cases, UUID sizing in raw artifact batching, batch-buffer reinitialization after a flush, and optional quality-identity validation for legacy P21 evidence. The dirty source-tree revision now includes a digest of tracked `backend/src` changes instead of using a generic working-tree marker.

The remaining significant review gate is real PostgreSQL execution. Automatic stale-run leasing/abort and production baseline configuration remain outside the current local runner contract and are documented as such; same-ID restart is the supported recovery path. Low-value runner decomposition and broader scope generalization were deferred to avoid adding abstractions without a current caller.
