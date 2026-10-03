# Phase 7 travel and shopping release evidence

Date: 2026-10-02

Tested code revision: `f4dfc3a6f2bc1164d14e5d583df5977597ff636e` plus the
uncommitted Phase 7 remediation working tree described below.

Status: implemented locally within the provider and comparison scope described
in the [implementation guide](../phase-7-implementation-guide.md). Decision,
domain, provider, and inspection gates remain disabled by default.

Phase 7 adds internal versioned travel and shopping modules over shared Phase
5–6 evidence, identity, constraints, and ranking; bounded provider mappings;
immutable domain extensions and comparison snapshots; a gated browser
workbench; and deterministic domain evaluation. Nominatim provides bounded
place lookup, and Open Food Facts provides exact-barcode product identity.
Neither adapter supplies live booking or merchant-offer data. The phase does
not add booking, checkout, authoritative itinerary state, purchases, price
history, authentication, or Phase 8 iterative research.

## Initial Phase 7 verification

| Check | Result |
| --- | --- |
| Backend tests: `make backend-test` | 389 passed, 12 opt-in manual checks skipped; one upstream Starlette/httpx deprecation warning. |
| Backend lint: `make backend-lint` | Passed. |
| Context evaluation | Passed. |
| Memory evaluation | Passed. |
| Memory lifecycle evaluation | Passed. |
| Research evaluation | Passed. |
| Decision evaluation | Passed. |
| Domain evaluation: `make domain-eval` | Passed, travel 4/4 and shopping 6/6 synthetic fixtures. |
| Frontend tests: `make frontend-test` | 59 passed across 12 files. |
| Frontend lint: `make frontend-lint` | Passed. |
| Frontend typecheck: `make frontend-typecheck` | Passed. |
| `git diff --check` | Passed. |

Backend checks used Python 3.11.15. The configured Node 22 runtime was not
available on this host; frontend checks used the bundled Node 24.19.0 runtime
and pnpm 11.19.0. The frontend suite emitted Vite's existing CJS Node API
deprecation notice. Offline checks ran against synthetic evidence and fake
repositories/providers only.

## Combined-review remediation verification

Date: 2026-10-02 (America/Los_Angeles).

The combined review of backend commit `e83f89e299a7a3da98a33a743758b3248847b6aa`,
frontend commit `40ed00d444d3878337ad5a4799570f2da7f6bff7`, and evidence commit
`f4dfc3a6f2bc1164d14e5d583df5977597ff636e` was performed against review base
`d75e7f8`. The six findings and their regression coverage are recorded in the
[remediation report](phase-7-review-remediation.md). Checks below ran against
the `f4dfc3a6f2bc1164d14e5d583df5977597ff636e` code plus the uncommitted
remediation changes; no remediation commit exists yet.

| Check | Result |
| --- | --- |
| Focused domain and Firestore tests | 29 passed. |
| `make backend-test` | 401 passed, 12 opt-in manual checks skipped; one upstream Starlette/httpx deprecation warning. |
| `make backend-lint` | Passed. |
| `make context-eval` | Passed. |
| `make memory-eval` | Passed. |
| `make memory-lifecycle-eval` | Passed. |
| `make research-eval` | Passed. |
| `make decision-eval` | Passed. |
| `make domain-eval` | Passed, travel 4/4 and shopping 6/6 synthetic fixtures. |
| `make frontend-test` | 64 passed across 12 files. |
| `make frontend-lint` | Passed. |
| `make frontend-typecheck` | Passed. |
| `git diff --check` | Passed. |

Backend checks used Python 3.11.15. Node 22 was not available on `PATH`; the
frontend checks used bundled Node 24.19.0 and pnpm 11.19.0. The frontend suite
emitted Vite's existing CJS Node API deprecation notice. Offline checks used
synthetic evidence, fake repositories, and mock HTTP transports only. They do
not establish real Firestore transaction or provider behavior.

## Completion review

1. **Shared platform reuse:** travel and shopping map through the shared
   evidence, entity, claim, constraint, decision, and ranking contracts. Domain
   features are applied after shared hard-constraint filtering.
2. **Attribution and freshness:** every fixture and mapped provider record
   retains source/evidence IDs, observation time, expiry, attribution, and
   policy metadata. Synthetic tests cover stale/conflicting evidence and
   incomplete or inconsistent totals. Current provider and Firestore behavior
   still needs external verification.
3. **Inspectable UI:** the gated workbench shows visible requirements,
   candidate eligibility, rationale, freshness/conflict/missing states, source
   links, and local filters without exposing hidden reasoning or private memory.

## Remaining verification gaps

- Real Firestore emulator transactions and cross-instance rate limiting,
  production index readiness, and GCP deployment were not exercised.
- Nominatim and Open Food Facts smoke tests and current policy review remain
  outstanding. Brave storage/AI-use rights remain outstanding as well.
- Current hotel, flight, restaurant, merchant-offer, stock, shipping, and
  delivery evidence requires additional provider adapters before these facts
  can support real recommendations.
- No real personal data, credentials, provider responses, booking, or purchase
  was used in offline evaluation.

Do not treat offline tests as provider, emulator, deployment, or data-rights
evidence.
