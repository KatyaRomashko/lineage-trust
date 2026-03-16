#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="lineage"
NAMESPACE="lineage"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${SCRIPT_DIR}")"
PLATFORM="linux/$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')"

GREEN='\033[0;32m'
NC='\033[0m'
info() { echo -e "${GREEN}[INFO]${NC}  $*"; }

if command -v podman &>/dev/null; then
  CONTAINER_RT="podman"
  export KIND_EXPERIMENTAL_PROVIDER=podman
elif command -v docker &>/dev/null; then
  CONTAINER_RT="docker"
else
  echo "ERROR: Neither podman nor docker found." >&2; exit 1
fi

COMPONENT="${1:-both}"

API_IMG="docker.io/library/dataset-registry-api:local"
UI_IMG="docker.io/library/dataset-registry-ui:local"

case "$COMPONENT" in
  api|backend)
    info "Building dataset-registry-api (${PLATFORM})..."
    ${CONTAINER_RT} build --platform "${PLATFORM}" -t "${API_IMG}" "${REPO_ROOT}/dataset-registry/backend"
    kind load docker-image "${API_IMG}" --name "${CLUSTER_NAME}"
    kubectl rollout restart deployment/dataset-registry-api -n "${NAMESPACE}"
    kubectl rollout status deployment/dataset-registry-api -n "${NAMESPACE}" --timeout=120s
    ;;
  ui|frontend)
    info "Building dataset-registry-ui (${PLATFORM})..."
    ${CONTAINER_RT} build --platform "${PLATFORM}" -t "${UI_IMG}" "${REPO_ROOT}/dataset-registry/frontend"
    kind load docker-image "${UI_IMG}" --name "${CLUSTER_NAME}"
    kubectl rollout restart deployment/dataset-registry-ui -n "${NAMESPACE}"
    kubectl rollout status deployment/dataset-registry-ui -n "${NAMESPACE}" --timeout=120s
    ;;
  both|all)
    info "Building dataset-registry-api (${PLATFORM})..."
    ${CONTAINER_RT} build --platform "${PLATFORM}" -t "${API_IMG}" "${REPO_ROOT}/dataset-registry/backend"
    info "Building dataset-registry-ui (${PLATFORM})..."
    ${CONTAINER_RT} build --platform "${PLATFORM}" -t "${UI_IMG}" "${REPO_ROOT}/dataset-registry/frontend"
    info "Loading images into Kind..."
    kind load docker-image "${API_IMG}" --name "${CLUSTER_NAME}"
    kind load docker-image "${UI_IMG}" --name "${CLUSTER_NAME}"
    kubectl rollout restart deployment/dataset-registry-api deployment/dataset-registry-ui -n "${NAMESPACE}"
    kubectl rollout status deployment/dataset-registry-api -n "${NAMESPACE}" --timeout=120s
    kubectl rollout status deployment/dataset-registry-ui -n "${NAMESPACE}" --timeout=120s
    ;;
  *)
    echo "Usage: $0 [api|ui|both]"
    exit 1
    ;;
esac

info "Done. Registry rebuilt and redeployed."
