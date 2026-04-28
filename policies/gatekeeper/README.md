# OPA Gatekeeper policies (region-aware)

Install the **Gatekeeper** operator for OpenShift, enable the config sync for namespaces (`sync.config.gatekeeper.sh`) so Rego can read `data.inventory.namespace[...]`.

```bash
oc apply -f https://raw.githubusercontent.com/open-policy-agent/gatekeeper/master/deploy/gatekeeper.yaml
# Or use the Gatekeeper operator from OperatorHub; then apply templates from this directory.
```

## Templates

| File | Intent |
|------|--------|
| `constraint-template-namespace-region.yaml` | Requires `metadata.labels.region` on namespaces labelled `app.kubernetes.io/part-of=feast-kfp-mlflow`. |
| `constraint-template-agent-card.yaml` | Requires pods to reference a signed Agent Card (`agent-card.fkm.io` annotations); extend with Sigstore external data for full signature verification. |
| `constraint-template-cross-region.yaml` | Illustrates comparing source/destination region labels (expand with GVK for your mesh / Route objects). |

`input.user` in Gatekeeper v3.14+ can be populated from the Kubernetes TokenReview / external data for SPIFFE; wire your **SecurityProfile** or **RequestHeader** mutation to pass SPIFFE ID into OPA as needed.
