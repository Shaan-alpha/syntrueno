#!/usr/bin/env bash
# Syntrueno — Cloud Run deployment.
#
# Builds from the repository root so the multi-stage Dockerfile compiles the
# React frontend and serves it from the same container as the API. Deploying
# from ./backend instead would ship a headless service with no UI.
#
# Secrets are mounted from Secret Manager, never passed as plaintext env vars.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-composed-maxim-498517-f0}"
SERVICE_NAME="${SERVICE_NAME:-syntrueno}"
REGION="${REGION:-us-central1}"

# Real Gemini reasoning takes ~20-35s per incident (measured: SRE 20.3s,
# Judge 17.2s). A 60s request timeout would kill live calls mid-flight.
TIMEOUT="300s"

echo "============================================================"
echo "  Deploying ${SERVICE_NAME}"
echo "  Project:   ${PROJECT_ID}"
echo "  Region:    ${REGION}  (always-free tier)"
echo "  Scaling:   min 0 (scale-to-zero), max 1"
echo "  Timeout:   ${TIMEOUT}"
echo "============================================================"

SERVICE_URL="https://${SERVICE_NAME}-18489510475.${REGION}.run.app"

gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --project "${PROJECT_ID}" \
  --platform managed \
  --region "${REGION}" \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 1 \
  --memory 1Gi \
  --cpu 1 \
  --timeout "${TIMEOUT}" \
  --set-secrets "GEMINI_API_KEY=syntrueno-gemini-api-key:latest,A2A_AUTH_SECRET=syntrueno-a2a-secret:latest" \
  --set-env-vars "^@^ENVIRONMENT=production\
@SIMULATION_MODE=false\
@GOOGLE_CLOUD_PROJECT=${PROJECT_ID}\
@GOOGLE_CLOUD_PROJECT_NUMBER=18489510475\
@GOOGLE_CLOUD_LOCATION=${REGION}\
@FIRESTORE_ENABLED=true\
@FIRESTORE_DATABASE=(default)\
@FAST_MODEL=gemini-3.1-flash-lite\
@REASONING_MODEL=gemini-3.6-flash\
@REASONING_MODEL_CHAIN=gemini-3.6-flash,gemini-3.7-flash,gemini-3.5-flash,gemini-3.1-flash-lite\
@FAST_MODEL_CHAIN=gemini-3.1-flash-lite,gemini-3.5-flash\
@LLM_TIMEOUT_SECONDS=45\
@LLM_MAX_RETRIES=3\
@CANARY_SERVICE_NAME=syntrueno-canary\
@REMEDIATION_DRY_RUN=false\
@CORS_ALLOWED_ORIGINS=${SERVICE_URL},http://localhost:5173"

echo ""
echo "Deployed. Verifying..."
URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" --region "${REGION}" --format 'value(status.url)')

echo "  Service:    ${URL}"
echo "  Health:     ${URL}/api/v1/health"
echo "  Agent card: ${URL}/.well-known/agent-card.json"
echo "  API docs:   ${URL}/docs"
echo ""
curl -s --max-time 60 "${URL}/api/v1/health" && echo ""
