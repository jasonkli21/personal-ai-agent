# Dependency and build management

Backend dependency versions and artifact hashes are recorded in `backend/uv.lock`.
Frontend versions are recorded in `frontend/pnpm-lock.yaml`. Local setup, CI,
and Docker use these locks rather than resolving new versions on each install.
Use uv 0.11.13 and pnpm 11.19.0, matching the build configuration.

## Backend

From `backend/`:

```sh
uv sync --locked --only-group build --no-install-project
uv sync --locked --extra dev --group build --no-build-isolation
source .venv/bin/activate
uv build --no-build-isolation
```

The first sync installs the locked Hatchling and editables build group without building the
application. The second installs runtime/dev dependencies and builds the local
package with those build tools, avoiding a separate unpinned build environment.
Docker follows the same sequence, omitting the dev extra and using a noneditable
application install. CI checks packaging and tests on Python 3.11 and 3.12.

For an intentional dependency change, edit `pyproject.toml`, run `uv lock`, then
the sync steps and backend tests/lint/build. To upgrade existing pins, use
`uv lock --upgrade-package PACKAGE` or `uv lock --upgrade`, review the diff,
and commit the updated metadata and lock together. Build tooling lives in both
`build-system.requires` and the `build` group; keep their Hatchling and editables pins aligned. The pinned editables dependency
is required by Hatchling for the non-isolated editable install used locally and
in backend CI.

`--locked` rejects metadata changes that require updating the lockfile. See
[uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/).

## Frontend

From `frontend/`:

```sh
pnpm install --frozen-lockfile
pnpm run test
pnpm run lint
pnpm run typecheck
pnpm run build
```

Update dependencies deliberately with pnpm and commit `package.json` and
`pnpm-lock.yaml` together. Do not introduce npm lockfiles. Docker copies the
package manifest, pnpm lock, and workspace build-script policy before installing;
the standalone Next.js output is copied into the runtime image.

## Container checks

From the repo root, with Docker available:

```sh
docker build --tag personal-ai-api:local ./backend
docker build --tag personal-ai-web:local ./frontend
```

Both builds run in CI. Each context has a `.dockerignore` excluding local
environment files, installed dependencies, caches, and generated output.

These changes lock dependency resolution; they do not promise byte-identical
images. Python/Node base image tags and GitHub Action major tags remain mutable.
Docker build success also does not verify Firestore, Gemini, or deployed service
behavior; those checks remain in the Phase 1 verification closeout plan.
