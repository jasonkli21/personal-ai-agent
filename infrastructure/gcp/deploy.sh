#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID=${1:?Usage: deploy.sh PROJECT_ID [REGION] [MODEL_SECRET_NAME] [AI_MODEL]}
REGION=${2:-us-central1}
MODEL_SECRET_NAME=${3:-personal-ai-gemini-api-key}
AI_MODEL=${4:-gemini-2.5-flash}
ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TOPIC=personal-ai-async
WORKER_INVOKER_SA=personal-ai-pubsub-invoker
API_SA=personal-ai-api-runtime
WORKER_RUNTIME_SA=personal-ai-worker-runtime

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com firestore.googleapis.com pubsub.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

if ! gcloud secrets describe "$MODEL_SECRET_NAME" >/dev/null 2>&1; then
  echo "Secret '$MODEL_SECRET_NAME' does not exist. Create it first; its value must be a Gemini API key." >&2
  exit 1
fi

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
gcloud iam service-accounts describe "$API_SA@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$API_SA" --display-name="Personal AI API runtime"
API_RUNTIME_SA="$API_SA@$PROJECT_ID.iam.gserviceaccount.com"
gcloud secrets add-iam-policy-binding "$MODEL_SECRET_NAME" \
  --member="serviceAccount:$API_RUNTIME_SA" \
  --role='roles/secretmanager.secretAccessor' >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$API_RUNTIME_SA" \
  --role='roles/datastore.user' >/dev/null

if ! gcloud firestore databases describe --database='(default)' >/dev/null 2>&1; then
  gcloud firestore databases create --location="$REGION" --database='(default)' --type=firestore-native
fi

if [[ -z "$(gcloud firestore indexes composite list --database='(default)' \
  --filter='collectionGroup=conversations AND fields.fieldPath=owner_id AND fields.fieldPath=updated_at' \
  --format='value(name)' --limit=1)" ]]; then
  gcloud firestore indexes composite create \
    --database='(default)' \
    --collection-group=conversations \
    --field-config=field-path=owner_id,order=ascending \
    --field-config=field-path=updated_at,order=descending
fi

if [[ -z "$(gcloud firestore indexes composite list --database='(default)' \
  --filter='collectionGroup=messages AND fields.fieldPath=owner_id AND fields.fieldPath=conversation_id AND fields.fieldPath=created_at' \
  --format='value(name)' --limit=1)" ]]; then
  gcloud firestore indexes composite create \
    --database='(default)' \
    --collection-group=messages \
    --field-config=field-path=owner_id,order=ascending \
    --field-config=field-path=conversation_id,order=ascending \
    --field-config=field-path=created_at,order=ascending
fi

if [[ -z "$(gcloud firestore indexes composite list --database='(default)' \
  --filter='collectionGroup=conversation_summaries AND fields.fieldPath=owner_id AND fields.fieldPath=conversation_id' \
  --format='value(name)' --limit=1)" ]]; then
  gcloud firestore indexes composite create \
    --database='(default)' \
    --collection-group=conversation_summaries \
    --field-config=field-path=owner_id,order=ascending \
    --field-config=field-path=conversation_id,order=ascending
fi

gcloud pubsub topics describe "$TOPIC" >/dev/null 2>&1 || gcloud pubsub topics create "$TOPIC"
gcloud iam service-accounts describe "$API_SA@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$API_SA" --display-name="Personal AI API runtime"
gcloud iam service-accounts describe "$WORKER_RUNTIME_SA@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$WORKER_RUNTIME_SA" --display-name="Personal AI worker runtime"
gcloud iam service-accounts describe "$WORKER_INVOKER_SA@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$WORKER_INVOKER_SA" --display-name="Personal AI Pub/Sub invoker"
WORKER_RUNTIME_EMAIL="$WORKER_RUNTIME_SA@$PROJECT_ID.iam.gserviceaccount.com"
WORKER_INVOKER_EMAIL="$WORKER_INVOKER_SA@$PROJECT_ID.iam.gserviceaccount.com"
gcloud secrets add-iam-policy-binding "$MODEL_SECRET_NAME" \
  --member="serviceAccount:$WORKER_RUNTIME_EMAIL" \
  --role='roles/secretmanager.secretAccessor' >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$WORKER_RUNTIME_EMAIL" \
  --role='roles/datastore.user' >/dev/null
gcloud pubsub topics add-iam-policy-binding "$TOPIC" \
  --member="serviceAccount:$API_RUNTIME_SA" \
  --role='roles/pubsub.publisher' >/dev/null

gcloud run deploy personal-ai-api \
  --source="$ROOT_DIR/backend" \
  --region="$REGION" \
  --allow-unauthenticated \
  --min-instances=0 \
  --service-account="$API_RUNTIME_SA" \
  --set-env-vars="AI_PROVIDER=gemini,AI_MODEL=$AI_MODEL,DATABASE_BACKEND=firestore,FIRESTORE_PROJECT_ID=$PROJECT_ID,CONTEXT_INSPECTION_ENABLED=false,RESEARCH_ENABLED=false,RESEARCH_INSPECTION_ENABLED=false,RESEARCH_PROVIDER_STORAGE_APPROVED=false,MEMORY_ENABLED=false,MEMORY_EXTRACTION_ENABLED=false,MEMORY_INSPECTION_ENABLED=false,MEMORY_EXPERIMENT_VARIANT=fixed,MEMORY_LIFECYCLE_WORKER_ENABLED=false,MEMORY_CONSOLIDATION_ENABLED=false,MEMORY_CONTRADICTION_AUTOMATION_ENABLED=false,MEMORY_FORGETTING_ENABLED=false,MEMORY_LIFECYCLE_INSPECTION_ENABLED=false,MEMORY_LIFECYCLE_TOPIC=$TOPIC" \
  --set-secrets="AI_API_KEY=$MODEL_SECRET_NAME:latest"

API_URL=$(gcloud run services describe personal-ai-api --region="$REGION" --format='value(status.url)')

gcloud run deploy personal-ai-worker \
  --source="$ROOT_DIR/backend" \
  --region="$REGION" \
  --no-allow-unauthenticated \
  --min-instances=0 \
  --service-account="$WORKER_RUNTIME_EMAIL" \
  --command=uvicorn \
  --args="personal_ai.worker:app,--host=0.0.0.0,--port=8080" \
  --set-env-vars="AI_PROVIDER=gemini,AI_MODEL=$AI_MODEL,DATABASE_BACKEND=firestore,FIRESTORE_PROJECT_ID=$PROJECT_ID,MEMORY_ENABLED=false,MEMORY_EXTRACTION_ENABLED=false,MEMORY_INSPECTION_ENABLED=false,MEMORY_EXPERIMENT_VARIANT=fixed,MEMORY_LIFECYCLE_WORKER_ENABLED=false,MEMORY_CONSOLIDATION_ENABLED=false,MEMORY_CONTRADICTION_AUTOMATION_ENABLED=false,MEMORY_FORGETTING_ENABLED=false,MEMORY_LIFECYCLE_INSPECTION_ENABLED=false,MEMORY_LIFECYCLE_TOPIC=$TOPIC" \
  --set-secrets="AI_API_KEY=$MODEL_SECRET_NAME:latest"

WORKER_URL=$(gcloud run services describe personal-ai-worker --region="$REGION" --format='value(status.url)')
gcloud run services add-iam-policy-binding personal-ai-worker \
  --region="$REGION" \
  --member="serviceAccount:$WORKER_INVOKER_EMAIL" \
  --role='roles/run.invoker'

gcloud iam service-accounts add-iam-policy-binding "$WORKER_INVOKER_EMAIL" \
  --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role='roles/iam.serviceAccountTokenCreator'

if gcloud pubsub subscriptions describe personal-ai-worker >/dev/null 2>&1; then
  gcloud pubsub subscriptions update personal-ai-worker \
    --push-endpoint="$WORKER_URL/tasks/memory" \
    --push-auth-service-account="$WORKER_INVOKER_EMAIL"
else
  gcloud pubsub subscriptions create personal-ai-worker \
    --topic="$TOPIC" \
    --push-endpoint="$WORKER_URL/tasks/memory" \
    --push-auth-service-account="$WORKER_INVOKER_EMAIL"
fi

gcloud run deploy personal-ai-web \
  --source="$ROOT_DIR/frontend" \
  --region="$REGION" \
  --allow-unauthenticated \
  --min-instances=0 \
  --set-env-vars="API_BASE_URL=$API_URL,CONTEXT_INSPECTION_ENABLED=false,RESEARCH_ENABLED=false,RESEARCH_INSPECTION_ENABLED=false,RESEARCH_PROVIDER_STORAGE_APPROVED=false,MEMORY_INSPECTION_ENABLED=false,MEMORY_LIFECYCLE_INSPECTION_ENABLED=false"

WEB_URL=$(gcloud run services describe personal-ai-web --region="$REGION" --format='value(status.url)')
echo "Deployment complete: $WEB_URL"
echo "Verify API connectivity: $WEB_URL/api/health"
