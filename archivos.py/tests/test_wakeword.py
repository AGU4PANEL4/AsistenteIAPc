"""
wakeword.detectar_wakeword — reconoce la wake word ("jarvis" por
defecto) con tolerancia a errores de transcripción de voz. Pura:
recibe dos strings, devuelve bool.
"""

import pytest

from wakeword import detectar_wakeword, parecido


# =========================================================
# COINCIDENCIA EXACTA / SUBSTRING
# =========================================================

@pytest.mark.parametrize("texto", [
    "jarvis",
    "jarvis abre discord",
    "oye jarvis",
    "JARVIS",
    "  jarvis  ",
])
def test_wakeword_exacta_o_substring(texto):
    assert detectar_wakeword(texto, "jarvis") is True


# =========================================================
# TOLERANCIA DIFUSA (errores de transcripción)
# =========================================================

@pytest.mark.parametrize("texto", [
    "yarvis abre discord",   # variante fonética común
    "jarvys",
])
def test_wakeword_difusa_una_palabra(texto):
    assert detectar_wakeword(texto, "jarvis") is True


def test_wakeword_no_detectada_en_texto_no_relacionado():
    assert detectar_wakeword("abre discord por favor", "jarvis") is False


def test_wakeword_vacia_no_crashea():
    assert detectar_wakeword("", "jarvis") is False


# =========================================================
# WAKE WORD DE VARIAS PALABRAS
# =========================================================

def test_wakeword_multipalabra_exacta():
    assert detectar_wakeword("oye jarvis abre discord", "oye jarvis") is True


def test_wakeword_multipalabra_no_presente():
    assert detectar_wakeword("abre discord", "oye jarvis") is False


def test_wakeword_multipalabra_difusa_por_ventana():
    # variante ligeramente distinta de "oye jarvis" dentro de una
    # ventana de palabras del mismo tamaño (2 palabras) — un solo
    # carácter distinto en una de las dos palabras, similitud > 0.80
    assert detectar_wakeword("oye yarvis abre discord", "oye jarvis") is True


# =========================================================
# parecido() — SequenceMatcher, sin sorpresas
# =========================================================

def test_parecido_identico_es_uno():
    assert parecido("jarvis", "jarvis") == 1.0


def test_parecido_totalmente_distinto_es_bajo():
    assert parecido("jarvis", "xyz123") < 0.3


def test_parecido_es_simetrico():
    assert parecido("jarvis", "yarvis") == parecido("yarvis", "jarvis")
