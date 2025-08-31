#!/bin/bash

# This script tails the logs of the Cloud Run service.

# --- Configuration ---
# Replace with your Google Cloud Project ID
PROJECT_ID=$(gcloud config get project)
REGION="asia-northeast3"
# Name of your Cloud Run service (must match the one in deploy.sh)
SERVICE_NAME="image-voting-app"

echo "Tailing logs for Cloud Run service: ${SERVICE_NAME} in project ${PROJECT_ID}"
echo "Press Ctrl+C to stop tailing logs."

gcloud run services logs read "${SERVICE_NAME}" \
    --project "${PROJECT_ID}" \
    --region "${REGION}" \
    --format="default"

if [ $? -ne 0 ]; then
    echo "Failed to tail logs. Ensure the service name and project ID are correct and you have permissions."
    exit 1
fi
