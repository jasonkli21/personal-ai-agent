# Phase 9 operations runbook

This runbook is for one privately operated personal deployment. It is not an
incident-response service or a compliance claim. Keep synthetic staging and
production in separate GCP projects, service accounts, Neon databases, AWS
roles/tables, and Secret Manager secrets.

## Identity and access

- Browser requests go through the web service. The API accepts only the web
  runtime service account at Cloud Run IAM and then validates the end-user
  Google ID token itself.
- To remove user access, remove the exact allowlisted email and redeploy the
  API. Also disable/revoke the Google account/client when immediate revocation
  is needed; already-issued ID tokens can remain valid until token expiry.
- If the web-to-API boundary fails, verify the Web runtime service account has
  `roles/run.invoker` on the API service and that the API is not public.
  Do not grant project-wide `roles/run.invoker` to `allUsers`.
- Keep Pub/Sub and maintenance invokers separate. Pause the maintenance job
  with `gcloud scheduler jobs pause personal-ai-maintenance --location REGION`
  before investigating job backlog or data changes.

## Provider outage or emergency spend stop

- Set `EXTERNAL_PROVIDERS_KILL_SWITCH_ENABLED=true` to stop configured external
  model/search/domain provider operations. Set `CHAT_KILL_SWITCH_ENABLED` or
  `RESEARCH_KILL_SWITCH_ENABLED` to stop those capabilities independently.
- The API reserves a request-level estimate per provider-backed API operation
  against a per-owner UTC-day Postgres budget before the operation. A denied
  reservation returns 429 with a retry time. These estimates do not cover every context-counting, summary, extraction,
  embedding or worker call and do not guarantee an account spend ceiling.
  Reservations count as used even when a later provider call fails; `settled` is zero because usage metering is
  not yet reconciled from provider responses.
- Request rate windows are in DynamoDB and daily usage budgets are in Postgres
  so Cloud Run instances share the same limits. DynamoDB request windows expire
  through table TTL using numeric epoch-second values. Expired Postgres budget
  rows are removed in bounded batches by scheduled maintenance after their
  90-day retention. If either counter store is unavailable,
  protected requests fail closed with 503. Review request/error logs by route,
  request ID, status, duration, and error class; never enable request-body or
  authorization-header logging.
- No alert, dashboard, pager, or named on-call rotation is provisioned by this
  repository. The operator must create those before production access.

## Secrets and rotation

- Keep provider key values in Secret Manager or untracked local environment
  files. Source examples contain no credential values.
- Create a new numeric Secret Manager version, bind/deploy that version to a
  synthetic staging revision, verify the provider path, and retain the previous
  revision/version as the rollback target. Promote the same reviewed image and
  secret version only after staging. Disable the obsolete version after the
  rollback window. Never print secret values or include them in diagnostics.
- The deployment script takes a numeric secret version and binds it directly;
  its service accounts receive access only to the named model-key secret.

## Worker and maintenance

- API and worker runtime identities both need topic-scoped `roles/pubsub.publisher`: the worker maintenance path republishes pending notifications.
- Pub/Sub uses a dedicated invoker service account and a Google-signed token
  with the worker service URL as audience. Invalid payloads are acknowledged
  without logging payload bytes; transient storage/provider failures return
  503 so Pub/Sub retries.
- Maintenance has a different invoker identity and is bounded by a batch limit.
  It removes expired usage-budget rows, marks expired research sessions
  ineligible, and republishes durable pending memory job IDs. It does not
  physically delete user data.
- The bootstrap creates the 15-minute Cloud Scheduler job paused and leaves
  `MAINTENANCE_ENABLED=false`. Enable both only after a synthetic staging
  rehearsal proves duplicate, delayed, failed, and paused execution behavior.
  Dead-letter replay still requires an operator decision.
- This repository does not provision backups or restore workflows for the
  current Neon/Postgres and DynamoDB stores. Verify account-specific backup
  coverage and complete an isolated restore rehearsal before storing personal
  data; no target-store restore test is recorded.

## Rollback and recovery

- The deployment produces a unique Artifact Registry image tag from a clean
  committed revision and deploys each Cloud Run revision from that image. List
  revisions, inspect the deployed image digest and environment, then shift
  traffic to the previously approved revision using `gcloud run services
  update-traffic` for the affected service. Verify the API health and a
  synthetic authenticated request after rollback.
- Restore target stores only from tested backups in an isolated recovery
  environment first. Compare record counts and owner mappings before switching
  traffic. A restore may reintroduce data deleted from the primary stores; the
  current deployment has no deletion-aware backup ledger, so production restore
  is not approved until that behavior is implemented and rehearsed.
- The `/account` page exposes export and deletion controls only when their
  runtime flags are enabled. Export is a bounded, no-store JSON download.
  Deletion requests are audited
  and can be confirmed/cancelled, but they stop at
  `confirmed_pending_operator`: no automated physical deletion or completion
  certificate exists yet. Keep `EXPORT_ENABLED` and `DELETION_ENABLED` false in
  deployed environments until export fidelity and deletion propagation have
  been reviewed with synthetic data and a tested backup policy.

## Release gates

Before production use, complete the [Phase 9 release checklist](phase-9-release-checklist.md),
including staging login/chat/research/worker tests, provider policy review,
rate/budget probes, rollback, backup restore, export fidelity, deletion
propagation, evaluation comparison, and explicit operator approval. Current
automated checks do not prove Google IAM, Cloud Run, Neon, DynamoDB, Pub/Sub,
Secret Manager, or provider behavior.
