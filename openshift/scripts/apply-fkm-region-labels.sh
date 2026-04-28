#!/usr/bin/env bash
# Label the fkm namespace and patch fkm-config with FKM_REGION / SPIFFE_TRUST_DOMAIN.
# Expects oc logged in. Optional: SPIFFE_TRUST_DOMAIN (default spiffe://fkm.cluster.local).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NAMESPACE="${NAMESPACE:-fkm}"
# shellcheck source=detect-cluster-region.sh
source "$SCRIPT_DIR/detect-cluster-region.sh"
TRUST_DOMAIN="${SPIFFE_TRUST_DOMAIN:-spiffe://fkm.cluster.local}"

echo "[INFO] Applying region=$FKM_REGION to namespace/$NAMESPACE and ConfigMap fkm-config"
oc label namespace "$NAMESPACE" "region=${FKM_REGION}" "trust.fkm.io/region=${FKM_REGION}" --overwrite
oc patch configmap fkm-config -n "$NAMESPACE" --type merge \
    -p "{\"data\":{\"FKM_REGION\":\"${FKM_REGION}\",\"SPIFFE_TRUST_DOMAIN\":\"${TRUST_DOMAIN}\"}}" 2>/dev/null \
    || echo "[WARN] fkm-config not found yet; apply base manifests first"
