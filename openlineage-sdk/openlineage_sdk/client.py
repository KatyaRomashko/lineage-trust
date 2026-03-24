"""OpenLineage client for manual event emission."""

import functools
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import requests

from openlineage_sdk.models import Dataset

logger = logging.getLogger(__name__)

_PRODUCER = "https://github.com/rh-waterford-et/practice-mlops/openlineage-sdk"
_SCHEMA_URL = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent"


class OLClient:
    """Client for manually emitting OpenLineage events.

    Reads configuration from environment variables by default:
        - OPENLINEAGE_URL: The OpenLineage API endpoint (e.g. "http://marquez")
        - OPENLINEAGE_NAMESPACE: The namespace for jobs (e.g. "lineage")
        - DATASET_REGISTRY_URL: The Dataset Registry endpoint (optional)

    All can be overridden via constructor arguments.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        namespace: Optional[str] = None,
        registry_url: Optional[str] = None,
    ):
        self._url = url or os.environ.get("OPENLINEAGE_URL", "")
        self._namespace = namespace or os.environ.get("OPENLINEAGE_NAMESPACE", "default")
        self._registry_url = (
            registry_url or os.environ.get("DATASET_REGISTRY_URL", "")
        ).rstrip("/")

        if not self._url:
            logger.warning(
                "OPENLINEAGE_URL not set and no url provided; events will not be emitted"
            )

    @property
    def is_configured(self) -> bool:
        return bool(self._url)

    # -- public API --

    def dataset(self, name: str) -> Dataset:
        """Resolve a dataset from the Dataset Registry by its human-readable name.

        Returns a Dataset with ``source`` and ``name`` populated from the
        registry's ``ol_namespace`` and ``ol_name`` fields.  Schema fields are
        carried across when present in the registry entry.

        Requires ``registry_url`` (or the ``DATASET_REGISTRY_URL`` env var).
        """
        if not self._registry_url:
            raise RuntimeError(
                "Registry URL not configured. Set DATASET_REGISTRY_URL or "
                "pass registry_url to OLClient."
            )
        resp = requests.get(
            f"{self._registry_url}/api/v1/datasets/lookup",
            params={"name": name},
            timeout=10,
        )
        if resp.status_code == 404:
            raise LookupError(f"Dataset '{name}' not found in registry")
        resp.raise_for_status()
        data = resp.json()
        schema = None
        if data.get("schema_fields"):
            schema = [(f["name"], f["type"]) for f in data["schema_fields"]]
        return Dataset(
            source=data["ol_namespace"],
            name=data["ol_name"],
            schema_fields=schema,
        )

    def emit_job(
        self,
        job_name: str,
        inputs: Optional[List[Dataset]] = None,
        outputs: Optional[List[Dataset]] = None,
    ) -> str:
        """Emit a single COMPLETE event for a job (fire-and-forget).

        Use this when you just want to record that a job consumed inputs and
        produced outputs without tracking duration or lifecycle.

        Returns:
            The generated run_id.
        """
        run_id = str(uuid.uuid4())
        self._emit(
            event_type="COMPLETE",
            run_id=run_id,
            job_name=job_name,
            inputs=inputs or [],
            outputs=outputs or [],
        )
        return run_id

    def track(
        self,
        job_name: str,
        inputs: Optional[List[Dataset]] = None,
        outputs: Optional[List[Dataset]] = None,
    ) -> "_TrackedRun":
        """Track a job with automatic START/COMPLETE/FAIL lifecycle events.

        Can be used as a decorator or context manager.

        As a decorator::

            @client.track("my_job", inputs=[input_ds], outputs=[output_ds])
            def my_step():
                ...

        As a context manager::

            with client.track("my_job", inputs=[input_ds]) as run:
                result = do_work()
                run.add_output(Dataset(source="s3://bucket", name=result.path))
        """
        return _TrackedRun(self, job_name, inputs or [], outputs or [])

    # -- internal --

    def _emit_start(
        self,
        job_name: str,
        inputs: Optional[List[Dataset]] = None,
    ) -> str:
        run_id = str(uuid.uuid4())
        self._emit(
            event_type="START",
            run_id=run_id,
            job_name=job_name,
            inputs=inputs or [],
            outputs=[],
        )
        return run_id

    def _emit_complete(
        self,
        run_id: str,
        job_name: str,
        outputs: Optional[List[Dataset]] = None,
    ) -> None:
        self._emit(
            event_type="COMPLETE",
            run_id=run_id,
            job_name=job_name,
            inputs=[],
            outputs=outputs or [],
        )

    def _emit_fail(
        self,
        run_id: str,
        job_name: str,
        error: Optional[str] = None,
    ) -> None:
        run_facets: Dict[str, Any] = {}
        if error:
            run_facets["errorMessage"] = {
                "_producer": _PRODUCER,
                "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/ErrorMessageRunFacet.json",
                "message": error,
                "programmingLanguage": "python",
            }

        self._emit(
            event_type="FAIL",
            run_id=run_id,
            job_name=job_name,
            inputs=[],
            outputs=[],
            run_facets=run_facets,
        )

    def _emit(
        self,
        event_type: str,
        run_id: str,
        job_name: str,
        inputs: List[Dataset],
        outputs: List[Dataset],
        run_facets: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.is_configured:
            return

        event = {
            "eventType": event_type,
            "eventTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "producer": _PRODUCER,
            "schemaURL": _SCHEMA_URL,
            "run": {
                "runId": run_id,
                "facets": run_facets or {},
            },
            "job": {
                "namespace": self._namespace,
                "name": job_name,
                "facets": {},
            },
            "inputs": [self._dataset_to_dict(ds) for ds in inputs],
            "outputs": [self._dataset_to_dict(ds) for ds in outputs],
        }

        try:
            resp = requests.post(
                f"{self._url}/api/v1/lineage",
                json=event,
                timeout=10,
            )
            if resp.status_code >= 300:
                logger.warning("OpenLineage emit failed (%s): %s", resp.status_code, resp.text)
            else:
                logger.debug("OpenLineage %s event emitted for %s (run=%s)", event_type, job_name, run_id)
        except Exception as e:
            logger.warning("Failed to emit OpenLineage event: %s", e)

    @staticmethod
    def _dataset_to_dict(ds: Dataset) -> Dict[str, Any]:
        facets: Dict[str, Any] = dict(ds.facets) if ds.facets else {}

        if ds.schema_fields:
            facets["schema"] = {
                "_producer": _PRODUCER,
                "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/SchemaDatasetFacet.json",
                "fields": [
                    {"name": name, "type": col_type}
                    for name, col_type in ds.schema_fields
                ],
            }

        return {
            "namespace": ds.source,
            "name": ds.name,
            "facets": facets,
        }


class _TrackedRun:
    """Handles automatic START/COMPLETE/FAIL lifecycle for a job.

    Supports both decorator and context manager usage.
    """

    def __init__(
        self,
        client: OLClient,
        job_name: str,
        inputs: List[Dataset],
        outputs: List[Dataset],
    ):
        self._client = client
        self._job_name = job_name
        self._inputs = list(inputs)
        self._outputs = list(outputs)
        self._run_id: Optional[str] = None

    def add_input(self, dataset: Dataset) -> None:
        """Declare an additional input dataset mid-run."""
        self._inputs.append(dataset)

    def add_output(self, dataset: Dataset) -> None:
        """Declare an additional output dataset mid-run."""
        self._outputs.append(dataset)

    def __enter__(self) -> "_TrackedRun":
        self._run_id = self._client._emit_start(self._job_name, inputs=self._inputs)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            self._client._emit_fail(self._run_id, self._job_name, error=str(exc_val))
        else:
            self._client._emit_complete(self._run_id, self._job_name, outputs=self._outputs)

    def __call__(self, fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with self:
                return fn(*args, **kwargs)
        return wrapper
