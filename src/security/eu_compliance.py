"""
Geographic compliance helpers for EU-regulated date handling.

For EU data subjects, any material change to the logical ``Date`` (here:
``Original_Date`` / ``event_timestamp``) must carry a ``reasoning_hash``
that binds the change to an LLM monitoring trace (LangSmith or Arize).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

MonitoringTool = Literal["langsmith", "arize"]


@dataclass(frozen=True)
class RegulatedDateObject:
    """Structured date object for audit under EU policy."""

    iso8601: str
    reasoning_hash: str
    llm_trace_id: str
    monitoring_tool: MonitoringTool

    def as_dict(self) -> dict[str, str]:
        return {
            "date_iso8601": self.iso8601,
            "reasoning_hash": self.reasoning_hash,
            "llm_trace_id": self.llm_trace_id,
            "llm_monitoring_tool": self.monitoring_tool,
        }


def build_reasoning_hash(
    *,
    llm_trace_id: str,
    old_iso: str,
    new_iso: str,
    regional_policy: str,
    agent_id: str,
) -> str:
    """
    Deterministic hash linking a date change to an LLM trace for monitoring tools.
    """
    material = "|".join(
        [llm_trace_id, old_iso, new_iso, regional_policy, agent_id],
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def eu_date_metadata_columns(
    *,
    regional_policy: str,
    llm_trace_id: str,
    monitoring_tool: str,
    old_iso: str,
    new_iso: str,
    agent_id: str,
) -> dict[str, str]:
    """
    Column-level metadata for parquet sidecar / DataFrame when policy is EU.
    Non-EU regions return empty dict (no extra compliance fields required).
    """
    if regional_policy.upper() != "EU":
        return {}
    if not llm_trace_id.strip():
        raise ValueError(
            "EU regional_policy requires llm_trace_id for Date changes "
            "(LangSmith / Arize trace binding).",
        )
    tool: MonitoringTool = "langsmith" if monitoring_tool.lower() != "arize" else "arize"
    rh = build_reasoning_hash(
        llm_trace_id=llm_trace_id,
        old_iso=old_iso,
        new_iso=new_iso,
        regional_policy=regional_policy,
        agent_id=agent_id,
    )
    return {
        "eu_date_reasoning_hash": rh,
        "eu_llm_trace_id": llm_trace_id,
        "eu_llm_monitoring_tool": tool,
    }
