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

# Judging runs for a month against this URL, so the first request a judge
# makes should not be a cold start. A warm min-instance is billed at Cloud
# Run's idle rate because CPU is throttled between requests -- do NOT add
# --no-cpu-throttling, which bills the idle instance at the full active rate.
MIN_INSTANCES="${MIN_INSTANCES:-1}"

echo "============================================================"
echo "  Deploying ${SERVICE_NAME}"
echo "  Project:   ${PROJECT_ID}"
echo "  Region:    ${REGION}  (always-free tier)"
echo "  Scaling:   min ${MIN_INSTANCES} (warm), max 1"
echo "  Timeout:   ${TIMEOUT}"
echo "============================================================"

SERVICE_URL="https://${SERVICE_NAME}-18489510475.${REGION}.run.app"

# --max-instances 1 is a correctness constraint, not a cost setting.
# AuditLedger chains each entry to the previous through process-local state
# (_latest_hash / _sequence). A second container starts from its own
# recovered head, and two containers appending concurrently fork the chain,
# which verify_integrity() would only surface long after the run that broke
# it. Raising this needs the chain head moved into a Firestore transaction
# first. The in-process race is already closed by a lock; see
# app/storage/audit_ledger.py.
#
# The env-var delimiter below is ##, not @: PUBSUB_PUSH_SERVICE_ACCOUNT is
# an email address, so an @ delimiter would split it mid-value. Commas are
# already taken by the model chains.
gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --project "${PROJECT_ID}" \
  --platform managed \
  --region "${REGION}" \
  --allow-unauthenticated \
  --min-instances "${MIN_INSTANCES}" \
  --max-instances 1 \
  --memory 1Gi \
  --cpu 1 \
  --timeout "${TIMEOUT}" \
  --set-secrets "GEMINI_API_KEY=syntrueno-gemini-api-key:latest,A2A_AUTH_SECRET=syntrueno-a2a-secret:latest" \
  --set-env-vars "^##^ENVIRONMENT=production\
##SIMULATION_MODE=false\
##GOOGLE_CLOUD_PROJECT=${PROJECT_ID}\
##GOOGLE_CLOUD_LOCATION=${REGION}\
##FIRESTORE_ENABLED=true\
##FIRESTORE_DATABASE=(default)\
##USE_VERTEX_AI=true\
##VERTEX_LOCATION=global\
##USE_REAL_MODEL_ARMOR=true\
##MODEL_ARMOR_ENABLED=true\
##MODEL_ARMOR_TEMPLATE_ID=syntrueno-enterprise-standard\
##MODEL_ARMOR_LOCATION=${REGION}\
##MODEL_ARMOR_TIMEOUT_SECONDS=8.0\
##USE_GEMMA_SCREEN=true\
##GEMMA_MODEL=gemma-4-26b-a4b-it\
##GEMMA_TIMEOUT_SECONDS=3.0\
##VERTEX_MEMORY_ENABLED=true\
##AGENT_ENGINE_LOCATION=us-central1\
##AGENT_ENGINE_ID=3217687243581816832\
##VERTEX_MEMORY_TIMEOUT_SECONDS=4.0\
##TRACING_ENABLED=true\
##FAST_MODEL=gemini-3.5-flash\
##REASONING_MODEL=gemini-3.6-flash\
##REASONING_MODEL_CHAIN=gemini-3.6-flash,gemini-3.7-flash,gemini-3.5-flash\
##FAST_MODEL_CHAIN=gemini-3.5-flash,gemini-3.7-flash\
##LLM_TIMEOUT_SECONDS=45\
##LLM_MAX_RETRIES=3\
##PUBSUB_INGEST_ENABLED=true\
##PUBSUB_PUSH_SERVICE_ACCOUNT=syntrueno-pubsub-push@${PROJECT_ID}.iam.gserviceaccount.com\
##PUBSUB_AUDIENCE=${SERVICE_URL}/api/v1/ingest/pubsub\
##CANARY_SERVICE_NAME=syntrueno-canary\
##REMEDIATION_DRY_RUN=false\
##CORS_ALLOWED_ORIGINS=${SERVICE_URL},http://localhost:5173"

echo ""
echo "Deployed. Verifying..."

# gcloud exits 0 even when the revision it just built never takes traffic, and
# then truthfully reports that the OLD revision is serving 100 percent. That is
# not hypothetical: this service had spec.traffic pinned to a revision by name,
# so for three days every deploy uploaded the right source, built the right
# image, created a revision, had it retired unserved, and printed success. The
# live site stayed three days stale behind a green deploy, and nothing in the
# output said so. Compare what was built against what is actually serving.
LATEST_CREATED=$(gcloud run services describe "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" --region "${REGION}" \
  --format 'value(status.latestCreatedRevisionName)')
SERVING=$(gcloud run services describe "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" --region "${REGION}" \
  --format 'value(status.traffic[0].revisionName)')

if [ -n "${SERVING}" ] && [ "${LATEST_CREATED}" != "${SERVING}" ]; then
  echo ""
  echo "  DEPLOY DID NOT GO LIVE"
  echo "    built:   ${LATEST_CREATED}"
  echo "    serving: ${SERVING}"
  echo ""
  echo "  Traffic is not following the latest revision, which usually means"
  echo "  spec.traffic is pinned to one revision by name. Unpin it with:"
  echo ""
  echo "    gcloud run services update-traffic ${SERVICE_NAME} \\"
  echo "      --project ${PROJECT_ID} --region ${REGION} --to-latest"
  echo ""
  exit 1
fi
echo "  Serving:    ${LATEST_CREATED}  (the revision just built)"

URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" --region "${REGION}" --format 'value(status.url)')

echo "  Service:    ${URL}"
echo "  Health:     ${URL}/api/v1/health"
echo "  Agent card: ${URL}/.well-known/agent-card.json"
echo "  API docs:   ${URL}/docs"
echo ""
curl -s --max-time 60 "${URL}/api/v1/health" && echo ""
