#!/bin/bash
set -e

cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "[ERROR] File .env tidak ditemukan."
    echo "Silakan salin .env.example menjadi .env dan isi nilai-nilai yang dibutuhkan."
    exit 1
fi

echo "Building and deploying Singgah..."
docker compose up -d --build

echo ""
echo "Deploy berhasil."
echo "Backend : http://localhost:8000"
echo "Frontend: http://localhost:3000"
