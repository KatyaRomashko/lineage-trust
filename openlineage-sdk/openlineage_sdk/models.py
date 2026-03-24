"""Data models for the OpenLineage manual emission SDK."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Dataset:
    """Represents an OpenLineage dataset.

    Args:
        source: Where the data lives (e.g. "postgres://host:5432", "s3://bucket").
            Maps to the OpenLineage dataset namespace.
        name: The dataset name (e.g. "warehouse.customer_features", "path/to/file.csv").
        schema_fields: Optional list of (column_name, column_type) tuples.
        facets: Optional dict of additional OpenLineage dataset facets.
    """

    source: str
    name: str
    schema_fields: Optional[List[Tuple[str, str]]] = None
    facets: Dict[str, Any] = field(default_factory=dict)
