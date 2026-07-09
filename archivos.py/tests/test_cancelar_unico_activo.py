"""
recordatorios.cancelar_por_palabra_clave / temporizadores.cancelar_por_palabra_clave
— con exactamente un recordatorio/temporizador activo, "cancélalo"
sin dar ningún nombre debe cancelar ese único, en vez de responder
"no entendí cuál" (bug real encontrado: en temporizadores.py este
fallback existía pero era código inalcanzable — el early-return por
palabras_clave vacío ocurría ANTES de llegar a revisarlo; en
recordatorios.py directamente no existía el fallback).
"""

import sys
import types

import pytest

# recordatorios.py y temporizadores.py hacen `from tts import hablar`
# a nivel de módulo — tts.py real necesita edge_tts/pygame instalados,
# que no hacen falta para probar esta lógica pura. Se stubea antes de
# importar, mismo patrón ya usado en otros tests de este proyecto.
if "tts" not in sys.modules:
    _tts_stub = types.ModuleType("tts")
    _tts_stub.hablar = lambda *a, **k: None
    sys.modules["tts"] = _tts_stub

import recordatorios
import temporizadores


@pytest.fixture(autouse=True)
def limpiar_estado():
    recordatorios._recordatorios.clear()
    temporizadores._temporizadores.clear()
    yield
    recordatorios._recordatorios.clear()
    temporizadores._temporizadores.clear()


# =========================================================
# TEMPORIZADORES
# =========================================================

def test_temporizador_cancela_el_unico_sin_nombrar():
    temporizadores._temporizadores["1"] = {
        "momento": "2099-01-01T00:00:00", "nombre": None,
    }

    exito, mensaje = temporizadores.cancelar_por_palabra_clave("")

    assert exito is True
    assert "1" not in temporizadores._temporizadores


def test_temporizador_con_varios_y_sin_nombre_no_cancela_nada():
    temporizadores._temporizadores["1"] = {"momento": "2099-01-01T00:00:00", "nombre": "pasta"}
    temporizadores._temporizadores["2"] = {"momento": "2099-01-01T00:00:00", "nombre": "café"}

    exito, mensaje = temporizadores.cancelar_por_palabra_clave("")

    assert exito is False
    assert len(temporizadores._temporizadores) == 2


def test_temporizador_sin_ninguno_activo_no_crashea():
    exito, mensaje = temporizadores.cancelar_por_palabra_clave("")
    assert exito is False


# =========================================================
# RECORDATORIOS
# =========================================================

def test_recordatorio_cancela_el_unico_sin_nombrar():
    recordatorios._recordatorios["1"] = {
        "momento": "2099-01-01T00:00:00", "texto": "llamar a mamá",
    }

    exito, mensaje = recordatorios.cancelar_por_palabra_clave("")

    assert exito is True
    assert "mamá" in mensaje
    assert "1" not in recordatorios._recordatorios


def test_recordatorio_con_varios_y_sin_nombre_no_cancela_nada():
    recordatorios._recordatorios["1"] = {"momento": "2099-01-01T00:00:00", "texto": "llamar a mamá"}
    recordatorios._recordatorios["2"] = {"momento": "2099-01-01T00:00:00", "texto": "la pizza"}

    exito, mensaje = recordatorios.cancelar_por_palabra_clave("")

    assert exito is False
    assert len(recordatorios._recordatorios) == 2


def test_recordatorio_con_palabra_clave_sigue_funcionando_normal():
    recordatorios._recordatorios["1"] = {"momento": "2099-01-01T00:00:00", "texto": "llamar a mamá"}
    recordatorios._recordatorios["2"] = {"momento": "2099-01-01T00:00:00", "texto": "la pizza"}

    exito, mensaje = recordatorios.cancelar_por_palabra_clave("pizza")

    assert exito is True
    assert "1" in recordatorios._recordatorios
    assert "2" not in recordatorios._recordatorios