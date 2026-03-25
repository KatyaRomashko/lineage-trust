"""
KFP-specific OpenLineage facet builders.

Provides facets that identify KFP component runs and link them to their
parent pipeline run, enabling hierarchical lineage in Marquez.
"""

import os
from typing import Any, Dict, Optional

_PRODUCER = "https://github.com/rh-waterford-et/openlineage-oai/kfp-adapter"


def build_parent_run_facet(
    pipeline_run_id: Optional[str] = None,
    pipeline_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a ParentRunFacet linking a component run to its pipeline run.

    Reads KFP_RUN_ID and KFP_PIPELINE_NAME from the environment if not
    provided explicitly.  Returns an empty dict if no parent context is
    available (the caller should omit the facet in that case).
    """
    run_id = pipeline_run_id or os.environ.get("KFP_RUN_ID", "")
    name = pipeline_name or os.environ.get("KFP_PIPELINE_NAME", "")

    if not run_id:
        return {}

    return {
        "_producer": _PRODUCER,
        "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/ParentRunFacet.json",
        "run": {"runId": run_id},
        "job": {
            "namespace": "kfp://cluster",
            "name": name or "unknown-pipeline",
        },
    }


def build_job_type_facet() -> Dict[str, Any]:
    """Build a JobTypeJobFacet marking this job as a KFP component."""
    return {
        "_producer": _PRODUCER,
        "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/JobTypeJobFacet.json",
        "jobType": "KFP_COMPONENT",
        "integration": "KFP",
        "processingType": "BATCH",
    }
