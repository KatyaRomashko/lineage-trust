"""
STAGE 3  -  Kubeflow Pipelines v2 DSL definition for OpenShift AI.

Each component uses the pre-built fkm-app image (which already contains
all Python dependencies, source code, and the Feast feature_store.yaml).

Compile:
    python -m src.pipeline.kfp_pipeline

Upload to OpenShift AI:
    python -m src.pipeline.upload_pipeline
"""

from kfp import dsl, compiler
from kfp import kubernetes

# The fkm-app image built via OpenShift BuildConfig contains all deps.
# Override at pipeline-creation time via the `image` parameter.
FKM_IMAGE = (
    "image-registry.openshift-image-registry.svc:5000/fkm/fkm-app:latest"
)
SPARK_IMAGE = (
    "image-registry.openshift-image-registry.svc:5000/fkm/spark-etl:latest"
)


# =======================================================================
# PLATFORM - Spark ETL (CSV -> transform -> PostgreSQL, emits OpenLineage)
# =======================================================================
@dsl.component(base_image=SPARK_IMAGE)
def platform_spark_etl(
    minio_endpoint: str,
    pg_host: str,
    pg_user: str,
    pg_password: str,
    pg_database: str,
    warehouse_table: str,
    openlineage_url: str,
    aws_access_key: str,
    aws_secret_key: str,
    agent_id: str,
) -> str:
    """PySpark ETL that reads CSV from MinIO, transforms, writes to PostgreSQL.
    The OpenLineage Spark listener emits lineage events automatically.
    OPENLINEAGE_NAMESPACE is injected by the Argo workflow controller."""
    import os
    import subprocess
    from openlineage_oai.adapters.kfp import kfp_lineage
    from src.security.guards import finalize_step_audit, pipeline_step_guard

    sec = pipeline_step_guard(
        step_name="platform_spark_etl",
        activity_label="Spark ETL (MinIO CSV → PostgreSQL warehouse)",
        agent_id=agent_id,
        opa_input=None,
        used_entities=[
            {"label": "s3://raw-data/customers.csv"},
        ],
        generated_entities=[
            {"label": f"postgres://{pg_host}:5432/{pg_database}.{warehouse_table}"},
        ],
    )

    os.environ["MINIO_ENDPOINT"] = minio_endpoint
    os.environ["PG_HOST"] = pg_host
    os.environ["PG_USER"] = pg_user
    os.environ["PG_PASSWORD"] = pg_password
    os.environ["PG_DATABASE"] = pg_database
    os.environ["WAREHOUSE_TABLE"] = warehouse_table
    os.environ["OPENLINEAGE_URL"] = openlineage_url
    os.environ["AWS_ACCESS_KEY_ID"] = aws_access_key
    os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret_key

    with kfp_lineage(
        "kfp-spark_etl",
        inputs=[{"namespace": "s3://raw-data", "name": "customers.csv"}],
        outputs=[{"namespace": f"postgres://{pg_host}:5432", "name": f"{pg_database}.{warehouse_table}"}],
        url=openlineage_url,
    ):
        result = subprocess.run(
            ["python3", "/opt/spark/spark_etl.py"],
            capture_output=True, text=True,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"STDERR: {result.stderr}")
            raise RuntimeError(f"Spark ETL failed: {result.stderr[:500]}")
        print("Platform: spark ETL succeeded")
    finalize_step_audit(
        step_name="platform_spark_etl",
        context=sec,
        result_summary={"status": "etl_done"},
    )
    return "etl_done"


# =======================================================================
# PLATFORM - Feast Apply (registers entities/views, emits OpenLineage)
# =======================================================================
@dsl.component(base_image=FKM_IMAGE)
def platform_feast_apply(
    feast_repo_path: str,
    pg_host: str,
    redis_host: str,
    agent_id: str,
) -> str:
    """Run feast apply to register feature definitions. Emits OpenLineage events."""
    import os
    import subprocess
    from openlineage_oai.adapters.kfp import kfp_lineage
    from src.security.guards import finalize_step_audit, pipeline_step_guard

    sec = pipeline_step_guard(
        step_name="platform_feast_apply",
        activity_label="Feast apply (registry + feature views)",
        agent_id=agent_id,
        opa_input=None,
        used_entities=[{"label": "warehouse.customer_features"}],
        generated_entities=[{"label": "warehouse.customer_features_view"}],
    )

    ol_namespace = os.environ.get("OPENLINEAGE_NAMESPACE", "default")
    feast_project = ol_namespace.replace("-", "_")
    fs_yaml = os.path.join(feast_repo_path, "feature_store.yaml")
    with open(fs_yaml, "w") as f:
        f.write(f"""\
project: {feast_project}
provider: local
registry:
  registry_type: sql
  path: postgresql://feast:feast@{pg_host}:5432/warehouse
  cache_ttl_seconds: 60
offline_store:
  type: postgres
  host: {pg_host}
  port: 5432
  database: warehouse
  db_schema: public
  user: feast
  password: feast
online_store:
  type: redis
  connection_string: {redis_host}:6379
entity_key_serialization_version: 2
openlineage:
  enabled: true
  transport_type: http
  transport_url: http://marquez
  emit_on_apply: true
  emit_on_materialize: true
""")
    print(f"Patched {fs_yaml} -> ol_ns={ol_namespace}")

    pg_ns = f"postgres://{pg_host}:5432"

    feast_ns = ol_namespace.replace("-", "_")

    with kfp_lineage(
        "kfp-feast_apply",
        inputs=[{"namespace": pg_ns, "name": "warehouse.customer_features"}],
        outputs=[
            {"namespace": pg_ns, "name": "warehouse.customer_features_view"},
        ],
        url="http://marquez",
    ):
        env = os.environ.copy()
        env["REDIS_PORT"] = "6379"
        result = subprocess.run(
            ["feast", "apply"],
            cwd=feast_repo_path,
            capture_output=True, text=True,
            env=env,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"STDERR: {result.stderr}")
            raise RuntimeError(f"feast apply failed: {result.stderr[:500]}")
        print("Platform: feast apply succeeded")
    finalize_step_audit(
        step_name="platform_feast_apply",
        context=sec,
        result_summary={"status": "applied"},
    )
    return "applied"


# =======================================================================
# PLATFORM - Feast Materialize (offline -> online store, emits OpenLineage)
# =======================================================================
@dsl.component(base_image=FKM_IMAGE)
def platform_feast_materialize(
    feast_repo_path: str,
    pg_host: str,
    redis_host: str,
    apply_done: str,
    agent_id: str,
) -> str:
    """Materialize features from offline to online store. Emits OpenLineage events."""
    import os
    from datetime import datetime, timedelta
    from feast import FeatureStore
    from openlineage_oai.adapters.kfp import kfp_lineage
    from src.security.guards import finalize_step_audit, pipeline_step_guard

    sec = pipeline_step_guard(
        step_name="platform_feast_materialize",
        activity_label="Feast materialize (offline → online store)",
        agent_id=agent_id,
        opa_input=None,
        used_entities=[{"label": "warehouse.customer_features"}],
        generated_entities=[{"label": "redis:online_store"}],
    )

    ol_namespace = os.environ.get("OPENLINEAGE_NAMESPACE", "default")
    feast_project = ol_namespace.replace("-", "_")
    fs_yaml = os.path.join(feast_repo_path, "feature_store.yaml")
    with open(fs_yaml, "w") as f:
        f.write(f"""\
project: {feast_project}
provider: local
registry:
  registry_type: sql
  path: postgresql://feast:feast@{pg_host}:5432/warehouse
  cache_ttl_seconds: 60
offline_store:
  type: postgres
  host: {pg_host}
  port: 5432
  database: warehouse
  db_schema: public
  user: feast
  password: feast
online_store:
  type: redis
  connection_string: {redis_host}:6379
entity_key_serialization_version: 2
openlineage:
  enabled: true
  transport_type: http
  transport_url: http://marquez
  emit_on_apply: true
  emit_on_materialize: true
""")

    pg_ns = f"postgres://{pg_host}:5432"

    with kfp_lineage(
        "kfp-feast_materialize",
        inputs=[{"namespace": pg_ns, "name": "warehouse.customer_features"}],
        outputs=[{"namespace": feast_project, "name": "online_store_customer_features_view"}],
        url="http://marquez",
    ):
        store = FeatureStore(repo_path=feast_repo_path)
        end = datetime.utcnow()
        start = end - timedelta(days=1000)
        print(f"Materializing features {start.isoformat()} -> {end.isoformat()}")
        store.materialize(start_date=start, end_date=end)
        print("Platform: feast materialize succeeded")
    finalize_step_audit(
        step_name="platform_feast_materialize",
        context=sec,
        result_summary={"status": "materialized"},
    )
    return "materialized"


# =======================================================================
# DS - Data Extraction via Feast
# =======================================================================
@dsl.component(base_image=FKM_IMAGE)
def ds_data_extraction(
    pg_url: str,
    feast_repo_path: str,
    table_name: str,
    pg_host: str,
    redis_host: str,
    materialize_done: str,
    agent_id: str,
    output_path: dsl.Output[dsl.Dataset],
) -> None:
    """Retrieve historical features from Feast and save as parquet."""
    import os

    import pandas as pd
    from sqlalchemy import create_engine, text
    from feast import FeatureStore
    from openlineage_oai.adapters.kfp import kfp_lineage, kfp_output_with_schema
    from src.security.guards import finalize_step_audit, pipeline_step_guard

    sec = pipeline_step_guard(
        step_name="ds_data_extraction",
        activity_label="Feast historical feature extraction",
        agent_id=agent_id,
        opa_input=None,
        used_entities=[{"label": "warehouse.customer_features_view"}],
        generated_entities=[{"label": "parquet:extracted_features"}],
    )

    ol_namespace = os.environ.get("OPENLINEAGE_NAMESPACE", "default")
    feast_project = ol_namespace.replace("-", "_")
    fs_yaml = os.path.join(feast_repo_path, "feature_store.yaml")
    with open(fs_yaml, "w") as f:
        f.write(f"""\
project: {feast_project}
provider: local
registry:
  registry_type: sql
  path: postgresql://feast:feast@{pg_host}:5432/warehouse
  cache_ttl_seconds: 60
offline_store:
  type: postgres
  host: {pg_host}
  port: 5432
  database: warehouse
  db_schema: public
  user: feast
  password: feast
online_store:
  type: redis
  connection_string: {redis_host}:6379
entity_key_serialization_version: 2
openlineage:
  enabled: true
  transport_type: http
  transport_url: http://marquez
  emit_on_apply: true
  emit_on_materialize: true
""")
    print(f"Patched {fs_yaml} -> pg={pg_host}, redis={redis_host}, ol_ns={ol_namespace}")

    with kfp_lineage(
        "kfp-data_extraction",
        inputs=[{"namespace": f"postgres://{pg_host}:5432", "name": "warehouse.customer_features_view"}],
        outputs=[],
        url="http://marquez",
    ) as run:
        engine = create_engine(pg_url)
        with engine.connect() as conn:
            entity_df = pd.read_sql(
                text(f"SELECT entity_id, event_timestamp, churn FROM {table_name}"),
                conn,
            )
        engine.dispose()
        entity_df["event_timestamp"] = pd.to_datetime(
            entity_df["event_timestamp"], utc=True,
        )

        store = FeatureStore(repo_path=feast_repo_path)
        features = [
            "customer_features_view:tenure_months",
            "customer_features_view:monthly_charges",
            "customer_features_view:total_charges",
            "customer_features_view:num_support_tickets",
            "customer_features_view:contract_type",
            "customer_features_view:internet_service",
            "customer_features_view:payment_method",
        ]
        features_df = store.get_historical_features(
            entity_df=entity_df[["entity_id", "event_timestamp"]],
            features=features,
        ).to_df()

        for df_ in (features_df, entity_df):
            df_["event_timestamp"] = pd.to_datetime(
                df_["event_timestamp"], utc=True,
            )

        result = features_df.merge(
            entity_df[["entity_id", "event_timestamp", "churn"]],
            on=["entity_id", "event_timestamp"],
            how="left",
        )
        print(f"DS: data extraction complete - shape {result.shape}")
        result.to_parquet(output_path.path)
        run.add_output(kfp_output_with_schema(output_path, result))
    finalize_step_audit(
        step_name="ds_data_extraction",
        context=sec,
        result_summary={"rows": int(result.shape[0])},
    )


# =======================================================================
# DS - Feature Engineering
# =======================================================================
@dsl.component(base_image=FKM_IMAGE)
def ds_feature_engineering(
    dataset: dsl.Input[dsl.Dataset],
    agent_id: str,
    regional_policy: str,
    llm_trace_id: str,
    llm_monitoring_tool: str,
    modify_original_date: bool,
    hours_deviation: float,
    output_path: dsl.Output[dsl.Dataset],
) -> None:
    """Add derived features; optional Original_Date change under OPA; EU reasoning_hash."""
    import numpy as np
    import pandas as pd
    from openlineage_oai.adapters.kfp import kfp_lineage, kfp_output_with_schema
    from src.security.eu_compliance import eu_date_metadata_columns
    from src.security.guards import finalize_step_audit, pipeline_step_guard
    from src.security.opa_client import evaluate_churn_policy

    sec = pipeline_step_guard(
        step_name="ds_feature_engineering",
        activity_label="Feature engineering (derived columns)",
        agent_id=agent_id,
        opa_input=None,
        used_entities=[{"label": str(dataset.path)}],
        generated_entities=[{"label": "parquet:engineered_features"}],
    )

    with kfp_lineage(
        "kfp-feature_engineering",
        inputs=[dataset],
        outputs=[],
        url="http://marquez",
    ) as run:
        df = pd.read_parquet(dataset.path)
        old_ts = str(df["event_timestamp"].min())

        if modify_original_date:
            allowed = evaluate_churn_policy(
                {
                    "action": "modify_original_date",
                    "regional_policy": regional_policy,
                    "hours_deviation": float(hours_deviation),
                    "agent_id": agent_id,
                },
            )
            if not allowed:
                raise PermissionError(
                    "OPA denied modify_original_date "
                    f"(regional_policy={regional_policy!r}, "
                    f"hours_deviation={hours_deviation!r})",
                )
            delta = pd.Timedelta(hours=float(hours_deviation))
            df["event_timestamp"] = pd.to_datetime(
                df["event_timestamp"], utc=True,
            ) + delta

        new_ts = str(df["event_timestamp"].min())

        if regional_policy.upper() == "EU":
            meta = eu_date_metadata_columns(
                regional_policy=regional_policy,
                llm_trace_id=llm_trace_id,
                monitoring_tool=llm_monitoring_tool,
                old_iso=old_ts,
                new_iso=new_ts,
                agent_id=agent_id,
            )
            for k, v in meta.items():
                df[k] = v

        tenure_safe = df["tenure_months"].replace(0, 1)
        df["charges_per_month"] = df["total_charges"] / tenure_safe
        df["ticket_rate"] = df["num_support_tickets"] / tenure_safe

        for col in ["charges_per_month", "ticket_rate"]:
            df[col] = df[col].replace([np.inf, -np.inf], 0.0)

        print(f"DS: feature engineering complete - shape {df.shape}")
        df.to_parquet(output_path.path)
        run.add_output(kfp_output_with_schema(output_path, df))
    finalize_step_audit(
        step_name="ds_feature_engineering",
        context=sec,
        result_summary={
            "modify_original_date": modify_original_date,
            "regional_policy": regional_policy,
            "eu_compliance_columns": regional_policy.upper() == "EU",
        },
    )


# =======================================================================
# DS - Model Training + MLflow (emits OpenLineage)
# =======================================================================
@dsl.component(base_image=FKM_IMAGE)
def ds_model_training(
    dataset: dsl.Input[dsl.Dataset],
    tracking_uri: str,
    experiment_name: str,
    s3_endpoint: str,
    aws_key: str,
    aws_secret: str,
    agent_id: str,
) -> str:
    """Train XGBoost, log to MLflow. Returns JSON with run_id, model_uri, metrics."""
    import json
    import os

    import mlflow
    import mlflow.data
    import mlflow.sklearn
    import numpy as np
    import pandas as pd
    import xgboost as xgb
    from openlineage_oai.adapters.kfp import kfp_lineage
    from openlineage_oai.adapters.mlflow.dataset_source import URIDatasetSource
    from sklearn.metrics import (
        f1_score, precision_score, recall_score, roc_auc_score,
    )
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import LabelEncoder
    from src.security.guards import finalize_step_audit, pipeline_step_guard

    sec = pipeline_step_guard(
        step_name="ds_model_training",
        activity_label="XGBoost training + MLflow logging",
        agent_id=agent_id,
        opa_input=None,
        used_entities=[{"label": str(dataset.path)}],
        generated_entities=[{"label": "mlflow:model"}],
    )

    ol_namespace = os.environ.get("OPENLINEAGE_NAMESPACE", "default")

    os.environ["MLFLOW_S3_ENDPOINT_URL"] = s3_endpoint
    os.environ["AWS_ACCESS_KEY_ID"] = aws_key
    os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret
    os.environ["OPENLINEAGE_URL"] = "http://marquez"

    with kfp_lineage(
        "kfp-model_training",
        inputs=[dataset],
        outputs=[{"namespace": ol_namespace, "name": "model.model"}],
        url="http://marquez",
    ):
        df = pd.read_parquet(dataset.path)

        cat_cols = ["contract_type", "internet_service", "payment_method"]
        for col in cat_cols:
            df[col] = LabelEncoder().fit_transform(df[col].astype(str))

        feature_cols = [
            "tenure_months", "monthly_charges", "total_charges",
            "num_support_tickets", "contract_type", "internet_service",
            "payment_method",
        ]
        X = df[feature_cols].values.astype(np.float32)
        y = df["churn"].values.astype(np.int32)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y,
        )

        params = {
            "max_depth": 6,
            "learning_rate": 0.1,
            "n_estimators": 200,
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "seed": 42,
        }

        mlflow.set_tracking_uri(tracking_uri)
        artifact_root = os.getenv("MLFLOW_S3_ARTIFACT_ROOT", "s3://mlflow/artifacts")
        if mlflow.get_experiment_by_name(experiment_name) is None:
            mlflow.create_experiment(experiment_name, artifact_location=artifact_root)
        mlflow.set_experiment(experiment_name)

        with mlflow.start_run() as run:
            train_dataset = mlflow.data.from_pandas(
                df, source=URIDatasetSource(dataset.uri), name="engineered_features",
            )
            mlflow.log_input(train_dataset, context="training")

            mlflow.log_params(params)

            model = xgb.XGBClassifier(**params)
            model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

            y_pred = model.predict(X_test)
            y_prob = model.predict_proba(X_test)[:, 1]

            metrics = {
                "roc_auc": float(roc_auc_score(y_test, y_prob)),
                "f1": float(f1_score(y_test, y_pred)),
                "precision": float(precision_score(y_test, y_pred)),
                "recall": float(recall_score(y_test, y_pred)),
            }
            mlflow.log_metrics(metrics)

            info = mlflow.sklearn.log_model(model, artifact_path="model")

            print(f"DS: model training complete - metrics: {metrics}")
            out = json.dumps({
                "run_id": run.info.run_id,
                "model_uri": info.model_uri,
                "metrics": metrics,
            })
    finalize_step_audit(
        step_name="ds_model_training",
        context=sec,
        result_summary={"ok": True},
    )
    return out


# =======================================================================
# DS - Evaluation
# =======================================================================
@dsl.component(base_image=FKM_IMAGE)
def ds_evaluation(train_result_json: str, agent_id: str) -> str:
    """Display and return evaluation metrics."""
    import json
    import os
    from openlineage_oai.adapters.kfp import kfp_lineage
    from src.security.guards import finalize_step_audit, pipeline_step_guard

    sec = pipeline_step_guard(
        step_name="ds_evaluation",
        activity_label="Model evaluation summary",
        agent_id=agent_id,
        opa_input=None,
        used_entities=[{"label": "mlflow:train_metrics"}],
        generated_entities=[{"label": "metrics:evaluation"}],
    )

    ol_namespace = os.environ.get("OPENLINEAGE_NAMESPACE", "default")

    with kfp_lineage(
        "kfp-evaluation",
        inputs=[{"namespace": ol_namespace, "name": "model.model"}],
        outputs=[],
        url="http://marquez",
    ):
        result = json.loads(train_result_json)
        m = result["metrics"]
        print(
            f"DS: evaluation  ROC-AUC={m['roc_auc']:.4f}  F1={m['f1']:.4f}  "
            f"Precision={m['precision']:.4f}  Recall={m['recall']:.4f}"
        )
        out = json.dumps(m)
    finalize_step_audit(
        step_name="ds_evaluation",
        context=sec,
        result_summary={"ok": True},
    )
    return out


# =======================================================================
# DS - Model Registration
# =======================================================================
@dsl.component(base_image=FKM_IMAGE)
def ds_model_registration(
    train_result_json: str,
    metrics_json: str,
    model_name: str,
    tracking_uri: str,
    s3_endpoint: str,
    aws_key: str,
    aws_secret: str,
    roc_auc_threshold: float,
    agent_id: str,
) -> str:
    """Register model in MLflow if metrics beat the threshold."""
    import json
    import os

    import mlflow
    from mlflow.tracking import MlflowClient
    from openlineage_oai.adapters.kfp import kfp_lineage
    from src.security.guards import finalize_step_audit, pipeline_step_guard

    sec = pipeline_step_guard(
        step_name="ds_model_registration",
        activity_label="MLflow model registration / alias",
        agent_id=agent_id,
        opa_input=None,
        used_entities=[{"label": "mlflow:model_candidate"}],
        generated_entities=[{"label": f"mlflow:registered:{model_name}"}],
    )

    os.environ["MLFLOW_S3_ENDPOINT_URL"] = s3_endpoint
    os.environ["AWS_ACCESS_KEY_ID"] = aws_key
    os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret

    plain_uri = tracking_uri.replace("openlineage+", "")
    os.environ["MLFLOW_REGISTRY_URI"] = plain_uri

    ol_namespace = os.environ.get("OPENLINEAGE_NAMESPACE", "default")

    with kfp_lineage(
        "kfp-model_registration",
        inputs=[{"namespace": ol_namespace, "name": "model.model"}],
        outputs=[{"namespace": "mlflow", "name": f"models.{model_name}"}],
        url="http://marquez",
    ):
        result = json.loads(train_result_json)
        metrics = json.loads(metrics_json)

        if metrics["roc_auc"] < roc_auc_threshold:
            print(f"DS: model registration  ROC-AUC {metrics['roc_auc']:.4f} < {roc_auc_threshold} - skipping")
            out = json.dumps({"registered": False, "reason": "below_threshold"})
        else:
            mlflow.set_tracking_uri(tracking_uri)
            try:
                mv = mlflow.register_model(model_uri=result["model_uri"], name=model_name)
                client = MlflowClient()
                client.set_registered_model_alias(model_name, "champion", str(mv.version))
                print(f"DS: registered {model_name} v{mv.version} as alias 'champion'")
                out = json.dumps({
                    "registered": True,
                    "model_name": model_name,
                    "version": int(mv.version),
                    "alias": "champion",
                })
            except Exception as e:
                print(f"DS: model registration failed (non-fatal): {e}")
                out = json.dumps({"registered": False, "reason": str(e)[:200]})
    finalize_step_audit(
        step_name="ds_model_registration",
        context=sec,
        result_summary={"registered": json.loads(out).get("registered", False)},
    )
    return out


# =======================================================================
# Pipeline definition
# =======================================================================
@dsl.pipeline(
    name="Customer Churn ML Pipeline",
    description=(
        "End-to-end churn prediction pipeline. "
        "PLATFORM steps: Spark ETL, Feast apply & materialize (managed by infra). "
        "DS steps: data extraction, feature engineering, "
        "XGBoost training, evaluation, MLflow registration (owned by data scientists). "
        "OPENLINEAGE_NAMESPACE is injected by the Argo workflow controller. "
        "Security: PROV-O lineage, SPIFFE/SPIRE JWT authorization, OPA/Rego, "
        "signed transparency log (optional Rekor), EU date compliance metadata."
    ),
)
def customer_churn_pipeline(
    pg_url: str = "postgresql://feast:feast@postgres:5432/warehouse",
    feast_repo_path: str = "/app/src/feature_store",
    table_name: str = "customer_features",
    pg_host: str = "postgres",
    redis_host: str = "redis",
    tracking_uri: str = "openlineage+http://mlflow-server:5000",
    experiment_name: str = "customer_churn_lineage",
    model_name: str = "customer_churn_model",
    s3_endpoint: str = "http://mlflow-minio:9000",
    aws_key: str = "minioadmin",
    aws_secret: str = "minioadmin123",
    roc_auc_threshold: float = 0.70,
    # Security / compliance (SPIFFE, OPA, Rekor, EU metadata)
    agent_id: str = "spiffe://example.org/ns/churn/pipeline-agent",
    spiffe_dev_identity_json: str = '{"sub": "spiffe://example.org/ns/churn/pipeline-agent"}',
    opa_url: str = "http://opa:8181",
    opa_strict: bool = True,
    rekor_upload: bool = False,
    spiffe_required: bool = False,
    regional_policy: str = "NON_EU",
    llm_trace_id: str = "",
    llm_monitoring_tool: str = "langsmith",
    modify_original_date: bool = False,
    hours_deviation: float = 0.0,
):
    # -- PLATFORM STEPS (managed by infrastructure) ----------------------

    etl_task = platform_spark_etl(
        minio_endpoint="mlflow-minio:9000",
        pg_host=pg_host,
        pg_user="feast",
        pg_password="feast",
        pg_database="warehouse",
        warehouse_table=table_name,
        openlineage_url="http://marquez",
        aws_access_key=aws_key,
        aws_secret_key=aws_secret,
        agent_id=agent_id,
    )
    etl_task.set_caching_options(False)

    apply_task = platform_feast_apply(
        feast_repo_path=feast_repo_path,
        pg_host=pg_host,
        redis_host=redis_host,
        agent_id=agent_id,
    )
    apply_task.after(etl_task)
    apply_task.set_caching_options(False)

    materialize_task = platform_feast_materialize(
        feast_repo_path=feast_repo_path,
        pg_host=pg_host,
        redis_host=redis_host,
        apply_done=apply_task.output,
        agent_id=agent_id,
    )
    materialize_task.set_caching_options(False)

    # -- DS STEPS (owned by data scientists) ---------------------------

    extract_task = ds_data_extraction(
        pg_url=pg_url,
        feast_repo_path=feast_repo_path,
        table_name=table_name,
        pg_host=pg_host,
        redis_host=redis_host,
        materialize_done=materialize_task.output,
        agent_id=agent_id,
    )
    extract_task.set_caching_options(False)

    engineer_task = ds_feature_engineering(
        dataset=extract_task.outputs["output_path"],
        agent_id=agent_id,
        regional_policy=regional_policy,
        llm_trace_id=llm_trace_id,
        llm_monitoring_tool=llm_monitoring_tool,
        modify_original_date=modify_original_date,
        hours_deviation=hours_deviation,
    )
    engineer_task.set_caching_options(False)

    train_task = ds_model_training(
        dataset=engineer_task.outputs["output_path"],
        tracking_uri=tracking_uri,
        experiment_name=experiment_name,
        s3_endpoint=s3_endpoint,
        aws_key=aws_key,
        aws_secret=aws_secret,
        agent_id=agent_id,
    )
    train_task.set_caching_options(False)

    eval_task = ds_evaluation(
        train_result_json=train_task.output,
        agent_id=agent_id,
    )
    eval_task.set_caching_options(False)

    reg_task = ds_model_registration(
        train_result_json=train_task.output,
        metrics_json=eval_task.output,
        model_name=model_name,
        tracking_uri=tracking_uri,
        s3_endpoint=s3_endpoint,
        aws_key=aws_key,
        aws_secret=aws_secret,
        roc_auc_threshold=roc_auc_threshold,
        agent_id=agent_id,
    )
    reg_task.set_caching_options(False)

    # Inject parent run context for OpenLineage ParentRunFacet.
    # We use the Kubernetes downward API to get the real workflow name as the
    # parent run ID. In production OAI, the ds-pipelines-webhook should
    # inject these automatically at pod admission time.
    for task in [etl_task, apply_task, materialize_task, extract_task,
                 engineer_task, train_task, eval_task, reg_task]:
        kubernetes.use_field_path_as_env(
            task, "OPENLINEAGE_PARENT_RUN_ID",
            "metadata.labels['workflows.argoproj.io/workflow']",
        )
        task.set_env_variable(
            "OPENLINEAGE_PARENT_JOB_NAME", "customer-churn-ml-pipeline",
        )
        task.set_env_variable("SPIFFE_DEV_IDENTITY_JSON", spiffe_dev_identity_json)
        task.set_env_variable("OPA_URL", opa_url)
        task.set_env_variable("OPA_STRICT", "1" if opa_strict else "0")
        task.set_env_variable("REKOR_UPLOAD", "1" if rekor_upload else "0")
        task.set_env_variable("SPIFFE_REQUIRED", "1" if spiffe_required else "0")


# =======================================================================
# Compile to YAML
# =======================================================================
if __name__ == "__main__":
    compiler.Compiler().compile(
        pipeline_func=customer_churn_pipeline,
        package_path="customer_churn_pipeline.yaml",
    )
    print("Pipeline compiled -> customer_churn_pipeline.yaml")
