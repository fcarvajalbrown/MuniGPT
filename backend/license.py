"""
license.py — offline license verification for MuniGPT (FR-08).

Licenses are Ed25519-signed tokens minted by Instituto Igualdad's issuing tool
(tools/issue_license.py) with the matching PRIVATE key, held offline. This module
ships only the PUBLIC key, so a client can verify a license but can never forge
one — even if the whole client is reverse-engineered.

Token format:
    MUNIGPT-<b64url(payload_json)>.<b64url(signature)>

payload_json is compact, sorted-key UTF-8 JSON:
    {"v":1,"licenseId":"...","municipio":"...","issuedTo":"...",
     "issuedAt":"YYYY-MM-DD","expiresAt":"YYYY-MM-DD" | null}

The signature covers exactly those payload bytes. A null expiresAt is a perpetual
license. Enforcement is SOFT: main.py surfaces this status but never blocks /chat.
"""

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

TOKEN_PREFIX = "MUNIGPT-"

# Instituto Igualdad issuing public key (Ed25519, raw 32-byte key as hex). The
# matching private key is held offline by the issuer and is never in this repo.
PUBLIC_KEY_HEX = "8bc3045764a09c19d4d4c9e782ceca6d1842f4355eaf7226018056b193c7cbd7"


@dataclass
class LicenseStatus:
    valid: bool
    state: str  # "valid" | "expired" | "invalid" | "missing"
    reason: str  # Spanish, user-facing
    municipio: Optional[str] = None
    issuedTo: Optional[str] = None
    expiresAt: Optional[str] = None

    def to_public_dict(self) -> dict:
        """Safe to hand to the renderer — carries no secret, just status + metadata."""
        return asdict(self)


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def canonical_payload_bytes(payload: dict) -> bytes:
    """Deterministic serialization signed by the issuer and embedded in the token.

    Using one function for both sides means the signed bytes and the transported
    bytes can never drift apart.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def encode_token(payload: dict, signature: bytes) -> str:
    return (
        TOKEN_PREFIX
        + _b64url_encode(canonical_payload_bytes(payload))
        + "."
        + _b64url_encode(signature)
    )


def verify_license(
    key: Optional[str],
    public_key_hex: str = PUBLIC_KEY_HEX,
    today: Optional[date] = None,
) -> LicenseStatus:
    """Verifies a license token against the issuing public key.

    `today` is injectable for tests; production passes None (uses date.today()).
    """
    if not key or not key.strip():
        return LicenseStatus(False, "missing", "No hay licencia activada.")

    key = key.strip()
    if not key.startswith(TOKEN_PREFIX):
        return LicenseStatus(False, "invalid", "Formato de licencia no válido.")

    body = key[len(TOKEN_PREFIX):]
    if body.count(".") != 1:
        return LicenseStatus(False, "invalid", "Formato de licencia no válido.")

    payload_b64, sig_b64 = body.split(".")
    try:
        payload_bytes = _b64url_decode(payload_b64)
        signature = _b64url_decode(sig_b64)
    except (ValueError, TypeError):
        return LicenseStatus(False, "invalid", "Formato de licencia no válido.")

    # Verify the signature over the exact transported payload bytes. Do this
    # before parsing the JSON so unsigned/forged content is never interpreted.
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        pub.verify(signature, payload_bytes)
    except (InvalidSignature, ValueError):
        return LicenseStatus(False, "invalid", "La firma de la licencia no es válida.")

    try:
        payload = json.loads(payload_bytes)
    except ValueError:
        return LicenseStatus(False, "invalid", "Contenido de licencia no válido.")

    municipio = payload.get("municipio")
    issued_to = payload.get("issuedTo")
    expires_at = payload.get("expiresAt")

    if expires_at:
        try:
            exp = date.fromisoformat(expires_at)
        except (ValueError, TypeError):
            return LicenseStatus(
                False, "invalid", "Fecha de expiración no válida.",
                municipio, issued_to, expires_at,
            )
        if (today or date.today()) > exp:
            return LicenseStatus(
                False, "expired", f"La licencia expiró el {expires_at}.",
                municipio, issued_to, expires_at,
            )

    return LicenseStatus(
        True, "valid", "Licencia válida.", municipio, issued_to, expires_at
    )
