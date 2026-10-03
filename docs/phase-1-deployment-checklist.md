# Phase 1 deployment checklist

Use this baseline chat checklist with the current authenticated deployment
and the [Phase 9 release checklist](phase-9-release-checklist.md). Record only URLs,
timestamps, commit IDs, and pass/fail results; never record model keys, chat
content, or other personal data.

## Before deployment

- [ ] Billing is enabled, a budget exists, and at least one budget alert is enabled.
- [ ] The deployer is authenticated to the intended project and region.
- [ ] A Secret Manager secret containing the Gemini API key exists (default:
  `personal-ai-gemini-api-key`) and has an enabled version.
- [ ] `AI_MODEL` is available to that key. Choose it as the fifth deploy-script argument rather than editing source.
- [ ] Configure a Google OAuth web client, exact allowed account, HTTPS web
  origin and numeric secret version. Use a separate synthetic staging project.
- [ ] Confirm production acceptance remains blocked until the Phase 9 release
  checks have evidence; do not enter personal data during rehearsal.

## Deploy

- [ ] Run `infrastructure/gcp/deploy.sh staging PROJECT_ID REGION SECRET_NAME AI_MODEL OAUTH_CLIENT_ID OWNER_EMAIL HTTPS_WEB_ORIGIN NUMERIC_SECRET_VERSION`.
- [ ] Save the printed web URL and verify the script did not print a secret.
- [ ] Confirm `personal-ai-api`, `personal-ai-web`, and `personal-ai-worker` are
  deployed. The worker may remain idle; Phase 1 chat must publish no Pub/Sub
  messages.
- [ ] Confirm the deploy script created or reused the required `conversations`
  and `messages` composite indexes before testing queries.

## Smoke test

- [ ] Open `WEB_URL/api/health`; it returns HTTP 200 with `web: "ok"` and API
  status `ok`.
- [ ] Open `WEB_URL`, verify the sign-in shell, and sign in with the allowlisted
  synthetic account. Confirm unauthenticated API access is rejected.
- [ ] Verify the API admits the web runtime identity and the worker admits only
  its configured invokers; inspect inherited IAM as well as service bindings.
- [ ] Create a conversation using non-sensitive test text.
- [ ] Send one short message and confirm streamed text finishes successfully.
- [ ] Refresh the browser, reopen the conversation, and confirm the final user
  and assistant messages remain.
- [ ] In the Firestore console, verify the corresponding `conversations` and
  `messages` records exist. Do not copy message contents into a ticket or note.

## Cleanup

- [ ] Review the budget/usage after testing.
- [ ] Delete test conversations manually if they should not remain in Firestore.
- [ ] Disable or delete the model-key secret version when the environment is no
  longer needed, subject to any retention policy.
- [ ] To remove the disposable environment, delete the Cloud Run services,
  Pub/Sub subscription/topic, and Firestore database only after confirming the
  target project and that no data must be retained. These actions are
  destructive and are intentionally not automated by `deploy.sh`.

## Verification record

| Item | Result | Evidence |
| --- | --- | --- |
| Local backend tests | Passed 2026-10-01 | 69 passed, 1 credentialed manual test skipped |
| Local backend lint | Passed 2026-10-01 | Ruff reported all checks passed |
| Local frontend tests | Passed 2026-10-01 | 27 passed |
| Local frontend lint/type-check | Passed 2026-10-01 | ESLint and `tsc --noEmit` completed successfully |
| Firestore Emulator persistence across API restart | Not run | See verification closeout plan |
| Automated client-disconnect integration | Passed locally 2026-10-01 | ASGI send/disconnect, provider teardown, proxy abort, and frontend interruption regressions; deployed browser check remains pending |
| Credentialed Gemini smoke test | Not run | Opt-in manual test remains skipped |
| Credentialed deployed smoke test | Not run | Requires user-supplied GCP access and a Gemini key; use Smoke test above. |

This record deliberately does not claim a cloud deployment or smoke test that
has not been performed in this repository session.

See the [verification record](releases/phase-1-vertical-slice.md) for the tested
revision and local execution details, and the
[verification closeout plan](phase-1-verification-plan.md) for remaining work.
