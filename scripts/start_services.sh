#!/usr/bin/env bash
#
# Start all infrastructure via Docker Compose, then wait until healthy.
#
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Starting services …"
docker compose up -d --build

echo ""
echo "Waiting for services to become healthy …"

wait_for() {
    local name=$1 url=$2 retries=${3:-30}
    for i in $(seq 1 "$retries"); do
        if curl -sf "$url" > /dev/null 2>&1; then
            echo "  ✓ $name is ready"
            return 0
        fi
        sleep 2
    done
    echo "  ✗ $name did NOT become ready" && return 1
}

wait_for "MinIO"    "http://localhost:9000/minio/health/live"
wait_for "MLflow"   "http://localhost:5000/health"

# PostgreSQL & Redis don't expose HTTP, check via docker
docker compose exec -T postgres pg_isready -U feast -d warehouse > /dev/null && echo "  ✓ PostgreSQL is ready"
docker compose exec -T redis redis-cli ping | grep -q PONG && echo "  ✓ Redis is ready"

echo ""
echo "All services up.  UIs:"
echo "  MinIO Console  → http://localhost:9001  (minioadmin / minioadmin)"
echo "  MLflow UI      → http://localhost:5000"
echo "  Inference API  → http://localhost:8000/docs"
