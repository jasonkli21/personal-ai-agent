# GCP deployment

The runnable initial topology is defined in [the deployment guide](../../docs/gcp-deployment.md). `deploy.sh` creates or reuses the minimum GCP resources, then deploys three Cloud Run services:

- `personal-ai-api` — FastAPI API.
- `personal-ai-worker` — Pub/Sub push target for asynchronous work.
- `personal-ai-web` — Next.js UI, including `/api/health`, which verifies API connectivity server-side.

Use `deploy.sh PROJECT_ID REGION` after installing and authenticating the Google Cloud CLI. Default region: `us-central1`.
