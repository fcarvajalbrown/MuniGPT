"""
Unit tests for license.py verification (FR-08).

A throwaway Ed25519 keypair is minted through the real issuing helper
(tools/issue_license.mint_license), so the sign -> encode -> verify round trip is
exercised end to end without ever touching the production private key.
"""

import os
import sys
from datetime import date, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import license as lic

# Make the issuer-only tool importable (repo_root/tools).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
from issue_license import mint_license  # noqa: E402


@pytest.fixture
def keypair():
    priv = Ed25519PrivateKey.generate()
    pub_hex = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    return priv, pub_hex


def _payload(expires):
    return {
        "v": 1,
        "licenseId": "test-0001",
        "municipio": "Municipalidad de Prueba",
        "issuedTo": "Contacto TI",
        "issuedAt": "2026-07-09",
        "expiresAt": expires,
    }


def test_valid_perpetual_license(keypair):
    priv, pub_hex = keypair
    token = mint_license(_payload(None), priv)
    st = lic.verify_license(token, public_key_hex=pub_hex)
    assert st.valid and st.state == "valid"
    assert st.municipio == "Municipalidad de Prueba"
    assert st.issuedTo == "Contacto TI"
    assert st.expiresAt is None


def test_valid_future_expiry(keypair):
    priv, pub_hex = keypair
    token = mint_license(_payload("2099-01-01"), priv)
    st = lic.verify_license(token, public_key_hex=pub_hex)
    assert st.valid and st.state == "valid"


def test_expired_license(keypair):
    priv, pub_hex = keypair
    token = mint_license(_payload("2020-01-01"), priv)
    st = lic.verify_license(token, public_key_hex=pub_hex)
    assert not st.valid and st.state == "expired"
    assert "2020-01-01" in st.reason


def test_expiry_boundary_is_inclusive(keypair):
    """A license is valid through its expiry date, invalid the day after."""
    priv, pub_hex = keypair
    day = date(2026, 7, 9)
    token = mint_license(_payload(day.isoformat()), priv)
    assert lic.verify_license(token, public_key_hex=pub_hex, today=day).valid
    later = lic.verify_license(token, public_key_hex=pub_hex, today=day + timedelta(days=1))
    assert not later.valid and later.state == "expired"


def test_tampered_payload_fails_signature(keypair):
    priv, pub_hex = keypair
    token = mint_license(_payload(None), priv)
    prefix = lic.TOKEN_PREFIX
    _, sig_b64 = token[len(prefix):].split(".")
    # Re-sign nothing: keep the original signature but swap in an altered payload.
    forged_payload = _payload(None)
    forged_payload["municipio"] = "Municipalidad Falsificada"
    forged_b64 = lic._b64url_encode(lic.canonical_payload_bytes(forged_payload))
    forged = f"{prefix}{forged_b64}.{sig_b64}"
    st = lic.verify_license(forged, public_key_hex=pub_hex)
    assert not st.valid and st.state == "invalid"


def test_wrong_public_key_rejected(keypair):
    priv, _ = keypair
    token = mint_license(_payload(None), priv)
    other_hex = Ed25519PrivateKey.generate().public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    ).hex()
    st = lic.verify_license(token, public_key_hex=other_hex)
    assert not st.valid and st.state == "invalid"


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_license(key):
    st = lic.verify_license(key)
    assert not st.valid and st.state == "missing"


@pytest.mark.parametrize(
    "key",
    [
        "not-a-token",
        "MUNIGPT-onlyonepart",
        "MUNIGPT-a.b.c",
        "MUNIGPT-!!!.@@@",
    ],
)
def test_malformed_token(key):
    st = lic.verify_license(key)
    assert not st.valid and st.state == "invalid"
