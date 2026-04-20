"""
W3C PROV-O (Provenance Ontology) serialization for data lineage and ownership.

Uses RDFLib to emit Turtle graphs linking activities, entities, and agents.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import PROV, RDF, RDFS, XSD

DCTERMS = Namespace("http://purl.org/dc/terms/")
CUSTOM = Namespace("urn:churn-mlops:security#")


def _now_literal() -> Literal:
    return Literal(datetime.now(timezone.utc).isoformat(), datatype=XSD.dateTime)


def record_transformation_provenance(
    *,
    activity_id: str,
    activity_label: str,
    used_entities: list[dict[str, str]],
    generated_entities: list[dict[str, str]],
    responsible_agent_uri: str,
    data_owner_uri: str | None = None,
    extra_attributes: dict[str, Any] | None = None,
    output_dir: str | None = None,
) -> str:
    """
    Build a PROV-O graph for one transformation and write Turtle to disk.

    Each entity dict supports keys: ``uri`` (optional), ``label``.

    Returns path to the written ``.ttl`` file.
    """
    g = Graph()
    g.bind("prov", PROV)
    g.bind("dct", DCTERMS)
    g.bind("churn", CUSTOM)

    act = URIRef(responsible_agent_uri)
    g.add((act, RDF.type, PROV.Agent))

    owner = URIRef(data_owner_uri) if data_owner_uri else act
    g.add((owner, RDF.type, PROV.Agent))

    act_uri = URIRef(f"urn:uuid:{activity_id}")
    g.add((act_uri, RDF.type, PROV.Activity))
    g.add((act_uri, RDFS.label, Literal(activity_label)))
    g.add((act_uri, PROV.startedAtTime, _now_literal()))
    g.add((act_uri, PROV.wasAssociatedWith, act))
    if data_owner_uri:
        g.add((act_uri, CUSTOM.attributedDataOwner, owner))

    for u in used_entities:
        eid = u.get("uri") or f"urn:entity:{uuid4()}"
        ent = URIRef(eid)
        g.add((ent, RDF.type, PROV.Entity))
        g.add((ent, RDFS.label, Literal(u.get("label", ""))))
        g.add((act_uri, PROV.used, ent))

    for gen in generated_entities:
        eid = gen.get("uri") or f"urn:entity:{uuid4()}"
        ent = URIRef(eid)
        g.add((ent, RDF.type, PROV.Entity))
        g.add((ent, RDFS.label, Literal(gen.get("label", ""))))
        g.add((ent, PROV.wasGeneratedBy, act_uri))
        g.add((ent, PROV.wasAttributedTo, owner))

    if extra_attributes:
        for k, v in extra_attributes.items():
            g.add((act_uri, CUSTOM[k.replace(" ", "_")], Literal(str(v))))

    ttl = g.serialize(format="turtle")
    out = output_dir or os.environ.get("PROV_OUTPUT_DIR", "/tmp/prov-o")
    Path(out).mkdir(parents=True, exist_ok=True)
    fname = f"{activity_id}_{hashlib.sha256(ttl.encode()).hexdigest()[:12]}.ttl"
    path = Path(out) / fname
    path.write_text(ttl, encoding="utf-8")
    return str(path)
