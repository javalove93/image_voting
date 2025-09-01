#!/bin/bash

# This script builds the Docker image and deploys it to Google Cloud Run.

# --- Configuration ---
# Replace with your Google Cloud Project ID
PROJECT_ID=$(gcloud config get project)
# Replace with your desired Google Cloud region (e.g., us-central1, asia-east1)
REGION="asia-northeast3"
# Name of your Cloud Run service
SERVICE_NAME="image-voting-app"

# --- Artifact Registry Configuration ---
# Artifact Registry location (usually the same as your Cloud Run region)
ARTIFACT_REGISTRY_LOCATION="${REGION}"
# Artifact Registry repository name (e.g., 'my-docker-repo')
# You need to create this repository in Artifact Registry if it doesn't exist.
ARTIFACT_REGISTRY_REPOSITORY="jerry" # You can change this name

# Image name for Google Artifact Registry
IMAGE_NAME="${ARTIFACT_REGISTRY_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REGISTRY_REPOSITORY}/${SERVICE_NAME}"

# Image name for Google Artifact Registry
IMAGE_NAME="${ARTIFACT_REGISTRY_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REGISTRY_REPOSITORY}/${SERVICE_NAME}"
DOCKER_IMAGE_TAG="${IMAGE_NAME}:latest" # Using 'latest' tag for simplicity

# --- Build Docker Image Locally ---
echo "Building Docker image locally: ${DOCKER_IMAGE_TAG}"
cp ../sa-key-251130-exp.json sa-key-251130-exp.json
docker build -t "${DOCKER_IMAGE_TAG}" .
rm sa-key-251130-exp.json

if [ $? -ne 0 ]; then
    echo "Local Docker image build failed. Exiting."
    exit 1
fi

echo "Docker image built successfully."

# --- Push Docker Image to Artifact Registry ---
echo "Pushing Docker image to Artifact Registry: ${DOCKER_IMAGE_TAG}"
docker push "${DOCKER_IMAGE_TAG}"

if [ $? -ne 0 ]; then
    echo "Docker image push to Artifact Registry failed. Exiting."
    exit 1
fi

echo "Docker image pushed to Artifact Registry successfully!"

# --- Deploy to Cloud Run ---
echo "Deploying ${SERVICE_NAME} to Cloud Run in region ${REGION}"
gcloud run deploy "${SERVICE_NAME}" \
    --image "${DOCKER_IMAGE_TAG}" \
    --platform managed \
    --region "${REGION}" \
    --allow-unauthenticated \
    --memory 2Gi \
    --concurrency 5 \
    --project "${PROJECT_ID}"

if [ $? -ne 0 ]; then
    echo "Cloud Run deployment failed. Exiting."
    exit 1
fi

echo "Deployment to Cloud Run successful!"
echo "You can now access your service at the URL provided by Cloud Run."
