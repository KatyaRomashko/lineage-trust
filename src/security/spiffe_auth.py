"""
SPIFFE/SPIRE workload identity for agent authorization.

In Kubernetes, mount the SPIFFE JWT via the SPIRE agent CSI driver or
projected service account token. Set SPIFFE_JWT_PATH to the token file path.

Local development: set SPIFFE_JWT_PATH to a file containing a JWT, or
SPIFFE_DEV_IDENTITY_JSON for a fixed identity without a real SVID.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

import jwt

# SPIFFE ID claim per JWT-SVID: https://github.com/spiffe/spiffe/blob/main/standards/JWT-SVID.md
SPIFFE_CLAIM = "sub"


def _dev_identity() -> Mapping[str, Any] | None:
    raw = os.environ.get("SPIFFE_DEV_IDENTITY_JSON")
    if not raw:
        return None
    return json.loads(raw)


def _read_jwt_string() -> str | None:
    path = os.environ.get("SPIFFE_JWT_PATH", "/var/run/secrets/tokens/spiffe-token")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    direct = os.environ.get("SPIFFE_JWT")
    if direct:
        return direct.strip()
    return None


def get_workload_identity(verify: bool | None = None) -> dict[str, Any]:
    """
    Return decoded JWT claims for the workload SVID (SPIFFE JWT-SVID).

    If SPIFFE_DEV_IDENTITY_JSON is set, returns that object augmented with
    ``verified: False`` (development only).

    When verify is True (or SPIFFE_VERIFY_JWT is ``1``), validates signature
    using PyJWT with the key from SPIFFE_JWT_JWKS_URL / SPIFFE_JWT_SECRET
    when configured; otherwise decodes without verification and sets
    ``verified: False`` (not for production).
    """
    if verify is None:
        verify = os.environ.get("SPIFFE_VERIFY_JWT", "").lower() in ("1", "true", "yes")

    dev = _dev_identity()
    if dev is not None:
        return {**dict(dev), "verified": False, "source": "SPIFFE_DEV_IDENTITY_JSON"}

    token = _read_jwt_string()
    if not token:
        if os.environ.get("SPIFFE_REQUIRED", "1") == "0":
            return {
                "sub": os.environ.get("FALLBACK_AGENT_ID", "unauthenticated-local"),
                "verified": False,
                "source": "fallback",
            }
        raise RuntimeError(
            "SPIFFE JWT not found: set SPIFFE_JWT_PATH, SPIFFE_JWT, or "
            "SPIFFE_DEV_IDENTITY_JSON (dev), or SPIFFE_REQUIRED=0 with FALLBACK_AGENT_ID.",
        )

    if verify and os.environ.get("SPIFFE_JWT_SECRET"):
        payload = jwt.decode(
            token,
            os.environ["SPIFFE_JWT_SECRET"],
            algorithms=["HS256"],
        )
        return {**payload, "verified": True, "source": "jwt"}

    if verify and os.environ.get("SPIFFE_JWT_JWKS_URL"):
        jwk = jwt.PyJWKClient(os.environ["SPIFFE_JWT_JWKS_URL"])
        signing = jwk.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing.key,
            algorithms=["RS256", "ES256"],
            audience=os.environ.get("SPIFFE_JWT_AUDIENCE"),
        )
        return {**payload, "verified": True, "source": "jwt"}

    payload = jwt.decode(token, options={"verify_signature": False})
    return {**payload, "verified": False, "source": "jwt"}


def require_spiffe_identity() -> str:
    """
    Ensure a workload identity exists and return the SPIFFE ID (``sub`` claim).
    """
    ident = get_workload_identity()
    spiffe_id = ident.get(SPIFFE_CLAIM) or ident.get("spiffe_id")
    if not spiffe_id:
        raise RuntimeError("JWT missing SPIFFE ID (sub / spiffe_id)")
    return str(spiffe_id)
