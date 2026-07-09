"""
Tests de las funciones puras agregadas en la ronda de mejoras de
comodidad de uso: repetir último mensaje, modo dormido, "espera",
resumen de cadenas/macros, y describir_paso.
"""

import sys
import types

import pytest


# =========================================================
# session.py — es_repetir / es_dormir
# =========================================================

from session import es_repetir, es_dormir, DESPIERTA_WORD


@pytest.mark.parametrize("texto", [
    "repite", "repítelo", "repitelo",
    "qué dijiste", "que dijiste",
    "no te escuché", "REPITE", "  repite  ",
])
def test_es_repetir_frases_conocidas(texto):
    assert es_repetir(texto) is True


@pytest.mark.parametrize("texto", [
    "", None, "abre discord", "repite eso que estabas jugando",
])
def test_es_repetir_no_falsos_positivos(texto):
    assert es_repetir(texto) is False


@pytest.mark.parametrize("texto", [
    "duérmete", "duermete", "ponte a dormir", "vete a dormir",
    "modo silencioso", "silencio total",
])
def test_es_dormir_frases_conocidas(texto):
    assert es_dormir(texto) is True


@pytest.mark.parametrize("texto", [
    "", None, "abre discord", "duerme bien",
])
def test_es_dormir_no_falsos_positivos(texto):
    assert es_dormir(texto) is False


def test_despierta_word_es_una_palabra_simple():
    # DESPIERTA_WORD se usa como wake word alternativa en main.py —
    # debe ser una sola palabra corta, no una frase con espacios
    assert " " not in DESPIERTA_WORD


# =========================================================
# voz_utils.py — es_espera / escuchar_con_reintento / describir_paso
# =========================================================

from voz_utils import es_espera, escuchar_con_reintento, describir_paso


@pytest.mark.parametrize("texto", [
    "espera", "esperate", "espérate", "un momento", "un segundo",
    "dame un segundo", "dame un momento", "aguanta",
])
def test_es_espera_frases_conocidas(texto):
    assert es_espera(texto) is True


@pytest.mark.parametrize("texto", [
    "", None, "sí", "no", "espera un momento en la puerta",
])
def test_es_espera_no_falsos_positivos(texto):
    # frases que CONTIENEN palabras de espera pero no son la frase
    # exacta no deberían activarse (evita falsos positivos con
    # comandos reales que casualmente mencionen "espera" u otra)
    assert es_espera(texto) is False


def test_escuchar_con_reintento_da_mas_tiempo_si_pide_espera(monkeypatch):
    respuestas = iter(["", "espera", "", "discord"])

    mod_voice = types.ModuleType("voice")
    mod_voice.escuchar = lambda: next(respuestas, "")
    monkeypatch.setitem(sys.modules, "voice", mod_voice)

    resultado = escuchar_con_reintento(timeout=0.01, max_esperas=3)
    assert resultado == "discord"


def test_escuchar_con_reintento_tiene_tope_de_esperas(monkeypatch):
    mod_voice = types.ModuleType("voice")
    mod_voice.escuchar = lambda: "espera"
    monkeypatch.setitem(sys.modules, "voice", mod_voice)

    # con max_esperas=0, la primera "espera" ya se devuelve tal cual
    # en vez de seguir esperando para siempre
    resultado = escuchar_con_reintento(timeout=0.01, max_esperas=0)
    assert resultado == "espera"


def test_escuchar_con_reintento_sin_respuesta_devuelve_vacio(monkeypatch):
    mod_voice = types.ModuleType("voice")
    mod_voice.escuchar = lambda: ""
    monkeypatch.setitem(sys.modules, "voice", mod_voice)

    assert escuchar_con_reintento(timeout=0.01) == ""


@pytest.mark.parametrize("intent, valor, esperado", [
    ("abrir_app", "steam", "abrir steam"),
    ("cerrar_app", "discord", "cerrar discord"),
    ("media_pausar", "", "pausar"),
    ("media_volumen_exacto", "spotify|80", "volumen al 80"),
    ("intent_desconocido", "algo", "intent_desconocido algo"),
])
def test_describir_paso(intent, valor, esperado):
    assert describir_paso(intent, valor) == esperado