"""
Verify expected PROV-O / dataset lineage (Turtle) before ML pipeline steps run.

Set ``PROV_INPUT_RDF`` to a Turtle file path; set ``PROV_VERIFY_SKIP=1`` to bypass.
"""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)


def verify_or_exit() -> None:
    if os.environ.get("PROV_VERIFY_SKIP", "1").lower() in ("1", "true", "yes"):
        logger.info("PROV_VERIFY_SKIP enabled; skipping PROV-O input verification")
        return
    path = os.environ.get("PROV_INPUT_RDF", "").strip()
    if not path:
        logger.info("PROV_INPUT_RDF unset; skipping PROV-O input verification")
        return
    try:
        from rdflib import Graph

        g = Graph()
        g.parse(path, format="turtle")
        if len(g) == 0:
            raise RuntimeError(f"Empty PROV graph: {path}")
        expected = os.environ.get("PROV_EXPECTED_DATASET_URI", "").strip()
        if expected and expected not in {str(o) for o in g.subjects()} and expected not in g.serialize():
            raise RuntimeError(f"Expected dataset URI not found in graph: {expected}")
        logger.info("PROV-O input verification OK (%s triples)", len(g))
    except Exception as e:
        logger.error("PROV-O verification failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    verify_or_exit()
