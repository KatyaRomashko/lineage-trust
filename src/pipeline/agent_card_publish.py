"""
Emit Agent Card JSON (and optional Cosign signature bundle) after model validation.

Writes ``/tmp/agent-card.json`` and, when ``cosign`` is on ``PATH`` and ``COSIGN_KEY`` is set,
``/tmp/agent-card.cosign.bundle``. Platform teams can wrap these artifacts in a ConfigMap
(e.g. ``oc create configmap model-agent-card --from-file=. -n fkm``) from a Tekton step.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from shutil import which

logger = logging.getLogger(__name__)


def build_card_payload() -> dict:
    return {
        "schema_version": "1.0",
        "data_quality_score": float(os.environ.get("AGENT_CARD_DATA_QUALITY_SCORE", "0.85")),
        "training_regime": os.environ.get("AGENT_CARD_TRAINING_REGIME", "supervised"),
        "compliance_zone": os.environ.get("FKM_REGION", os.environ.get("AGENT_CARD_COMPLIANCE_ZONE", "us")),
        "trust_level": os.environ.get("AGENT_CARD_TRUST_LEVEL", "standard"),
        "spiffe_trust_domain": os.environ.get("SPIFFE_TRUST_DOMAIN", ""),
    }


def publish_agent_card() -> None:
    if os.environ.get("AGENT_CARD_PUBLISH", "0").lower() not in ("1", "true", "yes"):
        return
    out = Path(os.environ.get("AGENT_CARD_JSON_PATH", "/tmp/agent-card.json"))
    payload = build_card_payload()
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Agent card written to %s", out)

    cosign_key = os.environ.get("COSIGN_KEY", "")
    if cosign_key and which("cosign"):
        bundle = Path(os.environ.get("AGENT_CARD_COSIGN_BUNDLE", "/tmp/agent-card.cosign.bundle"))
        r = subprocess.run(
            ["cosign", "sign-blob", "--key", cosign_key, "--bundle", str(bundle), str(out)],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            logger.info("Cosign bundle written to %s (Rekor upload if COSIGN_EXPERIMENTAL=1)", bundle)
        else:
            logger.warning("cosign sign-blob failed: %s", r.stderr)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    publish_agent_card()
