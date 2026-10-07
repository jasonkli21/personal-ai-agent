# GCP deployment assets

The deployment topology and operator prerequisites are documented in the
[GCP deployment guide](../../docs/gcp-deployment.md). `deploy.sh` creates the
Cloud Run web/API/worker services and supporting GCP identities, Pub/Sub, and
paused maintenance schedule. It expects Neon and DynamoDB to be provisioned
separately and takes explicit Secret Manager versions and AWS federation
settings.

The active runtime stores query-rich records and vectors in Neon/Postgres and
conversation/runtime state in DynamoDB. Cloud Run exchanges its Google service
identity token through AWS STS for DynamoDB access. Firestore index definitions,
emulator instructions, provisioning, and IAM grants are no longer part of the
active deployment.

The script's local checks are `bash -n infrastructure/gcp/deploy.sh` and
`backend/tests/test_deployment_script.py`. A passing fake-script test does not
establish deployed GCP/AWS/Neon connectivity or strict-$0 eligibility.
