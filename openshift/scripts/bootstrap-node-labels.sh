#!/usr/bin/env bash
# Verify topology.kubernetes.io/region and topology.kubernetes.io/zone on worker nodes.
# OCP cloud installs usually propagate these from AWS/GCP/Azure/vSphere tags.
# For bare-metal or missing labels, prints oc label commands for operators to run.
#
# Usage: ./openshift/scripts/bootstrap-node-labels.sh [--dry-run]
set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

missing=0
while IFS= read -r node; do
    [[ -z "$node" ]] && continue
    region="$(oc get node "$node" -o jsonpath='{.metadata.labels.topology\.kubernetes\.io/region}' 2>/dev/null || true)"
    zone="$(oc get node "$node" -o jsonpath='{.metadata.labels.topology\.kubernetes\.io/zone}' 2>/dev/null || true)"
    if [[ -z "$region" ]]; then
        echo "[WARN] $node: missing topology.kubernetes.io/region"
        missing=1
        provider="$(oc get node "$node" -o jsonpath='{.spec.providerID}' 2>/dev/null || true)"
        if [[ -n "$provider" ]]; then
            echo "       providerID=$provider — set region/zone from your cloud console tags, then:"
            echo "       oc label node \"$node\" topology.kubernetes.io/region=<REGION> --overwrite"
        fi
    else
        echo "[OK]   $node region=$region zone=${zone:-<unset>}"
    fi
done < <(oc get nodes -l 'node-role.kubernetes.io/worker=' -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)

# Fallback: any schedulable node without master role
if ! oc get nodes -l 'node-role.kubernetes.io/worker=' &>/dev/null; then
    while IFS= read -r node; do
        [[ -z "$node" ]] && continue
        if oc get node "$node" -o jsonpath='{.metadata.labels.node-role\.kubernetes\.io/master}' 2>/dev/null | grep -q .; then
            continue
        fi
        region="$(oc get node "$node" -o jsonpath='{.metadata.labels.topology\.kubernetes\.io/region}' 2>/dev/null || true)"
        if [[ -z "$region" ]]; then
            echo "[WARN] $node: missing topology.kubernetes.io/region"
            missing=1
        fi
    done < <(oc get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')
fi

if (( missing )); then
    echo "Some nodes lack topology labels. RHACM placement and region detection need them."
    echo "See: https://access.redhat.com/documentation/en-us/red_hat_advanced_cluster_management_for_kubernetes/"
    [[ "${1:-}" == "--strict" ]] || [[ "${2:-}" == "--strict" ]] && exit 1
fi
exit 0
