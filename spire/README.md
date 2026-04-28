# SPIRE / SPIFFE on OpenShift

This directory holds **reference manifests** and scripts for workload identity. Production installs should follow your platform version of the **Red Hat Zero Trust Workload Identity Manager** (Technology Preview) or the upstream SPIRE Helm charts, then align these snippets with the operator-managed CRDs.

## Install order

1. Install the SPIFFE CSI driver and SPIRE Server / Agent via the operator (or community SPIRE bundle for non-production labs).
2. Create a trust domain (example: `spiffe://fkm.cluster.local`) and federation keys per environment.
3. Apply `spire/spiffe-csi-driver.yaml` only if the operator does not already register the `CSIDriver` named `csi.spiffe.io`.
4. Run `spire/scripts/register-workloads.sh` after the first `fkm-app` image is available and service accounts exist.

## Files

| File | Purpose |
|------|---------|
| `operator-subscription-spire.yaml` | Example `Subscription` to community SPIRE (adjust channel/source for your catalog). |
| `spire-server.yaml` | Reference `ConfigMap` + `StatefulSet` fragments — **merge** with operator output; do not double-apply servers. |
| `spire-agent.yaml` | Reference `DaemonSet` fragment for bare SPIRE (operator preferred on OCP). |
| `spiffe-csi-driver.yaml` | `CSIDriver` registration for `csi.spiffe.io`. |

## Red Hat documentation

- [Red Hat Zero Trust Workload Identity Manager](https://docs.openshift.com/) — search from your OCP version docs index.
- [RHACM placement labels](https://access.redhat.com/documentation/en-us/red_hat_advanced_cluster_management_for_kubernetes/) for `region=us` / `region=eu` on managed clusters.
