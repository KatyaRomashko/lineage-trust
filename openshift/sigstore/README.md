# Sigstore / Cosign on OpenShift

## Image signing

`openshift/deploy.sh` signs `fkm-app:latest` and `spark-etl:latest` when `COSIGN_KEY` is set and `cosign` is installed. Export `COSIGN_PASSWORD` if the key is encrypted.

```bash
export COSIGN_KEY=$HOME/cosign.key
oc registry login $(oc get route default-route -n openshift-image-registry -o jsonpath='{.spec.host}')
./openshift/deploy.sh infra
```

## Admission policy

`clusterimagepolicy-fkm.yaml` is an **example** `ClusterImagePolicy` for OpenShift. API versions differ by minor release — validate with:

```bash
oc api-resources | grep -i imagepolicy
oc explain clusterimagepolicy
```

Tune `matchLabels` to the `fkm` namespace and your Cosign public key or Fulcio trust.

## Agent cards

Pipeline job `05-ml-pipeline` can set `AGENT_CARD_PUBLISH=1` in `fkm-config` to write `/tmp/agent-card.json` and optionally `cosign sign-blob` output. Store bundles in a ConfigMap and reference them from Gatekeeper constraints in `policies/gatekeeper/`.
