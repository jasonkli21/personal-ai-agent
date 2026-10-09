# Phase 19 implementation evidence — Provider usage accounting and quota ledger

**Date:** 2026-10-08

**Tested revision:** working tree based on `683b568` (`main`). Phase 19 source
and tests were present during verification; this evidence and the linked guide
were added afterward without changing runtime code.

## Delivered

- Added provider-neutral invocation, attempt, result, and accounting contracts
  under `backend/src/personal_ai/usage/`, including task/run and validated
  request-scope attribution.
- Wired reserve-before-send and settle-after-response accounting through the
  LiteLLM transport and direct Brave, Nominatim, and OpenFoodFacts HTTP paths.
  Implicit SDK retries remain disabled; pre-send denial does not count as a
  physical attempt; unknown outcomes remain fenced with their reservations.
- Added migrations
  [`017_provider_usage_accounting.sql`](../../backend/src/personal_ai/persistence/migrations/017_provider_usage_accounting.sql)
  and
  [`018_provider_usage_profile_versions.sql`](../../backend/src/personal_ai/persistence/migrations/018_provider_usage_profile_versions.sql)
  and Postgres canonical invocation, attempt, quota reservation/window,
  endpoint-health, daily-aggregate, summary, reconciliation, and explicit
  retention operations. The second migration preserves quota-membership
  provenance and separates daily aggregates by endpoint profile version.
- Added scoped DynamoDB operational events and bounded explicit event deletion.
  Account export/deletion inventory includes owner-attributed Postgres records
  and the operational events; provider event schema is checked consistently at
  write and export boundaries.
- Added default-off `GET /v1/developer/provider-usage?days=...`, bounded
  inspection and usage settings, and Brave prepaid/no-auto-reload/no-paid-
  balance/source-rights attestations. Public lookup capacity remains unknown
  unless supported by fresh authoritative observations.
- Updated the current-state snapshot, API contract, README, Chapter 2 status,
  Phase 10 storage ownership inventory, and Phase 19 guide.

## Verification

| Check | Result |
| --- | --- |
| `cd backend && .venv/bin/python -m pytest -q` | **Passed:** 911 tests, 30 skipped; one existing Starlette/httpx deprecation warning |
| Focused usage/provider checks | **Passed:** 104 tests before the final full-suite run; full suite includes the final event-contract test |
| `cd backend && .venv/bin/ruff check .` | **Passed** |
| `cd backend && UV_CACHE_DIR=/private/tmp/phase19-uv-cache uv build --no-build-isolation` | **Passed:** source distribution and wheel built |
| `cd backend && PYTHONPYCACHEPREFIX=/private/tmp/phase19-pycache .venv/bin/python -m compileall -q src/personal_ai` | **Passed** |
| `git diff --check` | **Passed** |
| `cd backend && .venv/bin/python -m pytest -q tests/persistence/test_provider_usage_accounting.py` | **Skipped:** all 4 Postgres integration cases require `PERSISTENCE_TEST_POSTGRES_DSN` |

The persistence integration tests cover concurrent shared-bucket admission,
unknown quota accounting, all-or-none multi-bucket reservation, and generic
unit reservation/settlement. They did not execute against Postgres in this
environment. Docker was unavailable, so no local Postgres/DynamoDB stack was
started. The migration was not applied to a database.

## Independent review follow-up

**Date:** 2026-10-08

**Tested revision:** working tree based on `a3540ac` (`main`) with the review
follow-up changes described here.

The independent review identified seven correctness gaps and one persistence
verification gate. The follow-up changes resolve the code findings by carrying
the exact durable endpoint profile and quota-membership provenance into
admission; denying unknown or ambiguous membership before dispatch; enforcing
the stale-attempt age above the maximum provider timeout; preserving explicit
research retry lineage and task/run attribution; keying aggregates by profile
version; applying conservative quota corrections while rejecting incompatible
window identity; and retaining closed, unreferenced operator quota windows
under the configured bound. Late settlement cannot replace an orphaned unknown
result. A regression found during full-suite verification also led to lazy
registry loading, so routes that do not dispatch a provider do not read
Postgres just to construct the accounting dependency.

The persistence integration suite now has 13 cases, including profile
membership, quota corrections, retry fencing, aggregation versioning, stale
attempt handling, and retention. GitHub Actions starts a pgvector/Postgres 17
service and runs this suite with `PERSISTENCE_TEST_POSTGRES_DSN`; this makes the
database suite a repeatable CI gate instead of relying on tests that silently
skip without a DSN.

| Check | Result |
| --- | --- |
| `cd backend && .venv/bin/python -m pytest -q` | **Passed:** 915 tests, 39 skipped; one existing Starlette/httpx deprecation warning |
| `cd backend && .venv/bin/python -m ruff check .` | **Passed** |
| `git diff --check` | **Passed** |
| `cd backend && .venv/bin/python -m pytest -q tests/persistence/test_provider_usage_accounting.py` | **Skipped locally:** 13 integration tests require `PERSISTENCE_TEST_POSTGRES_DSN` |

No Docker executable or reachable local Postgres server was available, and no
local pgvector extension was found. Therefore neither migration 018 nor the
Postgres concurrency/retention tests were applied or executed locally. The CI
gate is configured but has not run as part of this local review. Cloud,
DynamoDB, provider, quota/account, and deployment checks remain open.

## Configuration and remaining gates

Provider accounting requires the configured Postgres and DynamoDB persistence
clients and migrations 017–018. `PROVIDER_USAGE_INSPECTION_ENABLED` defaults off.
Unknown or stale quota capacity is not promoted to a known limit or remaining
amount. Brave search requires its configured prepaid and source-rights facts and
has no postpaid overflow path.

No live provider, provider-account/tier, privacy/source-rights, IAM, cloud,
deployed retention, or strict-$0 checks were performed. Fakes and offline tests
establish only the local contracts documented above. Application workflows
remain Gemini-only; Phase 19 adds accounting and admission controls without
provider routing.
