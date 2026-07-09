"""
no_molestar.activar/desactivar ahora también actualizan
ui_estado.set_no_molestar() — para que el indicador visual del orbe
(ver ui.py, _dibujar_orbe) sepa cuándo mostrarse, sin que main.py
tenga que hacer ese trabajo por su cuenta.
"""

import sys
import types

import pytest


@pytest.fixture(autouse=True)
def stub_tts_y_logger(monkeypatch):
    if "tts" not in sys.modules:
        mod_tts = types.ModuleType("tts")
        mod_tts.hablar = lambda *a, **k: None
        monkeypatch.setitem(sys.modules, "tts", mod_tts)


import ui_estado
import no_molestar


@pytest.fixture(autouse=True)
def limpiar_estado():
    no_molestar._activo_hasta = None
    no_molestar._avisos_diferidos = []
    ui_estado.set_no_molestar(False)
    yield
    no_molestar._activo_hasta = None
    no_molestar._avisos_diferidos = []
    ui_estado.set_no_molestar(False)


def test_activar_prende_el_indicador():
    assert ui_estado.get_estado()["no_molestar"] is False
    no_molestar.activar(60)
    assert ui_estado.get_estado()["no_molestar"] is True


def test_desactivar_apaga_el_indicador():
    no_molestar.activar(60)
    no_molestar.desactivar()
    assert ui_estado.get_estado()["no_molestar"] is False


def test_desactivar_sin_estar_activo_no_crashea():
    exito, _ = no_molestar.desactivar()
    assert exito is False
    assert ui_estado.get_estado()["no_molestar"] is False


def test_expiracion_automatica_funciona_de_verdad():
    """
    FIX crítico: _hilo_esperar_expiracion() le faltaba `global
    _activo_hasta` — como la función asigna esa variable más abajo
    (limpieza de estado), Python la trataba como LOCAL en toda la
    función, y la lectura de la primera línea del while fallaba con
    UnboundLocalError apenas el hilo arrancaba. Como es un hilo
    daemon, esa excepción no tumbaba el programa, solo se perdía en
    stderr — la expiración automática de no molestar (el aviso
    hablado "el modo no molestar terminó" y la reproducción de
    avisos diferidos) JAMÁS funcionaba de verdad, solo si alguien
    llamaba a desactivar() a mano.
    """
    import threading
    from datetime import datetime, timedelta

    hasta = datetime.now() + timedelta(milliseconds=50)
    no_molestar._activo_hasta = hasta

    hilo = threading.Thread(
        target=no_molestar._hilo_esperar_expiracion,
        args=(hasta,),
        daemon=True,
    )
    hilo.start()
    hilo.join(timeout=3)

    assert not hilo.is_alive(), "el hilo debería terminar solo, no colgarse"
    assert no_molestar.modo_activo() is False
    assert ui_estado.get_estado()["no_molestar"] is False