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
