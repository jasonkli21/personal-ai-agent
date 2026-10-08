# Phase 15 implementation evidence — Permissions and sensitivity policy

Date: 2026-10-07 (America/Los_Angeles)

## Tested tree and implementation

The tested source tree was the Phase 15 working tree based on commit
`c327cd67d8ab9435e5a0ebc30d92e46fc7404fa9` (`fix(context): address phase 14
review`). The implementation adds typed server-owned application/provider/
operation/field rules, separate source-access and model-disclosure decisions,
unknown-sensitivity denial, a hard cross-application deny, and explicit
Finance/Health field policies. Chat policy checks run before memory retrieval;
the assembler checks selections and baseline sensitivity before summaries or
token counting; the provider coordinator repeats the complete policy preflight
before factory/source work; and item sensitivity is joined and checked before
model-input construction. The effective sensitivity and policy version label
are carried in the build manifest/trace and passed through the neutral inference
contract.

The repository-root `README.md` was reviewed. No README edit was required:
Phase 15 adds server-side policy enforcement without changing setup,
user-visible capabilities, provider support, or deployment behavior.

## Checks

The backend virtual environment was activated for backend commands.

| Command | Result |
| --- | --- |
| `source backend/.venv/bin/activate && make backend-test` | Passed: 727 passed, 26 skipped, 1 warning (753 collected). |
| `source backend/.venv/bin/activate && make backend-lint` | Passed. |
| `source backend/.venv/bin/activate && make context-eval context-plan-eval memory-eval research-eval domain-eval` | All five deterministic evaluation targets exited successfully. Research and domain outputs identify themselves as synthetic. |
| `git diff --check` | Passed. |

An initial bare `make backend-lint` attempt could not start because `python` was
not on the shell `PATH`; the reported lint result is the successful rerun with
the repository backend virtual environment activated. No frontend files
changed, so frontend tests, lint, typecheck, and builds were not run.

## Remaining gaps and limits

- Phase 14's immutable Postgres policy/source-version reference prerequisite
  remains open. Phase 15 records code policy version labels, not immutable
  policy bodies or Postgres references.
- Existing profile and memory source dependencies are rechecked before
  injection. Conversation history and summaries do not yet carry source grant
  dependencies end-to-end through later turns, traces, exports, and artifacts;
  Phase 15 P15.2 is incomplete.
- Cross-app grants remain disabled. The versioned dependency contract can name
  future grant IDs and source/destination applications, but it does not create
  or enable grants.
- The test and evaluation fixtures are synthetic/fake. They do not establish
  provider, emulator, cloud, deployed membership, IAM, provider data-use or
  retention, production-security, or regulatory behavior. The 26 skipped tests
  were not represented as passed.
- No real Travel, Shopping, Finance, or Health provider is implemented or
  verified. The internal inference sensitivity envelope is checked locally;
  no external provider privacy/data-use review was performed.
