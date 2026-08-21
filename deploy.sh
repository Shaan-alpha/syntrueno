#!/usr/bin/env bash
# SentinelMesh (NexusFleet) - 1-Command Google Cloud Run Deployment
# Enforces $0.00 Cost with Scale-to-Zero

set -e

PROJECT_ID=$(gcloud config get-value project 2>/dev/null || echo "sentinel-mesh-hackathon")
SERVICE_NAME="sentinel-mesh-backend"
REGION="us-central1"

echo "============================================================"
echo "🚀 Deploying SentinelMesh to Google Cloud Run"
echo "Project:   ${PROJECT_ID}"
echo "Service:   ${SERVICE_NAME}"
echo "Region:    ${REGION} (Always Free Tier Region)"
echo "Instances: Min: 0 (Scale-to-Zero = \$0 Cost), Max: 1"
echo "============================================================"

# Build and Deploy to Cloud Run
gcloud run deploy ${SERVICE_NAME} \
  --source ./backend \
  --platform managed \
  --region ${REGION} \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 1 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 60s \
  --set-env-vars SIMULATION_MODE=true,MODEL_ARMOR_ENABLED=true

echo ""
echo "✅ Deployment Successful!"
echo "Service URL:"
gcloud run services describe ${SERVICE_NAME} --platform managed --region ${REGION} --format 'value(status.url)'
