"""
issue_license.py — mint MuniGPT license tokens (FR-08). ISSUER-ONLY tool.

Run by Instituto Igualdad with the offline Ed25519 PRIVATE key. This tool is NOT
shipped in the installer; the client (backend/license.py) only ever holds the
public key. It reuses the verifier's canonical serialization and token encoding,
so issuing and verifying can never drift apart.

Usage:
    python tools/issue_license.py --private-key private.pem \
        --municipio "Municipalidad de Chillán" --issued-to "Contacto TI" \
        [--expires 2027-07-09]        # omit --expires for a perpetual license
"""

from __future__ import annotations

import argparse
import secrets
import sys
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Reuse the shared helpers from the shipped verifier so the two never diverge.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from license import canonical_payload_bytes, encode_token  # noqa: E402


def mint_license(payload: dict, private_key: Ed25519PrivateKey) -> str:
    """Signs the canonical payload bytes and returns a MUNIGPT-... token."""
    signature = private_key.sign(canonical_payload_bytes(payload))
    return encode_token(payload, signature)


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("The provided key is not an Ed25519 private key.")
    return key


def main() -> None:
    ap = argparse.ArgumentParser(description="Mint a MuniGPT license token.")
    ap.add_argument("--private-key", required=True, type=Path,
                    help="PEM file holding the issuing Ed25519 private key")
    ap.add_argument("--municipio", required=True)
    ap.add_argument("--issued-to", required=True)
    ap.add_argument("--expires", help="YYYY-MM-DD; omit for a perpetual license")
    ap.add_argument("--license-id", help="defaults to a random hex id")
    args = ap.parse_args()

    if args.expires:
        try:
            date.fromisoformat(args.expires)
        except ValueError:
            raise SystemExit("--expires must be a valid YYYY-MM-DD date")

    payload = {
        "v": 1,
        "licenseId": args.license_id or secrets.token_hex(8),
        "municipio": args.municipio,
        "issuedTo": args.issued_to,
        "issuedAt": date.today().isoformat(),
        "expiresAt": args.expires or None,
    }
    print(mint_license(payload, _load_private_key(args.private_key)))


if __name__ == "__main__":
    main()
