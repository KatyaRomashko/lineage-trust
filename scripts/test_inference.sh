#!/usr/bin/env bash
#
# Smoke-test the FastAPI inference endpoint.
#
set -euo pipefail

echo "Testing /health …"
curl -s http://localhost:8000/health | python -m json.tool

echo ""
echo "Testing /predict …"
curl -s -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"entity_ids": [1, 2, 3, 10, 50]}' | python -m json.tool
