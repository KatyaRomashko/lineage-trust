#!/usr/bin/env bash
# Register SPIRE entries for FKM workloads (run with kubeconfig + spire-server admin socket/CLI).
# Adjust trust_domain and parent IDs for your environment.
set -euo pipefail
TRUST_DOMAIN="${SPIFFE_TRUST_DOMAIN:-spiffe://fkm.cluster.local}"
NS="${NAMESPACE:-fkm}"

spire_exec() {
  if oc exec -n spire-server deploy/spire-server -- "$@" 2>/dev/null; then
    return 0
  fi
  if oc exec -n spire statefulset/spire-server -- "$@" 2>/dev/null; then
    return 0
  fi
  echo "Could not exec into spire-server; run spire-server entry create manually." >&2
  return 1
}

register() {
  local spiffe_id=$1 selector=$2
  echo "Registering $spiffe_id ($selector)"
  spire_exec spire-server entry create \
    -parentID "spiffe://fkm.cluster.local/ns/${NS}/sa/default" \
    -spiffeID "$spiffe_id" \
    -selector "$selector" \
    -ttl 3600 || true
}

register "${TRUST_DOMAIN}/ns/${NS}/sa/default" "k8s:ns:${NS}"
register "${TRUST_DOMAIN}/ns/${NS}/job/etl" "k8s:ns:${NS},k8s:sa:default"
register "${TRUST_DOMAIN}/ns/${NS}/job/ml-pipeline" "k8s:ns:${NS},k8s:sa:default"
register "${TRUST_DOMAIN}/ns/${NS}/deployment/inference-api" "k8s:ns:${NS},k8s:sa:default"
echo "Done (best-effort; validate with: spire-server entry show)"
