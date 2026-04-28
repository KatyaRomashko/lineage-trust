"""
Translate OpenLineage-style run events (JSON dicts) into PROV-O RDF (Turtle).

Intended for Marquez / OpenLineage consumers: map run, job, dataset nodes to
``prov:Activity``, ``prov:Entity``, ``prov:wasGeneratedBy``, etc.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Mapping

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import PROV, RDF, RDFS

logger = logging.getLogger(__name__)

CUSTOM = Namespace("https://fkm.example/trust/")


def openlineage_event_to_graph(event: Mapping[str, Any]) -> Graph:
    """Build an in-memory RDF graph from one OpenLineage event dict."""
    g = Graph()
    g.bind("prov", PROV)
    g.bind("rdfs", RDFS)
    g.bind("fkm", CUSTOM)

    run_id = str(event.get("run", {}).get("runId") or event.get("runId") or uuid.uuid4())
    job = event.get("job") or event.get("jobName") or {}
    job_name = str(job.get("name") or event.get("jobName") or "job")
    namespace = str(event.get("producer") or "openlineage")

    act = URIRef(f"urn:uuid:{run_id}")
    g.add((act, RDF.type, PROV.Activity))
    et = event.get("eventTime")
    if et:
        g.add((act, PROV.startedAtTime, Literal(str(et))))
    g.add((act, CUSTOM.jobName, Literal(job_name)))
    g.add((act, CUSTOM.namespace, Literal(namespace)))

    inputs = event.get("inputs") or []
    for i, inp in enumerate(inputs):
        if not isinstance(inp, dict):
            continue
        fac = inp.get("facets") or {}
        ds = inp.get("name") or fac.get("schema", {}).get("fields", [{}])[0]
        ent = URIRef(f"urn:dataset:{run_id}:{i}")
        g.add((ent, RDF.type, PROV.Entity))
        g.add((ent, RDFS.label, Literal(str(ds))))
        g.add((act, PROV.used, ent))

    outputs = event.get("outputs") or []
    for j, out in enumerate(outputs):
        if not isinstance(out, dict):
            continue
        name = out.get("name") or f"output-{j}"
        gen = BNode()
        g.add((gen, RDF.type, PROV.Generation))
        ent_o = URIRef(f"urn:artifact:{run_id}:{j}")
        g.add((ent_o, RDF.type, PROV.Entity))
        g.add((ent_o, RDFS.label, Literal(str(name))))
        g.add((gen, PROV.entity, ent_o))
        g.add((gen, PROV.activity, act))

    return g


def graph_to_turtle(g: Graph) -> str:
    return g.serialize(format="turtle")


def store_graph_fuseki(g: Graph, update_url: str | None = None) -> bool:
    """
    POST Turtle to a SPARQL 1.1 Graph Store (e.g. Apache Jena Fuseki ``/data?graph=``).
    Set ``FUSEKI_UPDATE_URL`` to enable (e.g. ``http://fuseki:3030/fkm/data``).
    """
    url = update_url or os.environ.get("FUSEKI_UPDATE_URL")
    if not url:
        logger.debug("FUSEKI_UPDATE_URL unset; skip triplestore upload")
        return False
    try:
        import urllib.error
        import urllib.request

        body = graph_to_turtle(g).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "text/turtle")
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return 200 <= resp.status < 300
    except Exception as e:
        logger.warning("Fuseki upload failed: %s", e)
        return False


def translate_file(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        event = json.load(f)
    g = openlineage_event_to_graph(event)
    return graph_to_turtle(g)
