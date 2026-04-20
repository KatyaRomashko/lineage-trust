"""
Append-only transparency log with cryptographic signing and Rekor integration.

Each entry is chained (hash of previous + payload) to deter history rewriting.
Entries are signed with ECDSA (P-256) or optionally via the cosign CLI when
COSIGN_BINARY and key material are available. Signatures can be recorded in
Sigstore Rekor for public witness.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _load_or_create_signing_key():
    pem = os.environ.get("AUDIT_SIGNING_KEY_PEM")
    if pem:
        return serialization.load_pem_private_key(
            pem.encode(),
            password=None,
        )
    path = os.environ.get("AUDIT_SIGNING_KEY_PATH")
    if path and os.path.isfile(path):
        data = Path(path).read_bytes()
        return serialization.load_pem_private_key(data, password=None)
    return ec.generate_private_key(ec.SECP256R1())


_SIGNING_KEY = None


def _signing_key():
    global _SIGNING_KEY
    if _SIGNING_KEY is None:
        _SIGNING_KEY = _load_or_create_signing_key()
    return _SIGNING_KEY


def _public_pem_b64() -> str:
    key = _signing_key()
    pub = key.public_key()
    pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(pem).decode("ascii")


def _ecdsa_sign_message(message: bytes) -> str:
    key = _signing_key()
    sig = key.sign(message, ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(sig).decode("ascii")


def _last_chain_hash(log_path: Path) -> str:
    if not log_path.is_file():
        return "0" * 64
    last = ""
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                last = line
    if not last:
        return "0" * 64
    try:
        return json.loads(last)["entry_hash"]
    except (json.JSONDecodeError, KeyError):
        return "0" * 64


def _cosign_sign_blob(data: bytes) -> str | None:
    cosign = os.environ.get("COSIGN_BINARY", "cosign")
    key = os.environ.get("COSIGN_KEY_PATH")
    if not key or not os.path.isfile(key):
        return None
    env = {**os.environ, "COSIGN_PASSWORD": os.environ.get("COSIGN_PASSWORD", "")}
    try:
        p = subprocess.run(
            [cosign, "sign-blob", "--key", key, "-"],
            input=data,
            capture_output=True,
            env=env,
            timeout=120,
        )
        if p.returncode != 0:
            return None
        return p.stdout.decode("utf-8").strip()
    except (OSError, subprocess.TimeoutExpired):
        return None


def upload_signature_to_rekor(
    *,
    payload_sha256_hex: str,
    signature_b64: str,
    public_key_pem_b64: str,
    rekor_url: str | None = None,
) -> str | None:
    """
    Submit a hashedrekord entry to Rekor. Returns UUID (log index metadata) or None.
    """
    base = (rekor_url or os.environ.get("REKOR_URL", "https://rekor.sigstore.dev")).rstrip("/")
    proposed = {
        "apiVersion": "0.0.1",
        "kind": "hashedrekord",
        "spec": {
            "data": {
                "hash": {
                    "algorithm": "sha256",
                    "value": payload_sha256_hex,
                },
            },
            "signature": {
                "format": "x509",
                "content": signature_b64,
                "publicKey": {"content": public_key_pem_b64},
            },
        },
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            r = client.post(
                f"{base}/api/v1/log/entries",
                json=proposed,
                headers={"Accept": "application/json"},
            )
            if r.status_code not in (200, 201):
                return None
            body = r.json()
            # Response is a map of UUID -> entry
            if isinstance(body, dict) and body:
                return next(iter(body.keys()))
    except Exception:
        return None
    return None


def append_signed_audit_entry(
    payload: dict[str, Any],
    *,
    log_path: str | None = None,
) -> dict[str, Any]:
    """
    Append one transparency-log record: chain hash, ECDSA signature, optional Rekor UUID.

    Returns the full entry dict including ``entry_hash`` and ``rekor_uuid`` (optional).
    """
    path = Path(log_path or os.environ.get("TRANSPARENCY_LOG_PATH", "/tmp/audit/transparency.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)

    prev_hash = _last_chain_hash(path)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    chain_input = f"{prev_hash}|{canonical}".encode()
    entry_hash = hashlib.sha256(chain_input).hexdigest()

    sig_b64 = _ecdsa_sign_message(chain_input)
    pub_b64 = _public_pem_b64()

    cosign_sig = _cosign_sign_blob(chain_input)
    signature_for_rekor = cosign_sig or sig_b64

    rekor_uuid = None
    if os.environ.get("REKOR_UPLOAD", "1") == "1":
        rekor_uuid = upload_signature_to_rekor(
            payload_sha256_hex=entry_hash,
            signature_b64=signature_for_rekor,
            public_key_pem_b64=pub_b64,
        )

    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prev_hash": prev_hash,
        "entry_hash": entry_hash,
        "payload": payload,
        "signature_algorithm": "ECDSA_P256_SHA256",
        "signature": sig_b64,
        "public_key_pem_b64": pub_b64,
        "cosign_signature": cosign_sig,
        "rekor_uuid": rekor_uuid,
    }

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")

    return entry
