"""
no_molestar.modo_activo / tiempo_restante — pura lógica de fechas
sobre el estado interno del módulo (`_activo_hasta`). Se prueba
manipulando ese estado DIRECTAMENTE con monkeypatch, sin pasar por
activar() — activar() lanza un hilo real en background (el de
expiración) que no hace falta para probar esta lógica, y complicaría
la suite con temporización real y hablar() (TTS).
"""

from datetime import datetime, timedelta

import pytest

import no_molestar


@pytest.fixture(autouse=True)
def limpiar_estado(monkeypatch):
    monkeypatch.setattr(no_molestar, "_activo_hasta", None)
    monkeypatch.setattr(no_molestar, "_avisos_diferidos", [])


def test_modo_inactivo_por_defecto():
    assert no_molestar.modo_activo() is False
    assert no_molestar.tiempo_restante() == 0


def test_modo_activo_con_fecha_futura(monkeypatch):
    monkeypatch.setattr(no_molestar, "_activo_hasta", datetime.now() + timedelta(minutes=10))
    assert no_molestar.modo_activo() is True


def test_modo_expirado_se_reporta_inactivo(monkeypatch):
    # "hasta" en el pasado -> ya expiró, aunque el hilo de expiración
    # real todavía no haya corrido para limpiarlo
    monkeypatch.setattr(no_molestar, "_activo_hasta", datetime.now() - timedelta(seconds=1))
    assert no_molestar.modo_activo() is False


def test_tiempo_restante_redondea_hacia_abajo_en_minutos(monkeypatch):
    monkeypatch.setattr(no_molestar, "_activo_hasta", datetime.now() + timedelta(minutes=5, seconds=59))
    # 5 minutos y 59 segundos restantes -> se reportan 5 minutos completos
    assert no_molestar.tiempo_restante() == 5


def test_registrar_aviso_diferido_acumula():
    no_molestar.registrar_aviso_diferido("Recordatorio: la pizza")
    no_molestar.registrar_aviso_diferido("Se acabó el temporizador")

    assert no_molestar._avisos_diferidos == [
        "Recordatorio: la pizza",
        "Se acabó el temporizador",
    ]
