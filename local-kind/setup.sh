#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="lineage"
NAMESPACE="lineage"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${SCRIPT_DIR}")"
PLATFORM="linux/$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Detect container runtime ──────────────────────────────────────────
detect_runtime() {
  if command -v podman &>/dev/null; then
    CONTAINER_RT="podman"
    export KIND_EXPERIMENTAL_PROVIDER=podman
  elif command -v docker &>/dev/null; then
    CONTAINER_RT="docker"
  else
    error "Neither podman nor docker found.\n  brew install podman  (or install Docker Desktop)"
  fi
  info "Container runtime: ${CONTAINER_RT} (platform: ${PLATFORM})"
}

# ── Prerequisites ─────────────────────────────────────────────────────
check_prereqs() {
  detect_runtime

  local missing=()
  for cmd in kind kubectl; do
    if ! command -v "$cmd" &>/dev/null; then
      missing+=("$cmd")
    fi
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    error "Missing required tools: ${missing[*]}\n  brew install kind kubectl"
  fi

  if [[ "${CONTAINER_RT}" == "podman" ]]; then
    if ! podman machine info &>/dev/null 2>&1; then
      error "Podman machine is not running. Start it with: podman machine start"
    fi
  else
    if ! docker info &>/dev/null; then
      error "Docker daemon is not running. Start Docker Desktop first."
    fi
  fi
  info "Prerequisites OK (${CONTAINER_RT}, kind, kubectl)"
}

# ── Cluster ───────────────────────────────────────────────────────────
create_cluster() {
  if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    info "Kind cluster '${CLUSTER_NAME}' already exists, reusing it"
  else
    info "Creating Kind cluster '${CLUSTER_NAME}'..."
    kind create cluster --name "${CLUSTER_NAME}" --wait 60s
  fi
  kubectl cluster-info --context "kind-${CLUSTER_NAME}" >/dev/null 2>&1 \
    || error "Cannot connect to cluster"
  info "Cluster ready"
}

# ── Namespace ─────────────────────────────────────────────────────────
create_namespace() {
  if kubectl get namespace "${NAMESPACE}" &>/dev/null; then
    info "Namespace '${NAMESPACE}' exists"
  else
    kubectl create namespace "${NAMESPACE}"
    info "Created namespace '${NAMESPACE}'"
  fi
}

# ── Wait helper ───────────────────────────────────────────────────────
wait_for_deployment() {
  local deploy=$1
  local timeout=${2:-180}
  info "Waiting for deployment/${deploy} (timeout ${timeout}s)..."
  kubectl rollout status "deployment/${deploy}" -n "${NAMESPACE}" --timeout="${timeout}s"
}

# ── Deploy Marquez ────────────────────────────────────────────────────
deploy_marquez() {
  info "Deploying Marquez stack..."
  kubectl apply -f "${SCRIPT_DIR}/marquez.yaml"

  wait_for_deployment "marquez-db" 120
  sleep 5
  wait_for_deployment "marquez" 180
  wait_for_deployment "marquez-web" 120
  info "Marquez stack deployed"
}

# ── Deploy MLflow ─────────────────────────────────────────────────────
deploy_mlflow() {
  info "Deploying MLflow stack..."
  kubectl apply -f "${SCRIPT_DIR}/mlflow.yaml"

  wait_for_deployment "mlflow-db" 120
  wait_for_deployment "mlflow-minio" 120

  info "Waiting for MinIO bucket creation job..."
  kubectl wait job/minio-create-buckets -n "${NAMESPACE}" \
    --for=condition=complete --timeout=120s 2>/dev/null || true

  wait_for_deployment "mlflow-server" 240
  info "MLflow stack deployed"
}

# ── Seed sample data into MinIO ──────────────────────────────────────
seed_data() {
  local csv="${REPO_ROOT}/dataset-registry/customers.csv"
  if [[ ! -f "${csv}" ]]; then
    warn "customers.csv not found at ${csv}, skipping seed"
    return
  fi

  info "Seeding customers.csv into MinIO (s3://raw-data/)..."

  kubectl create configmap seed-customers-csv \
    --from-file=customers.csv="${csv}" \
    -n "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

  kubectl delete job seed-raw-data -n "${NAMESPACE}" --ignore-not-found 2>/dev/null
  kubectl apply -f "${SCRIPT_DIR}/seed-data.yaml"

  info "Waiting for seed job..."
  kubectl wait job/seed-raw-data -n "${NAMESPACE}" \
    --for=condition=complete --timeout=120s 2>/dev/null || warn "Seed job did not complete in time"

  info "Sample data seeded"
}

# ── Build & Deploy Dataset Registry ──────────────────────────────────
deploy_registry() {
  local api_img="docker.io/library/dataset-registry-api:local"
  local ui_img="docker.io/library/dataset-registry-ui:local"

  info "Building dataset-registry-api image (${PLATFORM})..."
  ${CONTAINER_RT} build --platform "${PLATFORM}" -t "${api_img}" \
    "${REPO_ROOT}/dataset-registry/backend"

  info "Building dataset-registry-ui image (${PLATFORM})..."
  ${CONTAINER_RT} build --platform "${PLATFORM}" -t "${ui_img}" \
    "${REPO_ROOT}/dataset-registry/frontend"

  info "Loading images into Kind cluster..."
  kind load docker-image "${api_img}" --name "${CLUSTER_NAME}"
  kind load docker-image "${ui_img}" --name "${CLUSTER_NAME}"

  info "Deploying dataset registry..."
  kubectl apply -f "${SCRIPT_DIR}/registry.yaml"

  wait_for_deployment "registry-db" 120
  sleep 3
  wait_for_deployment "dataset-registry-api" 120
  wait_for_deployment "dataset-registry-ui" 120
  info "Dataset Registry deployed"
}

# ── Port-forward helper (background) ─────────────────────────────────
start_port_forwards() {
  info "Starting port-forwards (background)..."

  pkill -f "kubectl port-forward.*-n ${NAMESPACE}" 2>/dev/null || true
  sleep 1

  kubectl port-forward -n "${NAMESPACE}" svc/marquez          5000:80   &>/dev/null &
  kubectl port-forward -n "${NAMESPACE}" svc/marquez-web      3000:80   &>/dev/null &
  kubectl port-forward -n "${NAMESPACE}" svc/mlflow-server    5001:5000 &>/dev/null &
  kubectl port-forward -n "${NAMESPACE}" svc/mlflow-minio     9000:9000 9001:9001 &>/dev/null &
  kubectl port-forward -n "${NAMESPACE}" svc/dataset-registry-api 8080:8080 &>/dev/null &
  kubectl port-forward -n "${NAMESPACE}" svc/dataset-registry-ui  8081:8080 &>/dev/null &

  sleep 2
}

# ── Summary ───────────────────────────────────────────────────────────
print_summary() {
  echo ""
  echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
  echo -e "${GREEN}  Local Lineage Cluster Ready${NC}"
  echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
  echo ""
  echo "  Marquez API:        http://localhost:5000/api/v1/namespaces"
  echo "  Marquez Web:        http://localhost:3000"
  echo "  MLflow:             http://localhost:5001"
  echo "  MinIO Console:      http://localhost:9001  (minioadmin / minioadmin123)"
  echo "  MinIO API:          http://localhost:9000"
  echo "  Registry API:       http://localhost:8080/docs"
  echo "  Registry UI:        http://localhost:8081"
  echo ""
  echo "  Namespace:          ${NAMESPACE}"
  echo "  Cluster:            kind-${CLUSTER_NAME}"
  echo ""
  echo "  Stop port-forwards:   pkill -f 'kubectl port-forward.*-n ${NAMESPACE}'"
  echo "  Rebuild registry:     ${SCRIPT_DIR}/rebuild-registry.sh"
  echo "  Tear down cluster:    ${SCRIPT_DIR}/teardown.sh"
  echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
}

# ── Main ──────────────────────────────────────────────────────────────
main() {
  check_prereqs
  create_cluster
  create_namespace
  deploy_marquez
  deploy_mlflow
  seed_data
  deploy_registry
  start_port_forwards
  print_summary
}

main "$@"
