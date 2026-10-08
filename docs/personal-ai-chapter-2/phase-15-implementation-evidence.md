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

## Independent-review follow-up

The independent review of commit `97cd92e8ce592dddfee538b98021dae94193ebf1`
identified three P1 gaps: populated provider payloads could exceed the selected
field projection, baseline conversation/summary disclosure did not use the
conversation-history policy, and standalone generation paths did not propagate
application policy into source preparation and inference. The correction tree
below addresses those three findings. P15.2 lineage and immutable Phase 14
policy/source references remain open, so Phase 15 remains partial. The review
record is [`docs/phase-15-independent-review-2026-10-07.md`](../phase-15-independent-review-2026-10-07.md)
and is intentionally uncommitted.

Checks were run on the working tree based on commit
`97cd92e8ce592dddfee538b98021dae94193ebf1`, with the follow-up source and test
changes present before their separate commit:

| Command | Result |
| --- | --- |
| `source backend/.venv/bin/activate && make backend-test` | Passed: 732 passed, 26 skipped, 1 warning (758 collected). |
| `source backend/.venv/bin/activate && make backend-lint` | Passed. |
| `source backend/.venv/bin/activate && make context-eval context-plan-eval memory-eval research-eval domain-eval` | All five deterministic evaluation targets exited successfully; research and domain outputs are synthetic. |
| `git diff --check` | Passed after the follow-up documentation edit. |

The focused and full checks use fake/offline context, repository, and model
adapters. They verify local contracts only and do not establish provider,
emulator, cloud, deployed membership, IAM, production-security, or regulatory
behavior. The 26 skipped tests were not represented as passed.

## Phase 14 and Phase 15 review-closure verification

Date: 2026-10-07 (America/Los_Angeles). The verification tree was based on
`78d1de9ae9f7b1a6c2b73b5eaabd642eae2bfafd` with the review-pass code and
documentation changes present in the working tree. It closes the remaining
dispatch gap by requiring a valid sensitivity/policy envelope for Gemini
generation and summaries, and by rejecting unscoped chat preparation when the
configured inference client requires that envelope. The built-in fake client is
explicitly marked as the unscoped development/test adapter.

| Command | Result |
| --- | --- |
| `cd backend && .venv/bin/python -m pytest` | Passed: 735 passed, 26 skipped, 1 warning (761 collected). |
| `cd backend && .venv/bin/python -m ruff check .` | Passed. |
| `git diff --check` | Passed. |

The full suite includes the Phase 14 trace-deadline/schema cases and Phase 15
payload-projection, baseline-history, standalone-policy, and inference-envelope
cases. The root Makefile aliases could not start in this shell because `python`
was not on `PATH`; the equivalent backend virtual-environment commands passed.
These offline results do not close the remaining immutable Postgres version
reference, derived-context revocation, application-membership, provider, local
emulator, cloud, or production-security gates. The Phase 14 and Phase 15
acceptance status remains partial.
