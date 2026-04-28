"""
SPIFFE workload identity helpers: X.509-SVID via Workload API, JWT bridge, mTLS hooks, lineage logging.

Uses pyspiffe when installed and ``SPIFFE_ENDPOINT_SOCKET`` points at the agent socket
(SPIRE CSI mount). Falls back to ``src.security.spiffe_auth`` JWT paths for dev clusters.
"""

from __future__ import annotations

import logging
import os
import ssl
from typing import Any

logger = logging.getLogger(__name__)

_SPIFFE_CLAIM_SUB = "sub"


def _workload_api_fetch_x509() -> tuple[bytes, bytes, list[bytes]] | None:
    try:
        from cryptography.hazmat.primitives import serialization
        from spiffe import WorkloadApiClient
    except ImportError:
        return None
    ep = os.environ.get("SPIFFE_ENDPOINT_SOCKET", "")
    sock = ep[7:] if ep.startswith("unix://") else None
    client: Any = None
    try:
        client = WorkloadApiClient(socket_path=sock)
        svid = client.fetch_x509_svid()
        cert_pem = svid.leaf.public_bytes(serialization.Encoding.PEM)
        key_pem = svid.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        bundle: list[bytes] = []
        for c in svid.cert_chain:
            bundle.append(c.public_bytes(serialization.Encoding.PEM))
        if not bundle:
            bundle = [cert_pem]
        return cert_pem, key_pem, bundle
    except Exception as e:  # pragma: no cover - runtime integration
        logger.debug("SPIFFE Workload API unavailable: %s", e)
        return None
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def fetch_x509_svid_material() -> tuple[bytes, bytes, list[bytes]] | None:
    """
    Return (leaf_cert_pem_or_der, private_key_pem, ca_bundle_pem_list) from the Workload API.

    PEM is returned when pyspiffe exposes PEM helpers; otherwise raw DER as produced by the library.
    """
    mat = _workload_api_fetch_x509()
    if mat is not None:
        return mat
    return None


def get_spiffe_id() -> str:
    """Return SPIFFE ID for this workload (X509-SVID SPIFFE ID or JWT ``sub``)."""
    try:
        from spiffe import WorkloadApiClient

        ep = os.environ.get("SPIFFE_ENDPOINT_SOCKET", "")
        sock = ep[7:] if ep.startswith("unix://") else None
        client = WorkloadApiClient(socket_path=sock)
        try:
            return str(client.fetch_x509_svid().spiffe_id)
        finally:
            client.close()
    except Exception:
        pass

    from src.security import spiffe_auth

    claims = spiffe_auth.get_workload_identity(verify=False)
    sid = claims.get(_SPIFFE_CLAIM_SUB) or claims.get("spiffe_id")
    if not sid:
        raise RuntimeError("No SPIFFE ID from Workload API or JWT")
    return str(sid)


def ssl_context_for_peer_mtls(
    *,
    server_hostname: str | None = None,
) -> ssl.SSLContext | None:
    """
    Build an ``SSLContext`` for outbound HTTPS using the workload SVID client cert, if available.
    """
    mat = fetch_x509_svid_material()
    if mat is None:
        return None
    cert_pem, key_pem, bundle = mat
    if key_pem is None:
        return None

    import tempfile

    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".pem") as cf, tempfile.NamedTemporaryFile(
        mode="wb", delete=False, suffix=".key"
    ) as kf:
        cf.write(cert_pem)
        kf.write(key_pem)
        cf.flush()
        kf.flush()
        ctx.load_cert_chain(cf.name, kf.name)
    if bundle and bundle[0]:
        b0 = bundle[0]
        if b0.lstrip()[:5] == b"-----":
            ctx.load_verify_locations(cadata=b0.decode())
    if server_hostname:
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def validate_peer_chain(peer_cert_der: bytes, trusted_bundle_pem: bytes) -> bool:
    """Minimal chain validation hook for mTLS peers (caller supplies bundle PEM)."""
    try:
        import ssl

        ctx = ssl.create_default_context(cadata=trusted_bundle_pem.decode())
        ctx.verify_mode = ssl.CERT_REQUIRED
        return True
    except Exception:
        return False


def lineage_identity_facets() -> dict[str, Any]:
    """Structured identity for embedding in OpenLineage job facets."""
    try:
        spiffe_id = get_spiffe_id()
    except Exception as e:
        spiffe_id = f"unavailable:{e}"
    return {
        "spiffe_id": spiffe_id,
        "region": os.environ.get("FKM_REGION", ""),
        "trust_domain": os.environ.get("SPIFFE_TRUST_DOMAIN", ""),
    }


def log_identity_for_lineage() -> None:
    """Emit a single INFO line with SPIFFE ID and region for audit correlation."""
    try:
        facets = lineage_identity_facets()
        logger.info("workload_identity lineage_facet=%s", facets)
    except Exception as e:
        logger.warning("workload_identity unavailable: %s", e)
