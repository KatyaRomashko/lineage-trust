"""Smoke tests for PROV-O translation."""
from __future__ import annotations

import unittest

from src.prov_translator import graph_to_turtle, openlineage_event_to_graph


class ProvTranslatorTests(unittest.TestCase):
    def test_minimal_event(self) -> None:
        event = {
            "run": {"runId": "abc-123"},
            "job": {"name": "train"},
            "eventTime": "2026-01-01T00:00:00Z",
            "inputs": [{"name": "ds1"}],
            "outputs": [{"name": "model1"}],
        }
        g = openlineage_event_to_graph(event)
        ttl = graph_to_turtle(g)
        self.assertIn("abc-123", ttl)
        self.assertIn("prov:Activity", ttl)


if __name__ == "__main__":
    unittest.main()
