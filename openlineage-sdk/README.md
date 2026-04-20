# OpenLineage SDK

Lightweight Python SDK for manually emitting [OpenLineage](https://openlineage.io/) events.
Use this when your pipeline step doesn't have native OpenLineage integration
(e.g. no Spark listener, no Feast emitter, no MLflow adapter).

## Installation

```bash
pip install ./openlineage-sdk
```

Or use the pre-built image:

```
quay.io/rh_et_wd/fkm/sdk:latest
```

## Configuration

The SDK reads from environment variables by default:

| Variable | Description | Required |
|---|---|---|
| `OPENLINEAGE_URL` | OpenLineage API endpoint (e.g. `http://marquez`) | Yes |
| `OPENLINEAGE_NAMESPACE` | Namespace for jobs (e.g. `fkm`) | No (defaults to `default`) |
| `DATASET_REGISTRY_URL` | Dataset Registry endpoint (e.g. `http://dataset-registry-api:8080`) | Only for `client.dataset()` |

All can be overridden via constructor arguments:

```python
client = OLClient(
    url="http://marquez:5000",
    namespace="my-namespace",
    registry_url="http://dataset-registry-api:8080",
)
```

## API

The public API has three methods:

| Method | When to use |
|---|---|
| `emit_job()` | Fire-and-forget -- record that a job ran with given inputs/outputs |
| `track()` | Lifecycle tracking -- automatic START/COMPLETE/FAIL events (decorator or context manager) |
| `dataset()` | Resolve a dataset by name from the Dataset Registry |

## Usage

### Quick start

```python
from openlineage_sdk import OLClient, Dataset

client = OLClient()
```

### `emit_job` -- Fire-and-forget

Record that a job consumed inputs and produced outputs in a single call.
No wrapping or lifecycle management needed:

```python
client.emit_job(
    "data_validation",
    inputs=[Dataset(source="postgres://postgres:5432", name="warehouse.raw_customers")],
    outputs=[Dataset(source="postgres://postgres:5432", name="warehouse.validated_customers")],
)
```

### `track` -- Decorator

Wrap a function with automatic START, COMPLETE, and FAIL events.
START is emitted before the function runs, COMPLETE on success, FAIL on exception:

```python
input_ds = Dataset(source="s3://raw-data", name="customers.csv")
output_ds = Dataset(source="postgres://postgres:5432", name="warehouse.customer_features")

@client.track("etl_job", inputs=[input_ds], outputs=[output_ds])
def run_etl():
    extract()
    transform()
    load()

run_etl()
```

### `track` -- Context manager

Use when outputs aren't known upfront, or when you need to add datasets mid-run:

```python
input_ds = Dataset(source="s3://raw-data", name="customers.csv")

with client.track("etl_job", inputs=[input_ds]) as run:
    result = do_work()
    run.add_output(Dataset(source="s3://models", name=result.model_path))
```

If an exception is raised inside the `with` block, a FAIL event is emitted automatically.

### `dataset` -- Resolve from the Dataset Registry

Look up a dataset by its human-readable name in the Dataset Registry instead of
hardcoding source URIs. The registry's `ol_namespace` and `ol_name` fields map to
the SDK's `source` and `name`:

```python
client = OLClient(registry_url="http://dataset-registry-api:8080")

features = client.dataset("Customer Features")
predictions = client.dataset("Churn Predictions")

client.emit_job("model_training", inputs=[features], outputs=[predictions])
```

Works with `track` too:

```python
@client.track("model_training", inputs=[client.dataset("Customer Features")])
def train():
    ...
```

### Defining datasets manually

When not using the registry, create `Dataset` objects directly.
`source` is the OpenLineage namespace (where the data lives),
`name` is the dataset name within that source:

```python
ds = Dataset(
    source="postgres://postgres:5432",
    name="warehouse.customer_features",
)
```

Optionally attach column-level schema:

```python
ds = Dataset(
    source="postgres://postgres:5432",
    name="warehouse.customer_features",
    schema_fields=[
        ("entity_id", "INTEGER"),
        ("tenure_months", "FLOAT"),
        ("monthly_charges", "FLOAT"),
        ("churn", "BOOLEAN"),
    ],
)
```

## Examples

### Full pipeline step with registry

```python
from openlineage_sdk import OLClient

client = OLClient(registry_url="http://dataset-registry-api:8080")

@client.track(
    "feature_engineering",
    inputs=[client.dataset("Raw Customers")],
    outputs=[client.dataset("Customer Features")],
)
def feature_engineering():
    df = load_from_postgres()
    features = compute_features(df)
    save_to_postgres(features)

feature_engineering()
```

### Dynamic outputs with context manager

```python
from openlineage_sdk import OLClient, Dataset

client = OLClient()

with client.track("model_export", inputs=[client.dataset("Customer Features")]) as run:
    model = train_model()
    path = export_model(model)
    run.add_output(Dataset(source="s3://models", name=path))
```

### Simple one-liner for a notebook cell

```python
from openlineage_sdk import OLClient, Dataset

OLClient().emit_job(
    "exploratory_analysis",
    inputs=[Dataset(source="postgres://postgres:5432", name="warehouse.customer_features")],
)
```
