#!/usr/bin/env bash
# Validate trust controls on a connected OpenShift cluster (best-effort; skips missing CRDs).
set -euo pipefail
NAMESPACE="${NAMESPACE:-fkm}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FAILURES=0
add_fail() { echo "[FAIL] $1"; FAILURES=$((FAILURES + 1)); }
pass() { echo "[OK]   $1"; }

command -v oc &>/dev/null || { echo "oc not found"; exit 2; }
oc whoami &>/dev/null || { echo "not logged in to cluster"; exit 2; }

echo "=== Namespace region ==="
R=$(oc get namespace "$NAMESPACE" -o jsonpath='{.metadata.labels.region}' 2>/dev/null || true)
if [[ "$R" == "us" || "$R" == "eu" ]]; then
  pass "namespace $NAMESPACE region=$R"
else
  add_fail "namespace $NAMESPACE missing region=us|eu (got '$R')"
fi

echo "=== SPIFFE CSI volume on inference-api (spec present) ==="
if oc get deploy inference-api -n "$NAMESPACE" -o yaml 2>/dev/null | grep -q 'csi.spiffe.io'; then
  pass "inference-api references SPIFFE CSI driver"
else
  add_fail "inference-api missing csi.spiffe.io volume"
fi

echo "=== fkm-config trust keys ==="
if oc get configmap fkm-config -n "$NAMESPACE" -o yaml 2>/dev/null | grep -q SPIFFE_TRUST_DOMAIN; then
  pass "fkm-config contains SPIFFE_TRUST_DOMAIN"
else
  add_fail "fkm-config missing SPIFFE_TRUST_DOMAIN"
fi

echo "=== Running pods (SVID check is manual: exec + pyspiffe) ==="
oc get pods -n "$NAMESPACE" -o wide || true

echo "=== Gatekeeper ==="
if oc get crd constrainttemplates.templates.gatekeeper.sh &>/dev/null; then
  oc get constrainttemplate 2>/dev/null | grep -i fkm && pass "Gatekeeper templates present" || echo "[INFO] No fkm-named ConstraintTemplates applied"
else
  echo "[INFO] Gatekeeper CRD not installed — skip"
fi

echo "=== ClusterImagePolicy ==="
if oc get clusterimagepolicy 2>/dev/null | grep -q .; then
  pass "ClusterImagePolicy CR exists"
else
  echo "[INFO] ClusterImagePolicy not available — skip"
fi

echo "=== RHACM Placement (hub) ==="
if oc get placement.cluster.open-cluster-management.io 2>/dev/null | grep -q fkm; then
  pass "RHACM Placement resources found"
else
  echo "[INFO] RHACM Placement not found on this cluster — skip"
fi

echo "=== Cosign / signatures (optional) ==="
if command -v cosign &>/dev/null && [[ -n "${COSIGN_PUB:-}" ]]; then
  pass "cosign available for verify (set COSIGN_PUB for automated verify)"
else
  echo "[INFO] cosign or COSIGN_PUB not set — skip image verify"
fi

echo "=== PROV / OpenLineage spot check ==="
if [[ -f "${SCRIPT_DIR}/../src/prov_translator.py" ]]; then
  pass "prov_translator module present"
fi

echo "=== Summary ==="
if (( FAILURES > 0 )); then
  echo "$FAILURES check(s) failed"
  exit 1
fi
echo "All executed checks passed"
