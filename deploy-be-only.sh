#!/bin/bash
set -e

cd "$(dirname "$0")"

# Load environment variables from .env if it exists.
if [ -f .env ]; then
    set -a
    # shellcheck source=/dev/null
    . .env
    set +a
fi

# Required variables for external database.
if [ -z "$DATABASE_URL" ]; then
    echo "[ERROR] DATABASE_URL is not set."
    echo ""
    echo "Buat file .env di folder ini dengan contoh isi:"
    echo ""
    echo "DATABASE_URL=mysql+pymysql://singgah_admin:singgah2026@103.52.212.190:3306/singgah_admin"
    echo "API_KEY=sk-or-v1-..."
    echo "LLM_MODEL=openai/gpt-3.5-turbo"
    echo "LLM_URL=https://openrouter.ai/api/v1"
    echo "CORS_ORIGINS=https://predev.my.id,https://www.predev.my.id"
    echo "PROJECT_NAME=Singgah SmartAdvisor"
    echo ""
    exit 1
fi

if [ -z "$API_KEY" ]; then
    echo "[WARNING] API_KEY is not set. Backend akan error saat memanggil LLM."
fi

IMAGE_NAME="singgah-backend"
CONTAINER_NAME="singgah_backend"

echo "Building backend image..."
docker build -t "${IMAGE_NAME}" .

echo "Stopping and removing existing container if any..."
docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true

echo "Starting backend container..."
docker run -d \
    --name "${CONTAINER_NAME}" \
    -p 8000:8000 \
    -e DATABASE_URL="${DATABASE_URL}" \
    -e API_KEY="${API_KEY}" \
    -e LLM_MODEL="${LLM_MODEL:-openai/gpt-3.5-turbo}" \
    -e LLM_URL="${LLM_URL:-https://openrouter.ai/api/v1}" \
    -e CORS_ORIGINS="${CORS_ORIGINS:-*}" \
    -e PROJECT_NAME="${PROJECT_NAME:-Singgah SmartAdvisor}" \
    --restart unless-stopped \
    "${IMAGE_NAME}"

echo ""
echo "Backend is starting..."
echo "Check logs: docker logs -f ${CONTAINER_NAME}"
echo "API: http://<server-ip>:8000"
