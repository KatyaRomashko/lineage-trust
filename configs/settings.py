"""
Centralised configuration – all service endpoints and credentials in one place.
Values fall back to environment variables so the same code works inside
Docker Compose and on a local dev machine.
"""

import os

# ── MinIO / S3 ──────────────────────────────────────────────────────────
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "raw-data")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

# ── PostgreSQL ──────────────────────────────────────────────────────────
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_USER = os.getenv("PG_USER", "feast")
PG_PASSWORD = os.getenv("PG_PASSWORD", "feast")
PG_DATABASE = os.getenv("PG_DATABASE", "warehouse")
PG_URL = (
    f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
)

# ── Redis ───────────────────────────────────────────────────────────────
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# ── MLflow ──────────────────────────────────────────────────────────────
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
MLFLOW_S3_ENDPOINT_URL = os.getenv("MLFLOW_S3_ENDPOINT_URL", "http://localhost:9000")
MLFLOW_EXPERIMENT_NAME = os.getenv("MLFLOW_EXPERIMENT_NAME", "customer_churn_lineage")
MODEL_NAME = os.getenv("MODEL_NAME", "customer_churn_model")

# ── Feast ───────────────────────────────────────────────────────────────
FEAST_REPO_PATH = os.getenv("FEAST_REPO_PATH", "src/feature_store")

# ── Data ────────────────────────────────────────────────────────────────
RAW_CSV_OBJECT = os.getenv("RAW_CSV_OBJECT", "customers.csv")
WAREHOUSE_TABLE = "customer_features"
TARGET_COLUMN = "churn"
ENTITY_COLUMN = "entity_id"
TIMESTAMP_COLUMN = "event_timestamp"

# ── Thresholds ──────────────────────────────────────────────────────────
MODEL_ROC_AUC_THRESHOLD = float(os.getenv("MODEL_ROC_AUC_THRESHOLD", "0.70"))

# ── Security (SPIFFE, OPA, Rekor, PROV-O, EU compliance) ─────────────────
AGENT_ID = os.getenv("AGENT_ID", "spiffe://example.org/ns/churn/pipeline-agent")
OPA_URL = os.getenv("OPA_URL", "http://localhost:8181")
OPA_STRICT = os.getenv("OPA_STRICT", "1") == "1"
REKOR_URL = os.getenv("REKOR_URL", "https://rekor.sigstore.dev")
REKOR_UPLOAD = os.getenv("REKOR_UPLOAD", "0") == "1"
SPIFFE_JWT_PATH = os.getenv("SPIFFE_JWT_PATH", "")
SPIFFE_REQUIRED = os.getenv("SPIFFE_REQUIRED", "0") == "1"
PROV_OUTPUT_DIR = os.getenv("PROV_OUTPUT_DIR", "/tmp/prov-o")
TRANSPARENCY_LOG_PATH = os.getenv("TRANSPARENCY_LOG_PATH", "/tmp/audit/transparency.jsonl")
REGIONAL_POLICY = os.getenv("REGIONAL_POLICY", "NON_EU")
FKM_REGION = os.getenv("FKM_REGION", "unset")
SPIFFE_TRUST_DOMAIN = os.getenv("SPIFFE_TRUST_DOMAIN", "spiffe://fkm.cluster.local")
FUSEKI_UPDATE_URL = os.getenv("FUSEKI_UPDATE_URL", "")
PROV_INPUT_RDF = os.getenv("PROV_INPUT_RDF", "")
PROV_VERIFY_SKIP = os.getenv("PROV_VERIFY_SKIP", "1") == "1"
LLM_TRACE_ID = os.getenv("LLM_TRACE_ID", "")
LLM_MONITORING_TOOL = os.getenv("LLM_MONITORING_TOOL", "langsmith")
