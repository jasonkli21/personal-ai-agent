# Development instructions

## Start here

- Read `docs/project-brief.md`, `docs/architecture.md`, and
  `docs/phase-1-implementation-guide.md`, then the plan relevant to the task.
- Phase 1 chat code is implemented; the current scope is verification closeout
  and handoff maintenance. See `docs/phase-1-verification-plan.md` for open work.
  Phase 2 is planned, not started. Follow explicit user instructions when
  advancing scope; do not add later-phase features incidentally.
- Inspect `git status` before editing and preserve existing user changes.

## Boundaries

- Keep routes and UI thin; backend services own chat behavior. Browser calls
  go through the Next.js API proxy.
- Keep provider SDKs inside `backend/src/personal_ai/llm`; services depend on
  `LLMClient`. Keep Firestore details behind repository contracts.
- Preserve parent/supersedes links and superseded message records. Regenerate
  and edit/retry must use only the active branch as model context.
- The fixed `local` owner is not authenticated identity. Do not claim the
  public bootstrap protects personal data.
- Keep durable user memory separate from time-sensitive external evidence;
  enforce hard constraints in code. Future domain modules reuse shared layers.
- Avoid large orchestration frameworks unless the task explicitly calls for
  one. Keep experiments isolated until evaluated against a baseline.

## Setup and checks

Follow the root README for installation. Use Python 3.11+ with the backend
virtual environment activated, Node 22 on `PATH`, and pnpm 11.19.0. Install
frontend dependencies with `pnpm install --frozen-lockfile`.

From the repo root:

```sh
make backend-test
make backend-lint
make frontend-test
make frontend-lint
make frontend-typecheck
```

Run checks relevant to the change; run all five for changes spanning both
applications. For deployment-script edits also run
`bash -n infrastructure/gcp/deploy.sh`. Finish with `git diff --check`.
Documentation-only edits need link/content review and `git diff --check`.

Automated tests use fake repositories and a fake LLM and require no credentials,
emulator, or network. Keep real Firestore/Gemini checks opt-in. Do not turn a
missing manual-test environment into a requirement for offline tests.

## Handoff and evidence

- Update docs when behavior, phase status, setup, or acceptance evidence changes.
  Record the date, tested revision, results, and remaining verification gaps.
- Never claim cloud, emulator, or provider checks passed based on fake tests.
- Keep credentials in untracked environment files or Secret Manager. Do not
  commit keys, personal chats, or private data in fixtures, logs, or reports.
