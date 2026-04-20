"""
Orchestration: SPIFFE authorization, OPA, PROV-O, and transparency log per step.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from src.security.opa_client import evaluate_churn_policy, opa_decision_json
from src.security.prov_o_lineage import record_transformation_provenance
from src.security.spiffe_auth import get_workload_identity, require_spiffe_identity
from src.security.transparency import append_signed_audit_entry


def pipeline_step_guard(
    *,
    step_name: str,
    activity_label: str,
    agent_id: str | None = None,
    opa_input: dict[str, Any] | None = None,
    used_entities: list[dict[str, str]] | None = None,
    generated_entities: list[dict[str, str]] | None = None,
    extra_prov: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Run before a pipeline action:

    1. Resolve SPIFFE workload identity (must match ``agent_id`` when set).
    2. Optionally evaluate OPA (``churn.allow``).
    3. Emit PROV-O Turtle for the step.
    4. Append a signed transparency-log entry (Rekor witness when configured).
    """
    ident = get_workload_identity()
    spiffe_id = ident.get("sub") or ident.get("spiffe_id")
    if not spiffe_id:
        spiffe_id = require_spiffe_identity()
    effective_agent = agent_id or spiffe_id

    if (
        os.environ.get("SPIFFE_AGENT_MATCH", "1") == "1"
        and agent_id
        and spiffe_id != agent_id
        and ident.get("source") != "SPIFFE_DEV_IDENTITY_JSON"
    ):
        raise PermissionError(
            f"agent_id {agent_id!r} does not match SPIFFE ID {spiffe_id!r}",
        )

    opa_result: bool | str | None = "skipped"
    opa_json = "{}"
    if opa_input is not None:
        opa_result = evaluate_churn_policy({**opa_input, "agent_id": effective_agent})
        opa_json = opa_decision_json({**opa_input, "agent_id": effective_agent})
        if not opa_result:
            raise PermissionError(f"OPA denied action for step {step_name}: input={opa_input!r}")

    act_id = str(uuid.uuid4())
    agent_uri = f"urn:spiffe:{effective_agent}"
    owner_uri = os.environ.get("DATA_OWNER_URI", agent_uri)

    prov_path = record_transformation_provenance(
        activity_id=act_id,
        activity_label=activity_label,
        used_entities=used_entities or [],
        generated_entities=generated_entities or [],
        responsible_agent_uri=agent_uri,
        data_owner_uri=owner_uri,
        extra_attributes={
            "step_name": step_name,
            **(extra_prov or {}),
        },
    )

    audit = append_signed_audit_entry(
        {
            "type": "pipeline_step_start",
            "step_name": step_name,
            "activity_label": activity_label,
            "agent_id": effective_agent,
            "spiffe_id": spiffe_id,
            "opa_allowed": opa_result,
            "opa_input": opa_input,
            "opa_response": opa_json,
            "prov_o_path": prov_path,
        },
    )

    return {
        "activity_id": act_id,
        "spiffe_id": spiffe_id,
        "agent_id": effective_agent,
        "prov_o_path": prov_path,
        "audit_entry_id": audit.get("id"),
        "rekor_uuid": audit.get("rekor_uuid"),
    }


def finalize_step_audit(
    *,
    step_name: str,
    context: dict[str, Any],
    result_summary: dict[str, Any],
) -> dict[str, Any]:
    """Append a completion record chained to the same transparency log."""
    return append_signed_audit_entry(
        {
            "type": "pipeline_step_end",
            "step_name": step_name,
            "context": context,
            "result": result_summary,
        },
    )
