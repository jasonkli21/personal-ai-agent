# Phase 1 verification closeout

This is an outline of the remaining acceptance work, not a record of completed
checks. Phase 1 code is implemented. Offline checks last passed on 2026-10-01
at `7301bdd`: 32 backend tests passed, one credentialed test skipped, 10 frontend
tests passed, and Ruff/ESLint/TypeScript checks passed. See the
[verification record](releases/phase-1-vertical-slice.md) for execution details.

## 1. Verify Firestore persistence across an API restart

**Prerequisites:** installed backend dependencies, Google Cloud CLI and Firestore
Emulator; no model key is needed for the persistence-only check.

- Start the emulator using the root README instructions and configure the
  example project ID and emulator host in an untracked backend environment file.
- Start the API, create a synthetic conversation through
  `POST /v1/conversations`, and verify list/detail routes retrieve it.
- Add an opt-in emulator integration check that writes synthetic completed
  user/assistant messages through the real Firestore repositories. Recreate
  the repository clients and assert content, status, owner scoping, and active
  branch selection survive; verify superseded records remain retrievable.
- Restart the API while leaving the emulator running. Retrieve the same
  conversation and message IDs and compare the persisted active history.
- Keep emulator integration checks separate from the default offline suite.

**Pass evidence:** matching IDs, statuses, and active history before and after
API restart; report assertions and results without copying message content.
This verifies adapter persistence, not real Gemini generation or cloud indexes.

## 2. Maintain client-disconnect integration coverage

**Prerequisites:** fake LLM/repositories; no cloud access, model key, or emulator.

**Implementation status:** local ASGI and proxy tests have been added in the
[review remediation](phase-1-review-fixes.md). They cover disconnect during
initial events, delta delivery, provider waits, and before iterator start,
plus preservation of terminal states. Run the backend and frontend suites to
retain this evidence; deployed browser cancellation is still pending.

- Use a controllable async fake LLM that yields a known first delta, then waits
  on a synchronization event and records cancellation/finalization.
- Exercise the FastAPI streaming route through an ASGI harness that explicitly
  delivers `http.disconnect` after the first delta. Do not rely on a buffered
  TestClient response to simulate a disconnect.
- Assert the provider stops consuming, the task terminates within a bounded
  timeout, and the assistant persists as `failed` with `client_cancelled` and
  the partial content. Assert no completed event or further delta is emitted.
- Add a companion direct iterator-cancellation test if useful to isolate
  service behavior from ASGI behavior. Fix lifecycle defects exposed by the
  tests and rerun the relevant backend checks.

**Pass evidence:** deterministic tests pass without sleeps or external calls;
the persisted result is retryable rather than left indefinitely streaming.
Separately verify browser abort behavior through the Next.js proxy during the
deployed check; an ASGI-only test does not prove proxy disconnect propagation.

## 3. Run the credentialed Gemini smoke test

**Prerequisites:** a development Gemini key and an available configured model.
Supply them through an untracked environment file or environment variables;
use synthetic prompts only.

From the backend with its virtual environment active:

```sh
RUN_GEMINI_MANUAL_TEST=1 python -m pytest tests/test_gemini_manual.py -q
```

**Pass evidence:** the existing test receives nonempty streamed text from the
real adapter. This checks provider connectivity; it does not prove end-to-end
UI streaming or Firestore persistence.

## 4. Run the deployed end-to-end checklist

**Prerequisites:** the intended GCP project/region, deploy access, billing and
budget alerts, and a Secret Manager model key. Use the existing
[deployment checklist](phase-1-deployment-checklist.md) and
[GCP guide](gcp-deployment.md).

- Build/deploy the intended revision and confirm required Firestore indexes
  are ready, API/web health works, and the idle worker is private.
- Create a synthetic chat in the browser, observe incremental output, refresh,
  and reopen it. Exercise regenerate, edit/retry, and a recoverable failed turn.
- Restart or replace the API instance and confirm the same history is returned.
- Abort a browser streaming request and verify proxy/provider cancellation and
  persisted failure state. Record any mismatch as an open defect.
- Review costs and follow the checklist's cleanup guidance for test resources.

**Pass evidence:** deployment revision, timestamp, service URLs where appropriate,
and pass/fail results. Store no secrets or chat content in the repo. The public
bootstrap uses a shared `local` owner and is for non-sensitive test data only.

## Closeout and next phase

Record each result separately in the verification record and deployment
checklist, including failures and unresolved gaps. Update the project brief
only when evidence supports the new status. Phase 1 acceptance is closed when
the persistence, disconnect, provider, and deployed checks all pass.

Then, when the user advances the phase, begin
[Phase 2](phase-2-implementation-plan.md) with synthetic long-thread baseline
fixtures and context contracts. Do not add memory or research features as part
of this verification work.
