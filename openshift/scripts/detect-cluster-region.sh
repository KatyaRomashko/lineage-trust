#!/usr/bin/env bash
# Detect coarse region (us | eu) from worker node topology labels.
# OpenShift / cloud providers set topology.kubernetes.io/region on compute nodes.
# Export FKM_REGION for sourcing:  source openshift/scripts/detect-cluster-region.sh
set -euo pipefail

detect_region() {
    local regions
    regions="$(oc get nodes -o jsonpath='{range .items[*]}{.metadata.labels.topology\.kubernetes\.io/region}{"\n"}{end}' 2>/dev/null | sed '/^$/d' || true)"
    if [[ -z "$regions" ]]; then
        echo "warn: no topology.kubernetes.io/region on nodes; defaulting FKM_REGION=us" >&2
        echo "us"
        return 0
    fi
    # Majority of node regions → map to policy bucket us | eu
    local eu_count=0 total=0
    while IFS= read -r r; do
        [[ -z "$r" ]] && continue
        total=$((total + 1))
        rl="${r,,}"
        if [[ "$rl" == *"europe"* ]] || [[ "$rl" == *"eu-"* ]] || [[ "$rl" == *"eu_"* ]] \
            || [[ "$rl" == *"euw"* ]] || [[ "$rl" == *"eun"* ]] || [[ "$rl" == *"euc"* ]] \
            || [[ "$rl" == *"westeurope"* ]] || [[ "$rl" == *"northeurope"* ]]; then
            eu_count=$((eu_count + 1))
        fi
    done <<< "$regions"

    if (( eu_count * 2 > total )); then
        echo "eu"
    else
        echo "us"
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    detect_region
else
    FKM_REGION="$(detect_region)"
    export FKM_REGION
fi
