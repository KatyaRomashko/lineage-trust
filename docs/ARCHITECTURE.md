# Architecture and Operation

This document describes the architecture and operation of the end-to-end ML system for **customer churn prediction**, built with Feast (feature store), Kubeflow Pipelines (KFP), and MLflow. The system runs locally via Docker Compose and Python, or on OpenShift via KFP and Jobs.

---

## High-Level Flow

```
MinIO (raw CSV)
     │
     ▼
STAGE 1 — ETL (extract → transform → load)
     │
     ▼
PostgreSQL (warehouse + Feast offline store)
     │
     ▼
STAGE 2 — Feast (apply + materialize → Redis)
     │
     ▼
STAGE 3 — ML pipeline (6 steps: extract → validate → engineer → train → eval → register)
     │
     ▼
MLflow (tracking + registry) + MinIO (artifacts)
     │
     ▼
STAGE 4/5 — FastAPI inference (Feast online + MLflow model)
```

---

## Components and Responsibilities

### 1. Configuration (`configs/settings.py`)

Central place for all service endpoints and credentials: MinIO, PostgreSQL, Redis, MLflow, Feast paths, table names, and thresholds. Values are read from environment variables so the same code works in Docker Compose and on OpenShift.

### 2. Stage 1 — ETL (`src/etl/`)

| Module | Role |
|--------|------|
| **extract.py** | Downloads the raw CSV from MinIO (S3-compatible) and returns a pandas DataFrame. |
| **transform.py** | Cleans (drop duplicates by `entity_id`, coerce types, median imputation for nulls), then min-max normalises numeric columns; ensures `event_timestamp` is UTC. |
| **load.py** | Writes the transformed DataFrame to the PostgreSQL table `customer_features`. |

**Orchestrator:** `run_etl.py` runs **extract → transform → load** in sequence. Output is the populated PostgreSQL table that serves as both the data warehouse and Feast’s offline store.

### 3. Stage 2 — Feast (`src/feature_store/`)

| File / concept | Role |
|----------------|------|
| **feature_store.yaml** | Feast config: offline store = PostgreSQL, online store = Redis, registry in PostgreSQL. |
| **definitions.py** | Defines the **entity** `customer` (join key `entity_id`), the **PostgreSQL source** (table `customer_features`), and the **feature view** `customer_features_view` (tenure, charges, tickets, contract_type, internet_service, payment_method). |
| **feast_workflow.py** | **apply**: registers entities/sources/feature views in the Feast registry. **materialize**: copies features from the offline store (PostgreSQL) into the online store (Redis) for a time window. **get_historical_features**: point-in-time join for training (entity_df + timestamps → training DataFrame). |

Typical sequence: **feast apply** then **feast materialize**; training then uses **get_historical_features** so features are correct at prediction time (no leakage).

### 4. Stage 3 — ML Pipeline (`src/pipeline/`)

The same pipeline exists in two forms:

- **Local run** (`run_pipeline.py`): Calls the component functions from `components.py` in sequence in a single process.
- **KFP run** (`kfp_pipeline.py`): Same steps as KFP components; data between steps is passed via Parquet datasets; compiled to `customer_churn_pipeline.yaml` for OpenShift AI.

**Six steps:**

| Step | Name | What it does |
|------|------|----------------|
| 1 | **Data extraction** | Reads `entity_id`, `event_timestamp`, `churn` from PostgreSQL; runs Feast `get_historical_features()` (point-in-time join); merges target back; returns training DataFrame. |
| 2 | **Data validation** | Null checks (fill with 0), schema/type coercion, warns on constant columns. |
| 3 | **Feature engineering** | Adds derived features (`charges_per_month`, `ticket_rate`); clamps infinities. |
| 4 | **Model training** | Label-encodes categoricals, train/test split, XGBoost training; logs params, metrics (ROC-AUC, F1, precision, recall), and model artifact to MLflow (artifacts in MinIO). |
| 5 | **Evaluation** | Uses metrics from step 4; explicit evaluation/aggregation step. |
| 6 | **Model registration** | If ROC-AUC ≥ threshold (e.g. 0.75): registers model in MLflow and sets alias `champion`. |

`components.py` holds the shared logic; `kfp_pipeline.py` wraps it in `@dsl.component` and passes Parquet between steps. Training and registry details live in `src/training/trainer.py` and `src/training/registry.py`.

### 5. Training & Registry (`src/training/`)

- **trainer.py**: Encodes categoricals, builds feature matrix, trains XGBoost, logs run to MLflow (params, metrics, sklearn-flavor model artifact).
- **registry.py**: Helpers to register a model and promote it to an alias (e.g. `champion`), used by the pipeline’s registration step.

### 6. Serving (`src/serving/app.py`)

FastAPI app:

- **Startup**: Loads Feast feature store and MLflow model `models:/{MODEL_NAME}@champion`.
- **`POST /predict`**: Accepts `entity_ids`; gets latest features from Feast online store (Redis); encodes features (same categorical mapping as training); runs XGBoost; returns churn probability and binary prediction per entity.
- **`POST /reload-model`**: Reloads the `champion` model from MLflow without restart.
- **`GET /health`**: Reports model and Feast status.

So at request time: **Feast (Redis) → feature encoding → MLflow model → response**.

---

## How It Is Run

### Local (Docker Compose)

1. **Infrastructure**: `docker-compose up` brings up MinIO, PostgreSQL, Redis, MLflow, and the inference API. MinIO is seeded with `data/customers.csv` via `minio-init`.
2. **Data**: Optionally `python data/generate_dataset.py` to (re)generate the CSV.
3. **Stages**: `./scripts/run_all.sh` runs, in order:
   - (optional) data generation
   - ETL (MinIO → PostgreSQL)
   - Feast apply + materialize
   - ML pipeline (`run_pipeline.py`: all 6 steps in one process)
   - KFP YAML compile (`kfp_pipeline.py` → `customer_churn_pipeline.yaml`)

You can run only one stage: `./scripts/run_all.sh etl`, `feast`, `pipeline`, or `kfp`.

### OpenShift

- **Deploy** (`openshift/deploy.sh`): Creates namespace, secrets, configmaps, PVCs, builds images (e.g. `fkm-app`), deploys MinIO, PostgreSQL, Redis, MLflow, then runs Jobs in order:
  - `01-minio-seed` — put CSV in MinIO  
  - `02-etl` — ETL into PostgreSQL  
  - `03-feast-apply` — Feast apply  
  - `04-feast-materialize` — materialize to Redis  
  - `05-ml-pipeline` — run the ML pipeline (train + evaluate + register)  
  - `06-promote-model` — promote to Production  
- Then deploys the FastAPI inference API and exposes Routes (MLflow, MinIO, inference API).

So the same flow (ETL → Feast → pipeline → promote → serve) is executed as Jobs and services on the cluster.

---

## Data and Control Flow Summary

- **Raw data**: CSV in MinIO.
- **Warehouse**: PostgreSQL table `customer_features` (after ETL).
- **Features**: Defined in Feast; offline = PostgreSQL, online = Redis; training uses point-in-time join, serving uses online retrieval.
- **Experiments and models**: MLflow (PostgreSQL backend, artifacts in MinIO); pipeline logs runs and registers the best model as `champion`.
- **Inference**: FastAPI loads `champion` from MLflow and features from Feast (Redis), then returns churn predictions per `entity_id`.

Overall: **data flows from MinIO → PostgreSQL → Feast (offline + online) and into the pipeline; the pipeline produces a model in MLflow; the API serves predictions using Feast online store and the MLflow-registered model.**

---

## Security, trust, and data-sovereignty (SPIRE, OPA, Sigstore, PROV-O, RHACM, RHACS)

This section describes the **lineage-trust** style controls added around the same ML flow. Many artifacts are **reference manifests**; operators must align versions with their OpenShift minor release and installed operators.

### Geographic region

- **Node labels**: Cloud-backed clusters should already expose `topology.kubernetes.io/region` / `zone` on workers. `openshift/scripts/bootstrap-node-labels.sh` audits gaps and suggests `oc label node …` fixes.
- **Cluster majority**: `openshift/scripts/detect-cluster-region.sh` maps node regions to a coarse **`us` or `eu`** label for policy (heuristic on region string).
- **Namespace + ConfigMap**: `openshift/scripts/apply-fkm-region-labels.sh` (invoked from `openshift/deploy.sh` after `fkm-config` exists) sets `namespace/fkm` labels `region` and `trust.fkm.io/region`, and patches `FKM_REGION` / `SPIFFE_TRUST_DOMAIN` into `fkm-config`.
- **Admission**: `openshift/webhook/webhook-server/webhook.py` exposes **`/mutate-namespace`**; pair it with `openshift/webhook/mutating-webhook-namespace-region.yaml` (TLS CA as for the lineage webhook). Set **`FKM_DEFAULT_REGION`** on the webhook Deployment to match the RHACM cluster label.

### SPIRE / SPIFFE workload identity

- **Install**: See `spire/README.md`, `spire/operator-subscription-spire.yaml`, and reference fragments under `spire/`. Prefer **Red Hat Zero Trust Workload Identity Manager** when your subscription supports it.
- **Registration**: `spire/scripts/register-workloads.sh` is a template for `spire-server entry create` selectors (`k8s:ns`, `k8s:sa`, …); adjust parent IDs and trust domain.
- **Pods / Jobs**: Application workloads under `openshift/jobs/*.yaml`, `openshift/base/inference-api.yaml`, and `openshift/base/mlflow.yaml` mount the **SPIFFE CSI** volume (`csi.spiffe.io`) and set **`SPIFFE_ENDPOINT_SOCKET`** / **`SPIFFE_TRUST_DOMAIN`** / **`FKM_REGION`**. **Prerequisite**: install the SPIFFE CSI driver and SPIRE agent before running these Jobs, otherwise Pods stay unschedulable. For labs without SPIRE, maintain a fork or overlay that strips the CSI volume.
- **Python**: `src/spiffe_utils.py` uses the PyPI **`spiffe`** Workload API client (X.509 SVID) with fallback to `src/security/spiffe_auth.py` for JWT/dev. ETL, Feast workflows, the local pipeline, and FastAPI startup call **`log_identity_for_lineage()`** for audit correlation.

### OPA Gatekeeper

- Templates and sample constraints live in **`policies/gatekeeper/`** (namespace region label, agent-card annotations, cross-region sketch). Enable **config sync** for namespaces if policies must read `data.inventory`.

### Sigstore / Cosign

- **`openshift/deploy.sh`** calls **`cosign_sign_imagestream_tag`** after each BuildConfig build when **`COSIGN_KEY`** is set (install `cosign` and registry login). Use **`SKIP_COSIGN_SIGN=1`** to force-disable signing.
- **`openshift/sigstore/`** documents **`ClusterImagePolicy`**; validate `oc explain clusterimagepolicy` on your version before applying `clusterimagepolicy-fkm.yaml`.
- **Agent cards**: `src/pipeline/agent_card_publish.py` writes JSON and optional **`cosign sign-blob`** output when **`AGENT_CARD_PUBLISH=1`**.

### PROV-O provenance

- **`src/prov_translator.py`** maps OpenLineage-style JSON events to **PROV-O Turtle**. Optional upload: set **`FUSEKI_UPDATE_URL`** for `store_graph_fuseki`.
- **`src/pipeline/prov_input_verify.py`** runs at the start of **`run_pipeline`** and as an **initContainer** on Job `05-ml-pipeline`. With **`PROV_VERIFY_SKIP=0`** and **`PROV_INPUT_RDF`** pointing at Turtle, the job fails closed if the graph is empty or missing an expected dataset URI.

### RHACM / RHACS

- **`openshift/rhacm/`**: example **`Placement`** for EU-only workloads and a **`Policy` + `PlacementBinding`** skeleton to distribute Gatekeeper bundles from the hub.
- **`openshift/rhacs/`**: integration notes (Secured Cluster, compliance checks, runtime alerts). **`openshift/base/networkpolicy-fkm-egress.yaml`** is a baseline for MLflow + inference egress tightening; validate in RHACS **Network Graph** before enforcing in production.

### Validation and CI

- **`openshift/validate-trust.sh`**: cluster smoke checks (namespace region, CSI reference in Deployment, ConfigMap keys; optional Gatekeeper / RHACM detection).
- **`.github/workflows/trust-e2e.yml`**: runs PROV translator smoke on GitHub-hosted runners; **cluster jobs** expect self-hosted runners with `oc` and kubeconfigs for US/EU.

### Troubleshooting

| Symptom | Likely cause | Mitigation |
|--------|----------------|------------|
| Pods `Pending` / CSI mount errors | SPIFFE CSI not installed | Install SPIRE / CSI from `spire/` docs, or remove CSI volumes for non-SPIRE clusters. |
| Namespace denied by Gatekeeper | `region` label missing | Run `./openshift/scripts/apply-fkm-region-labels.sh` or fix webhook `FKM_DEFAULT_REGION`. |
| Cosign sign failures | Missing registry login or key | `oc registry login …`; set `COSIGN_KEY`; or `SKIP_COSIGN_SIGN=1`. |
| PROV initContainer fails | `PROV_VERIFY_SKIP=0` without valid `PROV_INPUT_RDF` | Set `PROV_VERIFY_SKIP=1` (default) until graphs are wired. |
| Webhook namespace patch ignored | `failurePolicy: Ignore` or TLS/CABundle mismatch | Regenerate certs per `openshift/webhook/generate-webhook-certs.sh` and reapply MWH. |
