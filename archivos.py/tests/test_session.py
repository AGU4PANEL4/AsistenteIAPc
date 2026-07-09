"""
session.es_cancelacion / es_despedida — detectan si el usuario quiso
cancelar la operación en curso, o terminar la sesión de voz. Ambas
son puro procesamiento de texto, sin ningún estado compartido.
"""

import pytest

from session import es_cancelacion, es_despedida


# =========================================================
# CANCELACIÓN
# =========================================================

@pytest.mark.parametrize("texto", [
    "cancela",
    "cancelar",
    "detente",
    "stop",
    "olvídalo",
    "olvidalo",
    "déjalo",
    "dejalo",
    "no importa",
    "CANCELA",              # mayúsculas
    "  cancela  ",           # espacios extra
    "mejor cancela eso",     # palabra en medio de una frase
    "detente un momento",    # "detente" es palabra completa de cancelación
])
def test_frases_de_cancelacion(texto):
    assert es_cancelacion(texto) is True


@pytest.mark.parametrize("texto", [
    "",
    None,
    "abre discord",
    "para la música",        # FIX documentado: "para" NO debe cancelar
    "pon pausa al video",
    "cancelacion",           # palabra distinta a "cancela"/"cancelar" exactas
])
def test_frases_que_no_cancelan(texto):
    assert es_cancelacion(texto) is False


def test_cancelacion_es_por_palabra_completa_no_substring():
    # "detente" no debería activarse si aparece como parte de otra
    # palabra más larga que no tiene nada que ver (comparación por
    # palabra completa, no por substring)
    assert es_cancelacion("indetenteible") is False


# =========================================================
# DESPEDIDA
# =========================================================

@pytest.mark.parametrize("texto", [
    "termina",
    "adiós",
    "adios",
    "gracias",
    "nada más",
    "nada mas",
    "eso es todo",
    "listo",
])
def test_frases_de_despedida(texto):
    assert es_despedida(texto) is True


@pytest.mark.parametrize("texto, filler_esperado", [
    ("mmm nada más", "nada más"),
    ("eh gracias", "gracias"),
    ("bueno listo", "listo"),
    ("nada más eh", "nada más"),
])
def test_despedida_ignora_muletillas(texto, filler_esperado):
    assert es_despedida(texto) is True


@pytest.mark.parametrize("texto", [
    "",
    None,
    "abre discord",
    "gracias por abrir discord",   # "gracias" en medio de una frase distinta no cuenta
    "nada más que decir",           # frase completa distinta a la reconocida
])
def test_frases_que_no_son_despedida(texto):
    assert es_despedida(texto) is False
