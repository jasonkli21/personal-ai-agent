# Development instructions

## Start here

- Read `docs/project-brief.md`, `docs/architecture.md`, and
  `docs/phase-1-implementation-guide.md`, then the plan relevant to the task.
- Phase 1 chat, Phase 2 context-management, and Phase 3 simple-memory code are implemented locally.
  Read `docs/phase-2-implementation-guide.md` for context contracts and current
  verification gaps. Provider/emulator/deployment closeout remains pending;
  Phase 3/4/5 gates remain disabled by default; Phase 4 and Phase 5 are implemented locally.
  Read `docs/phase-5-implementation-guide.md` for research contracts and external gaps.
  Read `docs/phase-3-implementation-guide.md` and
  `docs/phase-4-implementation-guide.md` for memory/lifecycle contracts and gaps.
  Follow explicit user instructions when advancing
  scope; do not add later-phase features incidentally.
- Inspect `git status` before editing and preserve existing user changes.

## Boundaries

- Keep routes and UI thin; backend services own chat behavior. Browser calls
  go through the Next.js API proxy.
- Keep provider SDKs inside `backend/src/personal_ai/llm`; services depend on
  `LLMClient`. Keep Firestore details behind repository contracts.
- Route every model turn through the shared token-budgeted context assembler.
  Summaries are lossy, branch-scoped working context, not long-term memory.
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
virtual environment activated, uv 0.11.13, Node 22 on `PATH`, and pnpm 11.19.0. Install
backend dependencies with the README's locked uv sync steps. Install
frontend dependencies with `pnpm install --frozen-lockfile`.

From the repo root:

```sh
make backend-test
make backend-lint
make context-eval
make memory-eval
make memory-lifecycle-eval
make frontend-test
make frontend-lint
make frontend-typecheck
```

Run checks relevant to the change; run all five for changes spanning both
applications. For dependency or build changes also run `make backend-build`
and/or `make frontend-build`, plus the affected Docker build when Docker is
available. CI checks backend packaging on Python 3.11/3.12 and both images.
See `docs/dependency-management.md` for lockfile maintenance.
For deployment-script edits also run
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
