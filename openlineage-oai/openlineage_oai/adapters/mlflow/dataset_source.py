"""
Custom MLflow DatasetSource that wraps a plain URI string.

This allows passing an arbitrary URI (e.g. a KFP artifact S3 path) as the
``source`` argument to ``mlflow.data.from_pandas()``, so that the MLflow
tracking store (and our OpenLineage adapter) can extract the upstream
dataset identity for lineage.
"""

from __future__ import annotations

from typing import Any

from mlflow.data.dataset_source import DatasetSource


class URIDatasetSource(DatasetSource):
    """A DatasetSource backed by a single URI string."""

    def __init__(self, uri: str) -> None:
        self._uri = uri

    @staticmethod
    def _get_source_type() -> str:
        return "uri"

    def load(self, dst_path: str | None = None) -> str:
        return self._uri

    @staticmethod
    def _can_resolve(raw_source: Any) -> bool:
        return isinstance(raw_source, str)

    @classmethod
    def _resolve(cls, raw_source: str) -> URIDatasetSource:
        return cls(raw_source)

    def to_dict(self) -> dict[str, Any]:
        return {"uri": self._uri}

    @classmethod
    def from_dict(cls, source_dict: dict[str, Any]) -> URIDatasetSource:
        return cls(uri=source_dict["uri"])
