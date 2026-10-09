# Phase 20 implementation evidence — private artifact tier

**Date:** 2026-10-08 (America/Los_Angeles).

**Tested revision:** phase-20 working tree based on `425bfde12c12d8f12721f1236f7f420977d4dc2d`, delivered in the accompanying single implementation commit. Runtime/config/test SHA-256: `5c12a0837cf7745b9646dc63ff3e58c49a40072c0a6bd2f7047e88ca8f33592d`.

The digest covers sorted unique Git tracked/non-ignored file paths under `backend/src`, `backend/tests`, `frontend/src`, `frontend/tests`, plus `backend/pyproject.toml`, `backend/uv.lock`, `.github/workflows/quality.yml` and `Makefile`, excluding Markdown. For each file it hashes UTF-8 relative path, a NUL byte, then the binary SHA-256 of its contents. Documentation edits do not change this runtime digest.

## Delivered local boundary

| Package | Files / interfaces and result |
| --- | --- |
| P20.0 | `artifacts/contracts.py`, `local.py`, `service.py`: scoped `ArtifactStore`/`ArtifactRef`, immutable store/key/generation/hash identity, gzip JSON/JSONL, raw/compressed/reference ceilings, numeric summaries, finite expiry, sensitivity/dependency contracts, deterministic fake adapters and stock/flow guards. Vectors and operational timeline state keep their existing stores. |
| P20.1 | `artifacts/gcs.py`, `persistence/postgres_artifacts.py`, migration `019_artifact_tier.sql`: private generation-precondition GCS adapter, compact Postgres metadata/CAS lifecycle, pending/ready/missing/deleting/deleted recovery, corruption detection, duplicate publication, retained tombstone orphan-race cleanup, store-identity mismatch denial and bounded reconciliation. No public URLs, client-selected keys, database body storage or metadata mirror. **Offline protocols passed; real target-store/cloud acceptance is open.** |
| P20.2 | `artifacts/consumers.py`, `evaluation/output.py`, account export/inventory, private artifact API and Next.js proxy, factory/settings, worker and accounting fences: optional actual-build and batched evaluation retention, routing/debug seams, frozen required exports with exact generations/dependency propagation, owner deletion denial/job fencing, retention and three-tier reference/body/budget observations. **Source-derived verbose traces remain gated on Phase 14/15; future request routing is not introduced.** |

`ARTIFACTS_ENABLED` defaults off in backend/frontend examples. Fake bodies are local/test only. Live GCS requires explicit bucket/eligible region, privacy/free-tier/IAM preflight attestation/reference and live private bucket verification. Hard guardrails constrain daily/monthly operations, reserved body IO and live stock; they do not certify account-wide billing eligibility. Every external generation reservation checks the durable owner fence, independently of optional artifact retention. Full physical canonical account deletion is still the Phase 9 operator workflow.

The root README was reviewed and updated because private GCS artifact bodies, optional capabilities and setup/status changed. Router, current-state, Chapter 2 overview/plan index, storage README and API contract now identify this phase-local implementation and its acceptance gaps. The supplied plan and unrelated untracked review/handoff documents were preserved.

## Verification

Environment: local macOS, backend Python **3.11.15** from the existing `.venv`, existing pinned dependencies, bundled Node runtime, pnpm **11.19.0**. Backend Makefile commands used the existing `.venv/bin` on `PATH`; frontend commands used the bundled Node path. Builds made no provider/cloud calls.

| Command / check | Actual result |
| --- | --- |
| `make backend-test` | **Passed: 962 tests, 43 skipped.** Existing Starlette/httpx deprecation warning. |
| `python -m pytest backend/tests/test_artifacts.py backend/tests/persistence/test_artifact_tier.py -q` | **47 deterministic tests passed; 4 Postgres integration cases skipped** without an isolated DSN. |
| `make backend-lint` | **Passed.** |
| `UV_CACHE_DIR=/tmp/personal-ai-phase20-uv-cache make backend-build` | **Passed:** sdist and wheel built. The default user cache was inaccessible; the writable `/tmp` cache resolved it. |
| Wheel contents | **Passed:** artifact modules and migration 019 included; no bytecode. Explicit Hatch sdist/wheel inclusion fixes the repository's generated `artifacts/` ignore pattern excluding source modules during packaging. |
| `make frontend-test` | **Passed: 98 tests, 19 test files.** |
| `make frontend-lint` | **Passed.** |
| `make frontend-typecheck` | **Passed.** |
| `make frontend-build` | **Passed**, including `/api/artifacts/[artifactId]`. Existing Vite CJS/Next ESLint integration warnings. |
| `make context-eval context-plan-eval memory-eval memory-lifecycle-eval research-eval decision-eval domain-eval iterative-research-eval itinerary-proposal-eval` | **All nine offline suites passed.** Synthetic reports were retained only in a temporary validation log, not committed as private/raw runtime data. |
| Documentation local links and content | **Reviewed** against implemented interfaces, gates and tests. |
| `git diff --check` | **Passed.** |

Regression coverage includes scoped reads, namespace/key validation, JSONL batching, hash/decompression bounds, immutable generation/revision checks, concurrent budget admission, monthly operations/transfer ceilings, no object creation when stock admission denies, duplicate uploads/publications, missing/corrupt bodies, crashes before upload and after upload/deletion, delayed expiry deletion, upload/delete orphan races, owner/grant revocation during IO, provider/job fencing before dispatch/claim, required export failure without success audit, export dependency/expiry propagation, ready export retry freezing, private/default-off API access and unsafe bucket configuration rejection.

Real Postgres cases are explicitly added to the existing GitHub Actions Postgres step. They test body/metadata separation, global concurrent admission, durable owner fence/reconciliation, and transactional account confirmation/cancellation. That CI configuration is present; **no CI run or engine execution is claimed here**.

## Open acceptance gates

- Docker is unavailable locally; no local Postgres/DynamoDB engine was started. Migration 019 was **not applied** and its four new real-engine cases remain **unverified**. The other opt-in provider/engine/manual checks account for the remaining skipped tests.
- No GCS bucket, cloud resource, IAM binding, provider or paid path was created, enabled or exercised. GCS ADC, private/inherited IAM, generation semantics, actual region/account eligibility, retention/soft-delete/version configuration, account-wide storage/operation/transfer costs, backups/index/container costs and deployed behavior are **unverified**. HTTPX fakes establish only local protocol contracts.
- Phase 14 immutable source/policy references and Phase 15 derived-history/source/grant revocation are still partial. Provider-derived verbose context artifacts are therefore off; nonempty artifact dependencies fail closed without a trusted current resolver. Sensitive Finance/Health verbose retention also remains off. This phase does not fabricate durable grants or claim full prerequisite acceptance.
- Routing/debug retention seams support future consumers; the current Gemini-only workflows have no routing selection to observe. Required canonical routing-decision replay facts and the 90-day reference horizon remain obligations of the later routing phase, independent of optional GCS support bodies.
- Account deletion fences future artifact access/publication, verified API use, provider reservations and new worker claims, and reconciles artifact body cleanup. Full canonical physical deletion, in-flight non-provider effects, deletion-aware restore and deployed acceptance retain their existing Phase 9/security gates. Tombstones remain compact canonical metadata; no raw artifact body has indefinite retention.

Phase 20's **local implementation is delivered**. Full phase acceptance remains open at the prerequisite, target-store and deployed/privacy/free-tier gates above. See the [guide](phase-20-implementation-guide.md) and [current state](../current-state.md).
