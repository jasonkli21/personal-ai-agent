# Phase 1 deployment checklist

Use this checklist for every credentialed Phase 1 deployment. Record only URLs,
timestamps, commit IDs, and pass/fail results; never record model keys, chat
content, or other personal data.

## Before deployment

- [ ] Billing is enabled, a budget exists, and at least one budget alert is enabled.
- [ ] The deployer is authenticated to the intended project and region.
- [ ] A Secret Manager secret containing the Gemini API key exists (default:
  `personal-ai-gemini-api-key`) and has an enabled version.
- [ ] `AI_MODEL` is available to that key. Choose it as the fourth deploy-script
  argument rather than editing source.
- [ ] The public, unauthenticated bootstrap is acceptable only for non-sensitive
  test data. Do not enter personal data.

## Deploy

- [ ] Run `infrastructure/gcp/deploy.sh PROJECT_ID REGION SECRET_NAME AI_MODEL`.
- [ ] Save the printed web URL and verify the script did not print a secret.
- [ ] Confirm `personal-ai-api`, `personal-ai-web`, and `personal-ai-worker` are
  deployed. The worker may remain idle; Phase 1 chat must publish no Pub/Sub
  messages.
- [ ] Confirm the deploy script created or reused the required `conversations`
  and `messages` composite indexes before testing queries.

## Smoke test

- [ ] Open `WEB_URL/api/health`; it returns HTTP 200 with `web: "ok"` and API
  status `ok`.
- [ ] Open `WEB_URL` and confirm the chat shell loads.
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
| Local backend tests | Passed 2026-08-19 | 30 passed, 1 credentialed manual test skipped |
| Local backend lint | Passed 2026-08-19 | Ruff reported all checks passed |
| Local frontend tests | Passed 2026-08-19 | 8 passed |
| Local frontend lint/type-check | Passed 2026-08-19 | ESLint and `tsc --noEmit` completed successfully |
| Credentialed deployed smoke test | Not run | Requires user-supplied GCP access and a Gemini key; use Smoke test above. |

This record deliberately does not claim a cloud deployment or smoke test that
has not been performed in this repository session.
