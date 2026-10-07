# Infrastructure

Deployment and local-environment definitions belong here. Keep provider-specific configuration isolated from application code.

- `gcp/` for Cloud Run, Pub/Sub, Secret Manager, and release deployment.
- `phase10/` for Neon/DynamoDB runtime, bootstrap, IAM, and strict-$0 templates.
- `../docker-compose.persistence.yml` for local Postgres/pgvector and DynamoDB
  Local. Firestore emulator/index assets are retired from the active setup.
