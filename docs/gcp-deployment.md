# GCP deployment

## Runtime architecture

```text
Browser
  |
  v
Cloud Run: public personal-ai-web (Next.js; Google sign-in shell)
  |  server-side /api proxy; web service identity plus end-user ID token
  v
Cloud Run: private personal-ai-api (FastAPI)
  |-- TLS transaction pooler --> Neon Postgres + pgvector
  |-- Google OIDC token -> AWS STS -> DynamoDB
  |-- hosted model/search providers
  '-- Pub/Sub --> private personal-ai-worker (bounded memory lifecycle jobs)
```

Neon/Postgres owns query-rich records, memories and vectors, research and
decision aggregates, account controls, and provider throttles. DynamoDB owns
conversations, messages, summaries, lifecycle job/guard state, and idempotency
records. Cloud Run, Pub/Sub, Google end-user authentication, and Secret Manager
remain on GCP. The application has no Firestore runtime path or migration
command.

P10.6 runtime wiring and Firestore dependency removal are implemented locally.
The user reports that Firestore was never deployed and no source data exists;
no cloud-account inventory independently verified that report, and no data
migration occurred. See the [P10.6 evidence](personal-ai-chapter-2/phase-10-p10.6-implementation-evidence.md)
for code checks, skipped target-engine/cloud checks, and remaining release gaps.

## Provisioning prerequisites

The deploy script creates and configures GCP service identities, Pub/Sub and
Cloud Scheduler resources, and Cloud Run services. It does not provision Neon
or DynamoDB. Before deployment:

1. Prepare a GCP project, OAuth web client, reviewed HTTPS origin, and billing
   budget/alerts. Authenticate with permissions for Cloud Run, Pub/Sub, Secret
   Manager, service accounts/IAM, Cloud Build, and Artifact Registry.
2. Provision a Neon database/schema using the Phase 10 migrations. Create a
   transaction-pooler DSN with TLS and put it in Secret Manager. Give the deploy
   operator permission to bind Secret Manager access; the script grants the API
   and worker identities access to the configured secret.
3. Provision the DynamoDB Standard table and required GSIs using
   [`infrastructure/phase10/dynamodb-cloudformation.yaml`](../infrastructure/phase10/dynamodb-cloudformation.yaml).
   Set up Google OIDC-to-AWS-STS trust from
   [`infrastructure/phase10/aws-google-oidc-trust-policy.json.tmpl`](../infrastructure/phase10/aws-google-oidc-trust-policy.json.tmpl)
   and grant only the runtime policy in
   [`infrastructure/phase10/dynamodb-runtime-policy.json.tmpl`](../infrastructure/phase10/dynamodb-runtime-policy.json.tmpl).
   Bootstrap/schema permissions are separate from runtime access.
4. Create the Gemini API-key secret and numeric version. Keep secret values out
   of repository files, logs, and command-line arguments.
5. Choose the exact allowed Google account and configure its matching OAuth
   client ID. Non-Gmail Workspace accounts also require the matching hosted
   domain claim.

## Deploy

Set these variables in the deployment shell. `NEON_RUNTIME_DSN_SECRET_VERSION`
and the model secret version must be explicit numeric versions; `latest` is
rejected.

```bash
export NEON_RUNTIME_DSN_SECRET_NAME=personal-ai-neon-runtime-dsn
export NEON_RUNTIME_DSN_SECRET_VERSION=1
export DYNAMODB_ROLE_ARN=arn:aws:iam::123456789012:role/personal-ai-runtime
export DYNAMODB_IDENTITY_TOKEN_AUDIENCE=https://aws.example/personal-ai

infrastructure/gcp/deploy.sh staging YOUR_STAGING_PROJECT us-central1 \
  personal-ai-gemini-api-key gemini-2.5-flash \
  YOUR_GOOGLE_OAUTH_WEB_CLIENT_ID.apps.googleusercontent.com \
  owner@gmail.com https://personal.example 2
```

Arguments are environment (`staging` or `production`), GCP project, region,
model-secret name, model ID, OAuth client ID, exact owner email, HTTPS web
origin, and numeric model-secret version. Optional variables are
`DYNAMODB_RUNTIME_TABLE_NAME` (default `personal-ai-runtime-v1`),
`DYNAMODB_AWS_REGION` (default `us-east-1`),
`MAINTENANCE_ENABLED`, `EXPORT_ENABLED`, and `DELETION_ENABLED` (default
`false`). The script refuses a dirty checkout. Production also requires
`PRODUCTION_DEPLOY_ACK=I_REVIEWED_THE_PRODUCTION_CHANGE` after staging and the
release gates pass.

The script enables required GCP APIs, verifies the named secrets and versions,
builds from the committed revision, resolves image tags to immutable digests,
and deploys separate web, API, and worker services. It creates separate runtime
and invoker identities, grants the web identity access to the private API,
configures authenticated Pub/Sub push, and creates the maintenance schedule
paused. The API and worker receive the Neon DSN and model key through explicit
Secret Manager versions. The runtime uses a Google service-account ID token to
exchange credentials with AWS STS; it does not receive static AWS keys.

The script does not run Neon migrations, create DynamoDB tables, establish
cross-cloud network paths, validate AWS trust/IAM, or prove cost eligibility.
Keep optional capability and maintenance gates off until their external
acceptance checks are complete. Deletion remains an operator-review workflow;
this implementation does not physically erase account data.

## Local and release verification

For local application use, configure `backend/.env` from
[`backend/.env.example`](../backend/.env.example), then run:

```bash
make persistence-up
make persistence-bootstrap
```

This starts local Postgres/pgvector and DynamoDB Local. Run `make persistence-test-up`
and `make persistence-test` for the isolated integration stack when Docker is
available. `make persistence-clean` is destructive to local persistence volumes.

After a deployment, use the [Phase 9 release checklist](phase-9-release-checklist.md)
for authentication, safeguards, and account workflows, and the
[Phase 10 migration/cutover verification plan](personal-ai-chapter-2/phase-10-migration-cutover-and-verification-plan.md)
for target-store persistence, recovery, IAM, and release evidence. The Phase 1
deployment checklist is a historical Firestore procedure and must not be used
for current deployments. A successful `/api/health` response confirms only
server-side web-to-API reachability; it does not exercise either database or
the model.

Cloud Run can scale to zero, but that does not establish a zero-cost deployment.
Review current account-specific Neon plan limits, DynamoDB table/GSI capacity,
cross-cloud egress, GCP quotas, external providers, and model usage. The
[strict-$0 validator](../infrastructure/phase10/strict_zero_release_gate.py)
needs current reviewed evidence; fake/unit tests and local DynamoDB do not prove
cloud IAM, production capacity, GSI behavior, or free-tier eligibility.

## Security boundary

The public web service exposes the sign-in shell. The API is private to the web
runtime service account and separately validates the end-user Google ID token.
Development `local` identity is allowed only in local/test configurations.
Cloud Run IAM and application identity are separate checks. Google-to-AWS
federation must bind the exact configured audience and runtime service-account
subject. Production remains blocked until staged identity, database, provider,
recovery, export/deletion, cost, and operational release checks have evidence.

Earlier phase guides and Firestore ADRs are historical records of the prior
implementation; they are not current deployment instructions.
