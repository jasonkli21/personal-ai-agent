#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID=${1:?Usage: deploy.sh PROJECT_ID [REGION]}
REGION=${2:-us-central1}
ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TOPIC=personal-ai-async
WORKER_SA=personal-ai-pubsub-invoker

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com firestore.googleapis.com pubsub.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

if ! gcloud firestore databases describe --database='(default)' >/dev/null 2>&1; then
  gcloud firestore databases create --location="$REGION" --database='(default)' --type=firestore-native
fi

gcloud pubsub topics describe "$TOPIC" >/dev/null 2>&1 || gcloud pubsub topics create "$TOPIC"
gcloud iam service-accounts describe "$WORKER_SA@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$WORKER_SA" --display-name="Personal AI Pub/Sub invoker"

gcloud run deploy personal-ai-api \
  --source="$ROOT_DIR/backend" \
  --region="$REGION" \
  --allow-unauthenticated \
  --min-instances=0 \
  --set-env-vars="DATABASE_BACKEND=firestore"

API_URL=$(gcloud run services describe personal-ai-api --region="$REGION" --format='value(status.url)')

gcloud run deploy personal-ai-worker \
  --source="$ROOT_DIR/backend" \
  --region="$REGION" \
  --no-allow-unauthenticated \
  --min-instances=0

WORKER_URL=$(gcloud run services describe personal-ai-worker --region="$REGION" --format='value(status.url)')
gcloud run services add-iam-policy-binding personal-ai-worker \
  --region="$REGION" \
  --member="serviceAccount:$WORKER_SA@$PROJECT_ID.iam.gserviceaccount.com" \
  --role='roles/run.invoker'

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
gcloud iam service-accounts add-iam-policy-binding "$WORKER_SA@$PROJECT_ID.iam.gserviceaccount.com" \
  --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role='roles/iam.serviceAccountTokenCreator'

gcloud pubsub subscriptions describe personal-ai-worker >/dev/null 2>&1 || \
  gcloud pubsub subscriptions create personal-ai-worker \
    --topic="$TOPIC" \
    --push-endpoint="$WORKER_URL/tasks/research" \
    --push-auth-service-account="$WORKER_SA@$PROJECT_ID.iam.gserviceaccount.com"

gcloud run deploy personal-ai-web \
  --source="$ROOT_DIR/frontend" \
  --region="$REGION" \
  --allow-unauthenticated \
  --min-instances=0 \
  --set-env-vars="API_BASE_URL=$API_URL"

WEB_URL=$(gcloud run services describe personal-ai-web --region="$REGION" --format='value(status.url)')
echo "Deployment complete: $WEB_URL"
echo "Verify API connectivity: $WEB_URL/api/health"
