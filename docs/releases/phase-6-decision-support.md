# Phase 6 decision support release evidence

Date: 2026-10-02

Tested code revision: `98afe76` (`feat(web): surface evidence-backed decisions`)

Status: implemented locally; runtime gates remain disabled by default.

This revision delivers the neutral decision-support contracts and accepted ADR
0012, owner-scoped entity/claim and decision persistence, conservative
evidence-backed resolution, typed claim validation, deterministic hard
constraints, explainable ranking, result and inspection APIs, browser views,
and a synthetic 15-fixture evaluation. Both completed Phase 5 session evidence
and explicitly supplied, fingerprint-checked excerpts are covered. This
release does not add a domain adapter or an external purchase/booking action.

## Offline verification

| Check | Result |
| --- | --- |
| Backend tests: `cd backend && ./.venv/bin/python -m pytest -q` | 353 passed, 12 skipped; skips are opt-in manual provider/emulator checks. One upstream Starlette/httpx deprecation warning. |
| Backend lint: `cd backend && ./.venv/bin/ruff check .` | Passed. |
| Context evaluation | Passed. |
| Memory evaluation | Passed. |
| Memory lifecycle evaluation | Passed. |
| Research evaluation | Passed. |
| Decision evaluation | Passed, 15/15 synthetic fixtures. |
| Frontend tests | Passed, 53 tests across 10 files. |
| Frontend lint | Passed. |
| Frontend typecheck | Passed. |

The decision tests include fake-repository Firestore transaction and
serialization coverage, owner scoping, idempotency, evidence/reference checks,
typed-value mismatches, ambiguous currency, future-dated evidence, hard
constraint precedence, conflict/freshness behavior, UI gate behavior, and
ranking fallback. They do not establish real Firestore semantics.

## Remaining verification gaps

- Real Firestore emulator transactions, deployed indexes, and production
  storage behavior have not been checked.
- Brave evidence storage and AI-use rights still need operator review before
  using provider data in snapshots.
- Real Gemini calls, browser behavior against a deployed backend, and cloud
  deployment were not exercised.
- The fixed `local` owner is not authentication or authorization for private
  data. Decision and inspection gates remain off by default.

Do not treat synthetic results as provider, emulator, or deployment evidence.

## Review remediation — 2026-10-02

Tested revision: base `309aa7f` plus the review-remediation working tree recorded
in this commit. The final parent review tightened full-assertion parsing,
preserved a successful session-backed decision test, and added partial identifier
conflict and replay-after-lowered-limit coverage. Final offline checks:

| Check | Result |
| --- | --- |
| `make backend-test` | 371 passed, 12 opt-in manual checks skipped; one upstream Starlette/httpx warning. |
| `make backend-lint` | Passed. |
| `make context-eval memory-eval memory-lifecycle-eval research-eval decision-eval` | All passed; decision fixtures 15/15. |
| `make frontend-test` | 53 passed across 10 files. |
| `make frontend-lint frontend-typecheck` | Both passed. |
| `git diff --check` | Passed. |

Checks used Python 3.11.15 and Node 22.23.3 with the existing locked dependencies.
These checks cover the conservative claim assertion parser, conflicting stable
identifiers, unsupported identity exclusion, complete attribute-filtered claim
retrieval in the Firestore fake, and replay after source-session expiry.

New claims and decision snapshots record `claim-verification-v2`. Claims whose
stored verification version is absent remain v1 and cannot satisfy current
constraints or identity resolution. New snapshots record `resolve-v2`; old
snapshots remain readable as v1. The updated Firestore claim query adds an
owner/entity/attribute index to the manifest. Real Firestore index readiness,
transactions, provider checks, and deployed behavior remain unverified.
