# RHACM — multi-cluster placement and policy

1. **Import clusters** into RHACM and label managed clusters:
   - US hub member: `oc label managedcluster/<name> region=us --overwrite`
   - EU hub member: `oc label managedcluster/<name> region=eu --overwrite`

2. Apply manifests in this directory on the **hub** (adjust namespaces to your GitOps or `open-cluster-management` policy namespace).

3. **PolicySets** wrap Gatekeeper `ConstraintTemplate` objects as `ConfigurationPolicy` manifests; use `Placement` + `PlacementBinding` so EU-only policies land only on `region=eu` clusters.

References: [Placement rules](https://access.redhat.com/documentation/en-us/red_hat_advanced_cluster_management_for_kubernetes/), [Governance policies](https://access.redhat.com/documentation/en-us/red_hat_advanced_cluster_management_for_kubernetes/2.10/html/security/index).
