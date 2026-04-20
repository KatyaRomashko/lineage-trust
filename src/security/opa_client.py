"""Open Policy Agent (OPA) client for Rego policy evaluation."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

DEFAULT_OPA_URL = os.environ.get("OPA_URL", "http://opa:8181")


def evaluate_policy(
    *,
    package_rule: str,
    input_payload: dict[str, Any],
    opa_url: str | None = None,
) -> dict[str, Any]:
    """
    POST ``input`` to OPA: ``/v1/data/<package_rule>``.

    ``package_rule`` uses slash notation, e.g. ``churn/allow`` for ``package churn``
    and rule ``allow``.
    """
    base = (opa_url or DEFAULT_OPA_URL).rstrip("/")
    url = f"{base}/v1/data/{package_rule}"
    with httpx.Client(timeout=30.0) as client:
        r = client.post(url, json={"input": input_payload})
        r.raise_for_status()
        return r.json()


def evaluate_churn_policy(input_payload: dict[str, Any]) -> bool:
    """
    Evaluate ``data.churn.allow`` (boolean). Missing OPA or network errors
    can be treated as deny or allow based on OPA_STRICT (default deny).
    """
    strict = os.environ.get("OPA_STRICT", "1") == "1"
    try:
        data = evaluate_policy(package_rule="churn/allow", input_payload=input_payload)
        result = data.get("result")
        if isinstance(result, bool):
            return result
        return bool(result)
    except Exception as e:
        if strict:
            raise RuntimeError(f"OPA policy evaluation failed: {e}") from e
        return False


def evaluate_original_date_policy(
    *,
    agent_id: str,
    regional_policy: str,
    hours_deviation: float,
    opa_url: str | None = None,
) -> bool:
    """Convenience wrapper for Original_Date modification rules."""
    payload = {
        "agent_id": agent_id,
        "regional_policy": regional_policy,
        "hours_deviation": hours_deviation,
        "action": "modify_original_date",
    }
    return evaluate_churn_policy(payload)


def opa_decision_json(input_payload: dict[str, Any]) -> str:
    """Return full OPA JSON response as string for audit storage."""
    try:
        data = evaluate_policy(package_rule="churn/allow", input_payload=input_payload)
        return json.dumps(data, sort_keys=True)
    except Exception as e:
        return json.dumps({"error": str(e)})
