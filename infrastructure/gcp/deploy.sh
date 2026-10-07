#!/usr/bin/env bash
set -euo pipefail

TARGET_ENV=${1:?Usage: deploy.sh staging|production PROJECT_ID REGION MODEL_SECRET_NAME AI_MODEL GOOGLE_OAUTH_CLIENT_ID ALLOWED_OWNER_EMAIL WEB_ORIGIN MODEL_SECRET_VERSION}
PROJECT_ID=${2:?Usage: deploy.sh staging|production PROJECT_ID REGION MODEL_SECRET_NAME AI_MODEL GOOGLE_OAUTH_CLIENT_ID ALLOWED_OWNER_EMAIL WEB_ORIGIN MODEL_SECRET_VERSION}
REGION=${3:-us-central1}
MODEL_SECRET_NAME=${4:-personal-ai-gemini-api-key}
AI_MODEL=${5:-gemini-2.5-flash}
GOOGLE_OAUTH_CLIENT_ID=${6:?Set the Google OAuth web client ID as argument 6}
ALLOWED_OWNER_EMAIL=${7:?Set the exact allowed Google account email as argument 7}
WEB_ORIGIN=${8:?Set the exact HTTPS web origin as argument 8}
MODEL_SECRET_VERSION=${9:?Set an explicit numeric Secret Manager version as argument 9}
MAINTENANCE_ENABLED=${MAINTENANCE_ENABLED:-false}
EXPORT_ENABLED=${EXPORT_ENABLED:-false}
DELETION_ENABLED=${DELETION_ENABLED:-false}
if [[ ! "$MAINTENANCE_ENABLED" =~ ^(true|false)$ || \
      ! "$EXPORT_ENABLED" =~ ^(true|false)$ || ! "$DELETION_ENABLED" =~ ^(true|false)$ ]]; then
  echo "MAINTENANCE_ENABLED, EXPORT_ENABLED, and DELETION_ENABLED must be true or false." >&2
  exit 2
fi
NEON_RUNTIME_DSN_SECRET_NAME=${NEON_RUNTIME_DSN_SECRET_NAME:?Set the Secret Manager secret containing the Neon transaction-pooler DSN}
NEON_RUNTIME_DSN_SECRET_VERSION=${NEON_RUNTIME_DSN_SECRET_VERSION:?Set the numeric Neon DSN secret version}
DYNAMODB_RUNTIME_TABLE_NAME=${DYNAMODB_RUNTIME_TABLE_NAME:-personal-ai-runtime-v1}
DYNAMODB_AWS_REGION=${DYNAMODB_AWS_REGION:-us-east-1}
DYNAMODB_ROLE_ARN=${DYNAMODB_ROLE_ARN:?Set the least-privilege AWS runtime role ARN}
DYNAMODB_IDENTITY_TOKEN_AUDIENCE=${DYNAMODB_IDENTITY_TOKEN_AUDIENCE:?Set the HTTPS audience trusted by the AWS role}
if [[ ! "$AI_MODEL" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Model identifier contains unsupported characters." >&2
  exit 2
fi
if [[ ! "$MODEL_SECRET_VERSION" =~ ^[1-9][0-9]*$ ]]; then
  echo "Use an explicit numeric Secret Manager version; 'latest' is not permitted." >&2
  exit 2
fi
if [[ ! "$NEON_RUNTIME_DSN_SECRET_VERSION" =~ ^[1-9][0-9]*$ ]]; then
  echo "Use an explicit numeric Neon DSN Secret Manager version; 'latest' is not permitted." >&2
  exit 2
fi
if [[ ! "$DYNAMODB_RUNTIME_TABLE_NAME" =~ ^[A-Za-z0-9_.-]{3,255}$ || \
      ! "$DYNAMODB_AWS_REGION" =~ ^[a-z]{2}(-gov)?-[a-z]+-[0-9]$ || \
      ! "$DYNAMODB_ROLE_ARN" =~ ^arn:(aws|aws-us-gov|aws-cn):iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+$ || \
      ! "$DYNAMODB_IDENTITY_TOKEN_AUDIENCE" =~ ^https://[A-Za-z0-9.-]+(/[^[:space:]]*)?$ ]]; then
  echo "Neon/DynamoDB runtime settings are invalid." >&2
  exit 2
fi

if [[ "$TARGET_ENV" != "staging" && "$TARGET_ENV" != "production" ]]; then
  echo "Target environment must be staging or production." >&2
  exit 2
fi
if [[ "$TARGET_ENV" == "production" && "${PRODUCTION_DEPLOY_ACK:-}" != "I_REVIEWED_THE_PRODUCTION_CHANGE" ]]; then
  echo "Production requires PRODUCTION_DEPLOY_ACK=I_REVIEWED_THE_PRODUCTION_CHANGE after a staging rehearsal." >&2
  exit 2
fi
if [[ ! "$GOOGLE_OAUTH_CLIENT_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Google OAuth client ID contains unsupported characters." >&2
  exit 2
fi
if [[ ! "$ALLOWED_OWNER_EMAIL" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$ ]]; then
  echo "Allowed owner email must be a single plain email address." >&2
  exit 2
fi
ALLOWED_OWNER_EMAIL=$(printf '%s' "$ALLOWED_OWNER_EMAIL" | tr '[:upper:]' '[:lower:]')
OWNER_DOMAIN=${ALLOWED_OWNER_EMAIL##*@}
AUTH_HOSTED_DOMAIN=""
if [[ "$OWNER_DOMAIN" != "gmail.com" ]]; then AUTH_HOSTED_DOMAIN="$OWNER_DOMAIN"; fi
if [[ ! "$WEB_ORIGIN" =~ ^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?$ ]]; then
  echo "Web origin must be one exact HTTPS origin without a path." >&2
  exit 2
fi

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
if [[ -n "$(git -C "$ROOT_DIR" status --porcelain)" ]]; then
  echo "Deploy only from a clean committed revision after review." >&2
  exit 2
fi
GIT_REVISION=$(git -C "$ROOT_DIR" rev-parse --short=12 HEAD)
BUILD_TAG="$GIT_REVISION-$TARGET_ENV-$(date -u +%Y%m%dT%H%M%SZ)"
ARTIFACT_REPOSITORY=personal-ai
BACKEND_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$ARTIFACT_REPOSITORY/backend:$BUILD_TAG"
FRONTEND_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$ARTIFACT_REPOSITORY/frontend:$BUILD_TAG"
TOPIC=personal-ai-async
API_SERVICE=personal-ai-api
WEB_SERVICE=personal-ai-web
WORKER_SERVICE=personal-ai-worker
API_SA=personal-ai-api-runtime
WEB_SA=personal-ai-web-runtime
WORKER_RUNTIME_SA=personal-ai-worker-runtime
WORKER_INVOKER_SA=personal-ai-pubsub-invoker
MAINTENANCE_INVOKER_SA=personal-ai-maintenance-invoker
API_ENV_FILE=$(mktemp)
WEB_ENV_FILE=$(mktemp)
WORKER_ENV_FILE=$(mktemp)
trap 'rm -f "$API_ENV_FILE" "$WEB_ENV_FILE" "$WORKER_ENV_FILE"' EXIT

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com pubsub.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

if ! gcloud secrets describe "$MODEL_SECRET_NAME" >/dev/null 2>&1; then
  echo "Secret '$MODEL_SECRET_NAME' does not exist. Create it first; its value must be a Gemini API key." >&2
  exit 1
fi
if ! gcloud secrets versions describe "$MODEL_SECRET_VERSION" --secret="$MODEL_SECRET_NAME" >/dev/null 2>&1; then
  echo "Secret version '$MODEL_SECRET_VERSION' does not exist." >&2
  exit 1
fi
if ! gcloud secrets describe "$NEON_RUNTIME_DSN_SECRET_NAME" >/dev/null 2>&1; then
  echo "Neon DSN secret '$NEON_RUNTIME_DSN_SECRET_NAME' does not exist." >&2
  exit 1
fi
if ! gcloud secrets versions describe "$NEON_RUNTIME_DSN_SECRET_VERSION" --secret="$NEON_RUNTIME_DSN_SECRET_NAME" >/dev/null 2>&1; then
  echo "Neon DSN secret version '$NEON_RUNTIME_DSN_SECRET_VERSION' does not exist." >&2
  exit 1
fi
gcloud artifacts repositories describe "$ARTIFACT_REPOSITORY" --location="$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$ARTIFACT_REPOSITORY" --location="$REGION" \
    --repository-format=docker --description="Reviewed Personal AI release images"

create_service_account() {
  local name=$1
  gcloud iam service-accounts describe "$name@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1 || \
    gcloud iam service-accounts create "$name" --display-name="$name"
}

create_service_account "$API_SA"
create_service_account "$WEB_SA"
create_service_account "$WORKER_RUNTIME_SA"
create_service_account "$WORKER_INVOKER_SA"
create_service_account "$MAINTENANCE_INVOKER_SA"
API_RUNTIME_EMAIL="$API_SA@$PROJECT_ID.iam.gserviceaccount.com"
WEB_RUNTIME_EMAIL="$WEB_SA@$PROJECT_ID.iam.gserviceaccount.com"
WORKER_RUNTIME_EMAIL="$WORKER_RUNTIME_SA@$PROJECT_ID.iam.gserviceaccount.com"
WORKER_INVOKER_EMAIL="$WORKER_INVOKER_SA@$PROJECT_ID.iam.gserviceaccount.com"
MAINTENANCE_INVOKER_EMAIL="$MAINTENANCE_INVOKER_SA@$PROJECT_ID.iam.gserviceaccount.com"

gcloud secrets add-iam-policy-binding "$MODEL_SECRET_NAME" \
  --member="serviceAccount:$API_RUNTIME_EMAIL" --role='roles/secretmanager.secretAccessor' >/dev/null
gcloud secrets add-iam-policy-binding "$MODEL_SECRET_NAME" \
  --member="serviceAccount:$WORKER_RUNTIME_EMAIL" --role='roles/secretmanager.secretAccessor' >/dev/null
gcloud secrets add-iam-policy-binding "$NEON_RUNTIME_DSN_SECRET_NAME" \
  --member="serviceAccount:$API_RUNTIME_EMAIL" --role='roles/secretmanager.secretAccessor' >/dev/null
gcloud secrets add-iam-policy-binding "$NEON_RUNTIME_DSN_SECRET_NAME" \
  --member="serviceAccount:$WORKER_RUNTIME_EMAIL" --role='roles/secretmanager.secretAccessor' >/dev/null
gcloud pubsub topics describe "$TOPIC" >/dev/null 2>&1 || gcloud pubsub topics create "$TOPIC"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
gcloud pubsub topics add-iam-policy-binding "$TOPIC" \
  --member="serviceAccount:$API_RUNTIME_EMAIL" --role='roles/pubsub.publisher' >/dev/null
gcloud pubsub topics add-iam-policy-binding "$TOPIC" \
  --member="serviceAccount:$WORKER_RUNTIME_EMAIL" --role='roles/pubsub.publisher' >/dev/null

cat >"$API_ENV_FILE" <<EOF
APP_ENVIRONMENT: $TARGET_ENV
GCP_PROJECT_ID: $PROJECT_ID
P10_CLOUD_ADAPTERS_CONFIGURED: "true"
P10_DYNAMODB_REGION: $DYNAMODB_AWS_REGION
P10_DYNAMODB_TABLE_NAME: $DYNAMODB_RUNTIME_TABLE_NAME
P10_DYNAMODB_ROLE_ARN: $DYNAMODB_ROLE_ARN
P10_DYNAMODB_IDENTITY_TOKEN_AUDIENCE: $DYNAMODB_IDENTITY_TOKEN_AUDIENCE
P10_NEON_POOL_MAX_SIZE: "4"
AI_PROVIDER: gemini
AI_MODEL: $AI_MODEL
AUTH_MODE: google_oidc
AUTH_REQUIRED: "true"
AUTH_ISSUER: https://accounts.google.com
AUTH_AUDIENCE: $GOOGLE_OAUTH_CLIENT_ID
AUTH_ALLOWED_EMAILS: '["$ALLOWED_OWNER_EMAIL"]'
AUTH_HOSTED_DOMAIN: "$AUTH_HOSTED_DOMAIN"
AUTH_RECENT_TOKEN_SECONDS: "300"
ALLOWED_ORIGINS: '["$WEB_ORIGIN"]'
OBSERVABILITY_REDACTION_VERSION: redaction-v1
API_RATE_LIMIT_PER_MINUTE: "60"
PROVIDER_CALLS_PER_DAY_LIMIT: "100"
INPUT_TOKENS_PER_DAY_LIMIT: "200000"
CHAT_KILL_SWITCH_ENABLED: "false"
RESEARCH_KILL_SWITCH_ENABLED: "false"
WORKER_KILL_SWITCH_ENABLED: "false"
EXTERNAL_PROVIDERS_KILL_SWITCH_ENABLED: "false"
MAINTENANCE_ENABLED: "$MAINTENANCE_ENABLED"
MAINTENANCE_BATCH_SIZE: "40"
EXPORT_ENABLED: "$EXPORT_ENABLED"
DELETION_ENABLED: "$DELETION_ENABLED"
CONTEXT_INSPECTION_ENABLED: "false"
RESEARCH_ENABLED: "false"
RESEARCH_INSPECTION_ENABLED: "false"
RESEARCH_PROVIDER_STORAGE_APPROVED: "false"
MEMORY_ENABLED: "false"
MEMORY_EXTRACTION_ENABLED: "false"
MEMORY_INSPECTION_ENABLED: "false"
MEMORY_EXPERIMENT_VARIANT: fixed
MEMORY_LIFECYCLE_WORKER_ENABLED: "false"
MEMORY_CONSOLIDATION_ENABLED: "false"
MEMORY_CONTRADICTION_AUTOMATION_ENABLED: "false"
MEMORY_FORGETTING_ENABLED: "false"
MEMORY_LIFECYCLE_INSPECTION_ENABLED: "false"
MEMORY_LIFECYCLE_TOPIC: $TOPIC
EOF

cat >"$WORKER_ENV_FILE" <<EOF
APP_ENVIRONMENT: $TARGET_ENV
GCP_PROJECT_ID: $PROJECT_ID
P10_CLOUD_ADAPTERS_CONFIGURED: "true"
P10_DYNAMODB_REGION: $DYNAMODB_AWS_REGION
P10_DYNAMODB_TABLE_NAME: $DYNAMODB_RUNTIME_TABLE_NAME
P10_DYNAMODB_ROLE_ARN: $DYNAMODB_ROLE_ARN
P10_DYNAMODB_IDENTITY_TOKEN_AUDIENCE: $DYNAMODB_IDENTITY_TOKEN_AUDIENCE
P10_NEON_POOL_MAX_SIZE: "2"
AI_PROVIDER: gemini
AI_MODEL: $AI_MODEL
AUTH_MODE: google_oidc
AUTH_REQUIRED: "true"
AUTH_ISSUER: https://accounts.google.com
AUTH_AUDIENCE: $GOOGLE_OAUTH_CLIENT_ID
AUTH_ALLOWED_EMAILS: '["$ALLOWED_OWNER_EMAIL"]'
AUTH_HOSTED_DOMAIN: "$AUTH_HOSTED_DOMAIN"
AUTH_RECENT_TOKEN_SECONDS: "300"
ALLOWED_ORIGINS: '["$WEB_ORIGIN"]'
WORKER_KILL_SWITCH_ENABLED: "false"
WORKER_PUSH_AUTH_REQUIRED: "true"
WORKER_MAINTENANCE_AUTH_REQUIRED: "true"
MAINTENANCE_ENABLED: "$MAINTENANCE_ENABLED"
MAINTENANCE_BATCH_SIZE: "40"
MEMORY_ENABLED: "false"
MEMORY_EXTRACTION_ENABLED: "false"
MEMORY_INSPECTION_ENABLED: "false"
MEMORY_EXPERIMENT_VARIANT: fixed
MEMORY_LIFECYCLE_WORKER_ENABLED: "false"
MEMORY_CONSOLIDATION_ENABLED: "false"
MEMORY_CONTRADICTION_AUTOMATION_ENABLED: "false"
MEMORY_FORGETTING_ENABLED: "false"
MEMORY_LIFECYCLE_INSPECTION_ENABLED: "false"
MEMORY_LIFECYCLE_TOPIC: $TOPIC
EOF

gcloud builds submit "$ROOT_DIR/backend" --project="$PROJECT_ID" --region="$REGION" --tag="$BACKEND_IMAGE"
BACKEND_DIGEST=$(gcloud artifacts docker images describe "$BACKEND_IMAGE" --project="$PROJECT_ID" --format='value(image_summary.digest)')
if [[ ! "$BACKEND_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "The backend image digest could not be verified." >&2
  exit 1
fi
BACKEND_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$ARTIFACT_REPOSITORY/backend@$BACKEND_DIGEST"

gcloud builds submit "$ROOT_DIR/frontend" --project="$PROJECT_ID" --region="$REGION" --tag="$FRONTEND_IMAGE"
FRONTEND_DIGEST=$(gcloud artifacts docker images describe "$FRONTEND_IMAGE" --project="$PROJECT_ID" --format='value(image_summary.digest)')
if [[ ! "$FRONTEND_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "The frontend image digest could not be verified." >&2
  exit 1
fi
FRONTEND_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$ARTIFACT_REPOSITORY/frontend@$FRONTEND_DIGEST"

gcloud run deploy "$API_SERVICE" \
  --image="$BACKEND_IMAGE" --region="$REGION" --no-allow-unauthenticated \
  --min-instances=0 --max-instances=3 --concurrency=10 --cpu=1 --memory=1Gi --timeout=300 \
  --service-account="$API_RUNTIME_EMAIL" --env-vars-file="$API_ENV_FILE" \
  --set-secrets="AI_API_KEY=$MODEL_SECRET_NAME:$MODEL_SECRET_VERSION,P10_NEON_RUNTIME_DSN=$NEON_RUNTIME_DSN_SECRET_NAME:$NEON_RUNTIME_DSN_SECRET_VERSION"
API_URL=$(gcloud run services describe "$API_SERVICE" --region="$REGION" --format='value(status.url)')

gcloud run services add-iam-policy-binding "$API_SERVICE" --region="$REGION" \
  --member="serviceAccount:$WEB_RUNTIME_EMAIL" --role='roles/run.invoker' >/dev/null

gcloud run deploy "$WORKER_SERVICE" \
  --image="$BACKEND_IMAGE" --region="$REGION" --no-allow-unauthenticated \
  --min-instances=0 --max-instances=1 --concurrency=1 --cpu=1 --memory=1Gi --timeout=60 \
  --service-account="$WORKER_RUNTIME_EMAIL" --command=uvicorn \
  --args="personal_ai.worker:app,--host=0.0.0.0,--port=8080" --env-vars-file="$WORKER_ENV_FILE" \
  --set-secrets="AI_API_KEY=$MODEL_SECRET_NAME:$MODEL_SECRET_VERSION,P10_NEON_RUNTIME_DSN=$NEON_RUNTIME_DSN_SECRET_NAME:$NEON_RUNTIME_DSN_SECRET_VERSION"
WORKER_URL=$(gcloud run services describe "$WORKER_SERVICE" --region="$REGION" --format='value(status.url)')
gcloud run services update "$WORKER_SERVICE" --region="$REGION" \
  --update-env-vars="WORKER_PUSH_AUTH_REQUIRED=true,WORKER_PUSH_AUDIENCE=$WORKER_URL,WORKER_PUSH_SERVICE_ACCOUNT=$WORKER_INVOKER_EMAIL,WORKER_MAINTENANCE_AUTH_REQUIRED=true,WORKER_MAINTENANCE_AUDIENCE=$WORKER_URL,WORKER_MAINTENANCE_SERVICE_ACCOUNT=$MAINTENANCE_INVOKER_EMAIL"
gcloud run services add-iam-policy-binding "$WORKER_SERVICE" --region="$REGION" \
  --member="serviceAccount:$WORKER_INVOKER_EMAIL" --role='roles/run.invoker' >/dev/null
gcloud run services add-iam-policy-binding "$WORKER_SERVICE" --region="$REGION" \
  --member="serviceAccount:$MAINTENANCE_INVOKER_EMAIL" --role='roles/run.invoker' >/dev/null
gcloud iam service-accounts add-iam-policy-binding "$WORKER_INVOKER_EMAIL" \
  --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role='roles/iam.serviceAccountTokenCreator' >/dev/null

if gcloud pubsub subscriptions describe "$WORKER_SERVICE" >/dev/null 2>&1; then
  gcloud pubsub subscriptions update "$WORKER_SERVICE" --push-endpoint="$WORKER_URL/tasks/memory" \
    --push-auth-service-account="$WORKER_INVOKER_EMAIL" --push-auth-token-audience="$WORKER_URL"
else
  gcloud pubsub subscriptions create "$WORKER_SERVICE" --topic="$TOPIC" \
    --push-endpoint="$WORKER_URL/tasks/memory" --push-auth-service-account="$WORKER_INVOKER_EMAIL" \
    --push-auth-token-audience="$WORKER_URL"
fi

MAINTENANCE_JOB=personal-ai-maintenance
if gcloud scheduler jobs describe "$MAINTENANCE_JOB" --location="$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$MAINTENANCE_JOB" --location="$REGION" \
    --schedule='*/15 * * * *' --time-zone='Etc/UTC' --uri="$WORKER_URL/tasks/maintenance" \
    --http-method=POST --oidc-service-account="$MAINTENANCE_INVOKER_EMAIL" \
    --oidc-token-audience="$WORKER_URL" --attempt-deadline=60s
else
  gcloud scheduler jobs create http "$MAINTENANCE_JOB" --location="$REGION" \
    --schedule='*/15 * * * *' --time-zone='Etc/UTC' --uri="$WORKER_URL/tasks/maintenance" \
    --http-method=POST --oidc-service-account="$MAINTENANCE_INVOKER_EMAIL" \
    --oidc-token-audience="$WORKER_URL" --attempt-deadline=60s
fi
gcloud scheduler jobs pause "$MAINTENANCE_JOB" --location="$REGION"

cat >"$WEB_ENV_FILE" <<EOF
API_BASE_URL: $API_URL
API_IAM_AUTH_ENABLED: "true"
AUTH_MODE: google_oidc
GOOGLE_OAUTH_CLIENT_ID: $GOOGLE_OAUTH_CLIENT_ID
EXPORT_ENABLED: "$EXPORT_ENABLED"
DELETION_ENABLED: "$DELETION_ENABLED"
EOF
gcloud run deploy "$WEB_SERVICE" \
  --image="$FRONTEND_IMAGE" --region="$REGION" --allow-unauthenticated \
  --min-instances=0 --max-instances=3 --concurrency=20 --cpu=1 --memory=1Gi --timeout=300 \
  --service-account="$WEB_RUNTIME_EMAIL" --env-vars-file="$WEB_ENV_FILE"

WEB_URL=$(gcloud run services describe "$WEB_SERVICE" --region="$REGION" --format='value(status.url)')
echo "Deployment complete for $TARGET_ENV: $WEB_URL"
echo "Reviewed source revision: $GIT_REVISION; image tag: $BUILD_TAG; secret version: $MODEL_SECRET_VERSION"
echo "Verify authenticated API connectivity: $WEB_URL/api/health"
echo "API is private to the web runtime service account; worker push uses a dedicated Pub/Sub invoker."
