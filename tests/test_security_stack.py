"""
Regression tests for src/security: SPIFFE dev identity, guards, PROV-O, transparency, OPA client.

Run: PYTHONPATH=/app python -m unittest tests.test_security_stack -v
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch


class TestSpiffeDevIdentity(unittest.TestCase):
    def test_dev_identity_returns_sub(self) -> None:
        os.environ["SPIFFE_DEV_IDENTITY_JSON"] = (
            '{"sub": "spiffe://example.org/ns/churn/pipeline-agent"}'
        )
        os.environ.pop("SPIFFE_JWT_PATH", None)
        from src.security.spiffe_auth import get_workload_identity

        ident = get_workload_identity()
        self.assertEqual(ident.get("sub"), "spiffe://example.org/ns/churn/pipeline-agent")
        self.assertEqual(ident.get("source"), "SPIFFE_DEV_IDENTITY_JSON")


class TestProvO(unittest.TestCase):
    def test_writes_turtle(self) -> None:
        from src.security.prov_o_lineage import record_transformation_provenance

        with tempfile.TemporaryDirectory() as tmp:
            path = record_transformation_provenance(
                activity_id="test-act-1",
                activity_label="unit test activity",
                used_entities=[{"label": "s3://bucket/in.csv"}],
                generated_entities=[{"label": "postgres://h/db.t"}],
                responsible_agent_uri="urn:spiffe:test-agent",
                output_dir=tmp,
            )
            self.assertTrue(path.endswith(".ttl"))
            self.assertTrue(os.path.isfile(path))
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertIn("@prefix prov:", text)
            self.assertIn("unit test activity", text)


class TestTransparency(unittest.TestCase):
    def test_append_chain(self) -> None:
        from src.security.transparency import append_signed_audit_entry

        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "t.jsonl")
            os.environ["REKOR_UPLOAD"] = "0"
            e1 = append_signed_audit_entry({"type": "test", "n": 1}, log_path=log)
            e2 = append_signed_audit_entry({"type": "test", "n": 2}, log_path=log)
            self.assertIn("entry_hash", e1)
            self.assertIn("signature", e1)
            self.assertEqual(e2["prev_hash"], e1["entry_hash"])
            with open(log, encoding="utf-8") as f:
                lines = f.read().strip().split("\n")
            self.assertEqual(len(lines), 2)


class TestGuardsIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self._dir, ignore_errors=True))
        os.environ["PROV_OUTPUT_DIR"] = os.path.join(self._dir, "prov")
        os.environ["TRANSPARENCY_LOG_PATH"] = os.path.join(self._dir, "audit.jsonl")
        os.environ["REKOR_UPLOAD"] = "0"
        os.environ["SPIFFE_DEV_IDENTITY_JSON"] = json.dumps(
            {"sub": "spiffe://example.org/ns/churn/pipeline-agent"},
        )
        os.environ["SPIFFE_AGENT_MATCH"] = "1"

    def test_pipeline_step_guard_and_finalize(self) -> None:
        from src.security.guards import finalize_step_audit, pipeline_step_guard

        sec = pipeline_step_guard(
            step_name="test_step",
            activity_label="unittest",
            agent_id="spiffe://example.org/ns/churn/pipeline-agent",
            opa_input=None,
            used_entities=[{"label": "urn:ds:in"}],
            generated_entities=[{"label": "urn:ds:out"}],
        )
        self.assertIn("prov_o_path", sec)
        self.assertTrue(os.path.isfile(sec["prov_o_path"]))
        fin = finalize_step_audit(
            step_name="test_step",
            context=sec,
            result_summary={"ok": True},
        )
        self.assertIn("entry_hash", fin)


class TestOpaClient(unittest.TestCase):
    def test_evaluate_churn_policy_allows_when_opa_returns_true(self) -> None:
        from src.security import opa_client

        fake = {"result": True}
        with patch.object(opa_client, "evaluate_policy", return_value=fake):
            os.environ["OPA_STRICT"] = "1"
            self.assertTrue(
                opa_client.evaluate_churn_policy({"action": "x", "agent_id": "a"}),
            )

    def test_evaluate_churn_policy_strict_raises_on_network_error(self) -> None:
        from src.security import opa_client

        with patch.object(
            opa_client,
            "evaluate_policy",
            side_effect=ConnectionError("no OPA"),
        ):
            os.environ["OPA_STRICT"] = "1"
            with self.assertRaises(RuntimeError) as ctx:
                opa_client.evaluate_churn_policy({"x": 1})
            self.assertIn("OPA", str(ctx.exception))


class TestEuCompliance(unittest.TestCase):
    def test_reasoning_hash_stable(self) -> None:
        from src.security.eu_compliance import build_reasoning_hash

        h1 = build_reasoning_hash(
            llm_trace_id="t1",
            old_iso="2020-01-01",
            new_iso="2020-01-02",
            regional_policy="EU",
            agent_id="agent",
        )
        h2 = build_reasoning_hash(
            llm_trace_id="t1",
            old_iso="2020-01-01",
            new_iso="2020-01-02",
            regional_policy="EU",
            agent_id="agent",
        )
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)


if __name__ == "__main__":
    unittest.main()
