# Local Kind Cluster for Lineage Development

Automated setup of a local Kubernetes (Kind) cluster with Marquez, MLflow, MinIO, and the Dataset Registry. Intended for local development and demos when the OpenShift cluster is unavailable.


## Prerequisites

- **Podman** (preferred) or **Docker** -- the scripts auto-detect, defaulting to Podman
- **kind** -- `brew install kind`
- **kubectl** -- `brew install kubectl`

If using Podman, ensure the machine is running: `podman machine start`


## Quick Start

```bash
./setup.sh
```

This single command will:

1. Check that all prerequisites are installed and running
2. Create a Kind cluster named `lineage`
3. Deploy Marquez (PostgreSQL + API + Web UI)
4. Deploy MLflow (PostgreSQL + MinIO + tracking server)
5. Create `mlflow` and `raw-data` S3 buckets in MinIO
6. Seed `customers.csv` into MinIO at `s3://raw-data/customers.csv`
7. Build the Dataset Registry backend and frontend images from local source
8. Load the images into the Kind cluster and deploy the registry (PostgreSQL + API + UI)
9. Start `kubectl port-forward` processes for all services

Images are built for the host platform (`linux/arm64` on Apple Silicon, `linux/amd64` on Intel). When using Podman, images are tagged with `docker.io/library/` prefix to match Kubernetes default image resolution.


## Services

After setup completes, all services are accessible on localhost:

| Service | URL |
|---|---|
| Marquez API | http://localhost:5000/api/v1/namespaces |
| Marquez Web UI | http://localhost:3000 |
| MLflow Tracking | http://localhost:5001 |
| MinIO Console | http://localhost:9001 |
| MinIO API | http://localhost:9000 |
| Dataset Registry API | http://localhost:8080/docs |
| Dataset Registry UI | http://localhost:8081 |

MinIO credentials: `minioadmin` / `minioadmin123`


## Seed Data

The setup script automatically uploads `dataset-registry/customers.csv` (2000 rows of telco subscriber data) into MinIO at:

```
s3://raw-data/customers.csv
```

This means you can immediately register a dataset in the Registry UI at http://localhost:8081 with source `s3://raw-data/customers.csv` and the backend will auto-detect the schema from the CSV.


## File Structure

```
local-kind/
  setup.sh              Main setup script (creates cluster + deploys everything)
  teardown.sh           Deletes the Kind cluster and stops port-forwards
  rebuild-registry.sh   Rebuild and redeploy the Dataset Registry without recreating the cluster
  marquez.yaml          Kubernetes manifests for Marquez (DB, API, Web UI)
  mlflow.yaml           Kubernetes manifests for MLflow (DB, MinIO, server, bucket creation job)
  registry.yaml         Kubernetes manifests for Dataset Registry (DB, API, UI)
  seed-data.yaml        Job to upload customers.csv into MinIO
```


## Rebuilding the Dataset Registry

After making code changes to the backend or frontend, rebuild and redeploy without tearing down the cluster:

```bash
./rebuild-registry.sh          # rebuild both api and ui
./rebuild-registry.sh api      # rebuild backend only
./rebuild-registry.sh ui       # rebuild frontend only
```

This builds the image, loads it into Kind, and restarts the deployment.


## Tearing Down

```bash
./teardown.sh
```

This stops all port-forwards and deletes the Kind cluster. All data is lost since the cluster uses `emptyDir` volumes rather than persistent storage.

To stop port-forwards without destroying the cluster:

```bash
pkill -f 'kubectl port-forward.*-n lineage'
```


## Differences from OpenShift Deployment

| Aspect | OpenShift | Kind (local) |
|---|---|---|
| Container runtime | CRI-O | containerd |
| PostgreSQL image | `registry.redhat.io/rhel9/postgresql-15` | `postgres:15` |
| Storage | PersistentVolumeClaims | emptyDir (ephemeral) |
| Image builds | OpenShift BuildConfig (binary builds) | Local Podman/Docker builds loaded into Kind |
| Routing | OpenShift Routes with TLS | kubectl port-forward |
| Image registry | Internal OpenShift registry | Images loaded directly into Kind nodes |

The application code, container images, and Kubernetes resource shapes are otherwise identical. Environment variables, service names, and database credentials match the OpenShift deployment so that switching between environments requires no code changes.
