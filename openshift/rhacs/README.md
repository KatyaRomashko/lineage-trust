# RHACS — runtime security and compliance

## Hub integration

Connect each OpenShift cluster’s RHACS Secured Cluster Services to the central RHACS stack from the RHACS UI (Integrations → Cluster init bundles). RHACM cluster inventory can list RHACS health when both are installed.

## Network controls

Use **NetworkPolicy** in `openshift/base/networkpolicy-fkm-egress.yaml` as a baseline, then validate denied east-west paths in RHACS **Network Graph** (especially cross-cluster routes when paired with multi-cluster service mesh).

## Custom compliance controls

Create **Compliance checks** in RHACS for:

- Pods in `fkm` mounting the SPIFFE CSI volume and exposing `SPIFFE_ENDPOINT_SOCKET`.
- Admission results from Gatekeeper (`kubectl get constrainttemplate`).
- Namespace labels `region` and `trust.fkm.io/region`.

## Runtime detections

Add **Runtime policies** alerting when processes read model artifacts without an expected SPIFFE ID (integrate with process baseline + network flows).
