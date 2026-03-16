#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="lineage"
NAMESPACE="lineage"

echo "Stopping port-forwards..."
pkill -f "kubectl port-forward.*-n ${NAMESPACE}" 2>/dev/null || true

echo "Deleting Kind cluster '${CLUSTER_NAME}'..."
kind delete cluster --name "${CLUSTER_NAME}"

echo "Done."
