# Next-scope Phase 2 implementation evidence — 2026-10-05

## Revision and configuration

- Source base: `dd6819b` (`record phase 1 review follow-up evidence`). Checks
  ran against the Phase 2 working tree based on that revision; this evidence
  and the tested implementation are included in the single Phase 2 commit.
- Backend interpreter: Python 3.11.15 from `backend/.venv`.
- Registry uses deterministic in-process manifests, comparison modules, and
  capability records. Tests use in-memory repositories, a fake LLM, and
  synthetic app definitions. No credentials, provider calls, emulator, or cloud
  services were used.

## Local checks

| Check | Result |
| --- | --- |
| `PATH="$PWD/backend/.venv/bin:$PATH" make backend-test` | Passed: 602 collected, 590 passed, 12 skipped. Skips are opt-in provider/emulator checks. |
| `PATH="$PWD/backend/.venv/bin:$PATH" make backend-lint` | Passed: Ruff reports all checks passed. |
| Focused app/auth/scope/conversation/context route tests | Passed: 61 tests. |
| `git diff --check` | Passed before commit. |

## Acceptance evidence

- Duplicate apps/capabilities, unknown provider/tool/domain/application
  references, unsupported schema versions, malformed availability declarations,
  contradictory cross-app metadata, invalid budget hints, and unsupported
  workspace use are covered by deterministic tests.
- Travel, Shopping, Finance, and Health registrations expose unavailable
  provider/tool stubs. Existing Travel and Shopping comparison modules compose
  into their app registrations without changing their ownership contracts.
- Unknown application IDs fail with `application_not_registered`; standalone
  and the five initial registered app scopes preserve existing conversation
  behavior.
- A synthetic app plus provider registration is accepted without app-name
  branches and reaches context assembly paired with the server-derived scope.
- App definitions carry memory namespace, sensitivity defaults, optional budget
  hints, workspace support, cross-app declarations, provider/tool IDs, and
  comparison module references. Metadata alone does not grant domain access,
  workspace access, or cross-app data sharing.

## Remaining verification gaps

- This phase adds no live domain context provider or tool/action implementation.
  The affected stubs remain unavailable.
- Cross-app declarations remain disabled for built-in applications; no grants
  or domain reads were added.
- Workspace membership remains denied by default. Firestore indexes, emulator
  behavior, deployed identity/IAM/proxy behavior, and live provider behavior
  were not exercised.
- Next-scope Phase 1's legacy standalone scan isolation limitation and its
  storage/deployment verification gaps remain unresolved. Existing Phase 9
  deletion, owner migration, provider accounting, and operational closeout also
  remain open.

## Independent-review remediation — 2026-10-06

Applied against base revision `2c2562d8b4aa798acd5961192b7405dc2539e01c`;
the following results cover the working tree with the review fixes and this
evidence update. Backend used Python 3.11.15 from `backend/.venv`. Frontend
checks used the bundled Node.js 24.19.0 runtime because Node 22 is not on PATH;
Node 22 compatibility remains unverified.

| Check | Result |
| --- | --- |
| `PATH="$PWD/backend/.venv/bin:$PATH" make backend-test` | Passed: 605 collected, 593 passed, 12 skipped. Skips are opt-in provider/emulator checks. |
| `PATH="$PWD/backend/.venv/bin:$PATH" make backend-lint` | Passed: Ruff reports all checks passed. |
| `PATH="/Users/jasonkli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" make frontend-test` | Passed: 97 tests across 19 files. |
| `PATH="/Users/jasonkli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" make frontend-lint` | Passed. |
| `PATH="/Users/jasonkli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" make frontend-typecheck` | Passed for both TypeScript configurations. |
| `git diff --check` | Passed. |

The capability contract now separates implementation availability from its
`memory_enabled` feature gate. Registry composition gives all registered chat
applications shared conversation history and memory metadata; domain-specific
providers/actions remain unavailable stubs. Offline integration coverage checks
memory disabled/enabled against actual fake model input, and registry coverage
checks standalone, built-in domain, and synthetic apps with and without an
explicit memory declaration. The frontend client accepts extensible app IDs,
defaults to `personal_ai`, and forwards synthetic app/workspace/correlation
headers; unknown applications continue to be rejected by the backend registry.

No emulator, live provider, deployed browser/IAM, workspace membership, or Node
22 verification was performed. Local fakes do not establish live readiness.
