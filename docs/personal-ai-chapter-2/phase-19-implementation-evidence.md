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
- Added migration
  [`017_provider_usage_accounting.sql`](../../backend/src/personal_ai/persistence/migrations/017_provider_usage_accounting.sql)
  and Postgres canonical invocation, attempt, quota reservation/window,
  endpoint-health, daily-aggregate, summary, reconciliation, and explicit
  retention operations.
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

## Configuration and remaining gates

Provider accounting requires the configured Postgres and DynamoDB persistence
clients and migration 017. `PROVIDER_USAGE_INSPECTION_ENABLED` defaults off.
Unknown or stale quota capacity is not promoted to a known limit or remaining
amount. Brave search requires its configured prepaid and source-rights facts and
has no postpaid overflow path.

No live provider, provider-account/tier, privacy/source-rights, IAM, cloud,
deployed retention, or strict-$0 checks were performed. Fakes and offline tests
establish only the local contracts documented above. Application workflows
remain Gemini-only; Phase 19 adds accounting and admission controls without
provider routing.
