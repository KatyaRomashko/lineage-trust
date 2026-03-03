"""
STAGE 2.1  –  Feast entity, data source, and feature view definitions.

These objects are discovered by `feast apply` when it scans this repo path.
"""

from datetime import timedelta

from feast import Entity, FeatureView, Field, ValueType
from feast.infra.offline_stores.contrib.postgres_offline_store.postgres_source import (
    PostgreSQLSource,
)
from feast.types import Float32, Int32, String

# ── Entity ──────────────────────────────────────────────────────────────
customer = Entity(
    name="customer",
    join_keys=["entity_id"],
    value_type=ValueType.INT64,
    description="Unique customer identifier",
)

# ── Data Source (PostgreSQL warehouse table) ────────────────────────────
customer_source = PostgreSQLSource(
    name="customer_features_source",
    query="SELECT * FROM customer_features",
    timestamp_field="event_timestamp",
)

# ── Feature View ────────────────────────────────────────────────────────
customer_features_view = FeatureView(
    name="customer_features_view",
    entities=[customer],
    schema=[
        Field(name="tenure_months", dtype=Float32),
        Field(name="monthly_charges", dtype=Float32),
        Field(name="total_charges", dtype=Float32),
        Field(name="num_support_tickets", dtype=Int32),
        Field(name="contract_type", dtype=String),
        Field(name="internet_service", dtype=String),
        Field(name="payment_method", dtype=String),
    ],
    source=customer_source,
    ttl=timedelta(days=365),
    online=True,
)
