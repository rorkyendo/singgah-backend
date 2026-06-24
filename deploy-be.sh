#!/bin/bash
set -e

# Load environment variables from .env if it exists.
if [ -f .env ]; then
    set -a
    # shellcheck source=/dev/null
    . .env
    set +a
fi

# Required variables.
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-root}"
DB_NAME="${DB_NAME:-singgah_chat}"
API_KEY="${API_KEY:-}"
LLM_MODEL="${LLM_MODEL:-openai/gpt-3.5-turbo}"
LLM_URL="${LLM_URL:-https://openrouter.ai/api/v1}"
CORS_ORIGINS="${CORS_ORIGINS:-*}"
PROJECT_NAME="${PROJECT_NAME:-Singgah SmartAdvisor}"

IMAGE_NAME="singgah-be-with-db"
CONTAINER_NAME="singgah_be"

if [ -z "$API_KEY" ]; then
    echo "WARNING: API_KEY is not set. The backend will not be able to use the LLM."
fi

echo "Building backend image (with embedded database)..."
docker build -t "${IMAGE_NAME}" -f Dockerfile.all-in-one .

echo "Stopping and removing existing container if any..."
docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true

echo "Starting backend container..."
docker run -d \
    --name "${CONTAINER_NAME}" \
    -p 8000:8000 \
    -e DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD}" \
    -e DB_NAME="${DB_NAME}" \
    -e API_KEY="${API_KEY}" \
    -e LLM_MODEL="${LLM_MODEL}" \
    -e LLM_URL="${LLM_URL}" \
    -e CORS_ORIGINS="${CORS_ORIGINS}" \
    -e PROJECT_NAME="${PROJECT_NAME}" \
    -v "singgah_db_data:/var/lib/mysql" \
    --restart unless-stopped \
    "${IMAGE_NAME}"

echo ""
echo "Backend is starting..."
echo "Check logs with: docker logs -f ${CONTAINER_NAME}"
echo "API will be available at: http://<server-ip>:8000"
