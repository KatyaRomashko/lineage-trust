# End-to-End ML System — Feast · KFP · MLflow

A production-style machine learning system for **customer churn prediction**
using MinIO, PostgreSQL, Feast, Redis, Kubeflow Pipelines, MLflow, and FastAPI.

---

## Architecture

```
MinIO (raw CSV)
     │
     ▼
ETL Job (extract → clean → normalise)
     │
     ▼
PostgreSQL  (Data Warehouse + Feast offline store)
     │
     ▼
Feast  (feature definitions, materialization → Redis)
     │
     ▼
Kubeflow Pipeline
  ├─ Step 1  Data Extraction (Feast historical features)
  ├─ Step 2  Data Validation
  ├─ Step 3  Feature Engineering
  ├─ Step 4  Model Training (XGBoost + MLflow tracking)
  ├─ Step 5  Evaluation (ROC-AUC, F1, Precision, Recall)
  └─ Step 6  Model Registration (MLflow Registry → Staging/Production)
     │
     ▼
FastAPI Inference Service
  └─ Feast online store (Redis) → Model → Prediction
```

For a detailed description of the architecture and operation, see **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Project Structure

```
.
├── Dockerfile                   # Unified app image (ETL + Feast + Pipeline + API)
├── Dockerfile.mlflow            # MLflow tracking server image
├── Dockerfile.api               # FastAPI inference image (Docker Compose)
├── docker-compose.yml           # Local dev environment
├── requirements.txt             # Python dependencies
├── .env                         # Local environment variables
│
├── configs/
│   └── settings.py              # Centralised configuration
│
├── data/
│   ├── generate_dataset.py      # Synthetic dataset generator
│   └── customers.csv            # Generated sample data
│
├── scripts/                     # Docker Compose local scripts
│   ├── start_services.sh
│   ├── run_all.sh
│   └── test_inference.sh
│
├── openshift/                   # OpenShift deployment manifests
│   ├── deploy.sh                # One-command deploy to OpenShift
│   ├── status.sh                # Namespace status check
│   ├── test-api.sh              # Smoke-test via Route
│   ├── base/
│   │   ├── namespace.yaml       # fkm namespace
│   │   ├── secret.yaml          # Credentials
│   │   ├── configmap.yaml       # Service endpoints
│   │   ├── feast-config.yaml    # Feast feature_store.yaml (cluster)
│   │   ├── pvc.yaml             # MinIO + PostgreSQL storage
│   │   ├── buildconfig.yaml     # ImageStreams + BuildConfigs
│   │   ├── minio.yaml           # MinIO Deployment + Service
│   │   ├── postgres.yaml        # PostgreSQL Deployment + Service
│   │   ├── redis.yaml           # Redis Deployment + Service
│   │   ├── mlflow.yaml          # MLflow Deployment + Service
│   │   ├── inference-api.yaml   # FastAPI Deployment + Service
│   │   └── routes.yaml          # OpenShift Routes (TLS)
│   └── jobs/
│       ├── 01-minio-seed.yaml   # Seed MinIO with CSV
│       ├── 02-etl.yaml          # ETL: MinIO → PostgreSQL
│       ├── 03-feast-apply.yaml  # Feast apply
│       ├── 04-feast-materialize.yaml  # Feast materialize
│       ├── 05-ml-pipeline.yaml  # Train + evaluate + register
│       └── 06-promote-model.yaml# Promote to Production
│
├── src/
│   ├── etl/
│   │   ├── extract.py           # Stage 1A – MinIO extraction
│   │   ├── transform.py         # Stage 1B – Cleaning & normalisation
│   │   ├── load.py              # Stage 1C – PostgreSQL load
│   │   └── run_etl.py           # Stage 1  – ETL orchestrator
│   │
│   ├── feature_store/
│   │   ├── feature_store.yaml   # Feast configuration (local dev)
│   │   ├── definitions.py       # Entity, source, feature view
│   │   └── feast_workflow.py    # apply / materialize / historical
│   │
│   ├── pipeline/
│   │   ├── components.py        # Stage 3  – KFP component functions
│   │   ├── run_pipeline.py      # Stage 3  – Local pipeline runner
│   │   └── kfp_pipeline.py      # Stage 3  – KFP DSL + compiler
│   │
│   ├── training/
│   │   ├── trainer.py           # Stage 4  – XGBoost + MLflow logging
│   │   └── registry.py          # Stage 4  – Model Registry helpers
│   │
│   └── serving/
│       └── app.py               # Stage 5  – FastAPI inference service
│
└── tests/                       # (placeholder for unit tests)
```

---

## Quick Start

### Prerequisites

| Tool           | Version |
|----------------|---------|
| Docker Desktop | ≥ 4.x  |
| Python         | ≥ 3.10 |
| pip / venv     | latest  |

### 1. Start infrastructure

```bash
# Build & start all containers (MinIO, PostgreSQL, Redis, MLflow, API)
./scripts/start_services.sh
```

Services & UIs:

| Service       | URL                           | Credentials             |
|---------------|-------------------------------|-------------------------|
| MinIO Console | http://localhost:9001         | minioadmin / minioadmin  |
| MLflow UI     | http://localhost:5000         | —                       |
| Inference API | http://localhost:8000/docs    | —                       |

### 2. Install Python dependencies (local)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Generate sample data (already done if CSV exists)

```bash
python3 data/generate_dataset.py
```

### 4. Run end-to-end

```bash
# Run all stages in sequence
./scripts/run_all.sh
```

Or run stages individually:

```bash
# Stage 1 – ETL
./scripts/run_all.sh etl

# Stage 2 – Feast
./scripts/run_all.sh feast

# Stage 3 – Pipeline (train + register)
./scripts/run_all.sh pipeline

# Compile KFP YAML
./scripts/run_all.sh kfp
```

### 5. Test the inference API

```bash
./scripts/test_inference.sh

# Or manually:
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"entity_ids": [1, 2, 3]}'
```

---

## Stage Details

### Stage 1 — ETL

`src/etl/run_etl.py` downloads the CSV from MinIO, cleans nulls (median
imputation), min-max normalises numerical columns, then writes the result
to the `customer_features` table in PostgreSQL.

### Stage 2 — Feast

- **`feature_store.yaml`** — offline store = PostgreSQL, online store = Redis
- **`definitions.py`** — entity, PostgreSQL data source, feature view
- **`feast apply`** — registers metadata in the SQL-backed registry
- **`feast materialize`** — copies latest features from PostgreSQL into Redis

### Stage 3 — Kubeflow Pipeline

Six sequential components:

1. **Data Extraction** — Feast `get_historical_features()` with point-in-time join
2. **Data Validation** — null/schema/distribution checks
3. **Feature Engineering** — derived ratios (`charges_per_month`, `ticket_rate`)
4. **Model Training** — XGBoost classifier, params/metrics/model logged to MLflow
5. **Evaluation** — ROC-AUC, F1, Precision, Recall
6. **Model Registration** — if ROC-AUC ≥ threshold → MLflow Registry → Staging

The pipeline can run locally (`run_pipeline.py`) or be compiled to a KFP YAML
(`kfp_pipeline.py`) for submission to a Kubeflow cluster.

### Stage 4 — MLflow

- **Tracking:** experiment name, run ID, hyperparameters, metrics, model artifact
- **Registry:** model name, version, stage lifecycle (None → Staging → Production → Archived)
- **Utilities:** `registry.py` provides promote, archive, and rollback helpers

### Stage 5 — Online Inference

FastAPI service at `/predict`:

1. Receives `entity_ids`
2. Queries Feast online store (Redis) for latest features
3. Loads the Production model from MLflow
4. Returns churn probability + binary prediction per entity

Hot-reload: `POST /reload-model` fetches the latest Production model without restart.

---

## Promoting a Model to Production

After the pipeline registers a model version in **Staging**:

```python
from src.training.registry import transition_stage

transition_stage(
    model_name="customer_churn_model",
    version=1,
    stage="Production",
    tracking_uri="http://localhost:5000",
)
```

Then reload the inference service:

```bash
curl -X POST http://localhost:8000/reload-model
```

---

## OpenShift Deployment (namespace: fkm)

### Prerequisites

| Tool   | Version |
|--------|---------|
| `oc`   | ≥ 4.x  |
| Logged in to your OpenShift cluster (`oc login`) |

### One-command deploy

```bash
./openshift/deploy.sh
```

This script performs the following in order:

1. Creates the `fkm` namespace, Secrets, ConfigMaps, PVCs
2. Creates ImageStreams + BuildConfigs, then builds the `fkm-app` and `mlflow-server` images via `oc start-build --from-dir`
3. Deploys MinIO, PostgreSQL, Redis, MLflow (waits for readiness)
4. Runs 6 sequential Jobs:
   - `01-minio-seed` — upload CSV to MinIO
   - `02-etl` — ETL: MinIO → PostgreSQL
   - `03-feast-apply` — register Feast entities/features
   - `04-feast-materialize` — offline store → online store (Redis)
   - `05-ml-pipeline` — train XGBoost + log to MLflow + register model
   - `06-promote-model` — promote Staging → Production
5. Deploys the FastAPI inference API
6. Creates OpenShift Routes (TLS edge-terminated)

### Partial deploys

```bash
./openshift/deploy.sh infra     # Infrastructure only (no jobs)
./openshift/deploy.sh build     # Rebuild images only
./openshift/deploy.sh jobs      # Run pipeline jobs only
```

### Check status

```bash
./openshift/status.sh           # Pods, services, routes, jobs, events
oc get pods -n fkm         # Quick pod check
oc logs job/ml-pipeline -n fkm   # View pipeline logs
```

### Test the API

```bash
./openshift/test-api.sh

# Or manually:
HOST=$(oc get route inference-api -n fkm -o jsonpath='{.spec.host}')
curl -sk -X POST "https://$HOST/predict" \
  -H "Content-Type: application/json" \
  -d '{"entity_ids": [1, 2, 3]}'
```

### Exposed Routes

| Service       | Route name      | Description                |
|---------------|-----------------|----------------------------|
| Inference API | `inference-api` | `/docs` for Swagger UI     |
| MLflow UI     | `mlflow`        | Experiment tracking        |
| MinIO Console | `minio-console` | Object storage browser     |

### Re-run a Job

```bash
oc delete job etl-job -n fkm
oc apply -f openshift/jobs/02-etl.yaml
```

### Teardown

```bash
# Remove everything in the namespace
./openshift/deploy.sh teardown

# Or manually:
oc delete namespace fkm
```

---

## Local Development (Docker Compose)

### Teardown

```bash
docker compose down -v   # Stop containers and remove volumes
```
