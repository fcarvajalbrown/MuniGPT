"""
Unit tests for the deterministic disambiguation classifier in main.py.

A prompt-based clarify-first approach was tried and removed because the 1.7B
model applied it pathologically. This classifier is plain keyword matching,
not the LLM: a query is ambiguous only if it hits a procedural/payment trigger
word (pagar, trámite, ...) and does NOT already name one of the fixed
categories grounded in the corpus (DL 3063, Ley 19925).
"""

import main


def test_vague_payment_query_is_ambiguous():
    assert main._is_ambiguous("¿Cómo pago su parte?") is True
    assert main._is_ambiguous("necesito pagar un trámite") is True


def test_query_naming_a_category_is_not_ambiguous():
    assert main._is_ambiguous("¿Cómo pago la patente de alcoholes?") is False
    assert main._is_ambiguous("necesito pagar el permiso de circulación") is False
    assert main._is_ambiguous("¿cuánto es el derecho de aseo domiciliario?") is False


def test_query_with_no_procedural_trigger_is_not_ambiguous():
    assert main._is_ambiguous("¿qué dice la ley sobre juntas de vecinos?") is False


def test_matching_is_accent_insensitive():
    # "tramite" / "circulacion" without tildes must still match.
    assert main._is_ambiguous("tengo que hacer un tramite de pago") is True
    assert main._is_ambiguous("quiero pagar el permiso de circulacion") is False


def test_category_label_lookup():
    assert main._category_label("patente_alcoholes") == "Patente de alcoholes"
    assert main._category_label("no_existe") is None
    assert main._category_label(None) is None
