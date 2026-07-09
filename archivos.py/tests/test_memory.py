"""
memory.registrar_accion / obtener_historial / ultimo_de — operan
sobre el dict global `memory.memoria` en memoria pura (a pesar del
nombre del módulo, estas funciones NO tocan disco por sí solas —
guardar_memoria() es una función aparte, nunca llamada acá).
"""

import pytest

import memory


@pytest.fixture(autouse=True)
def memoria_de_prueba(monkeypatch):
    monkeypatch.setattr(memory, "memoria", {
        "ultima_app":    None,
        "ultima_accion": None,
        "historial": {accion: [] for accion in memory.ACCIONES_CON_HISTORIAL},
    })


def test_registrar_y_obtener_historial():
    memory.registrar_accion("abrir_app", "discord")
    memory.registrar_accion("abrir_app", "steam")

    historial = memory.obtener_historial("abrir_app")

    # más reciente primero
    assert historial == ["steam", "discord"]


def test_ultimo_de():
    memory.registrar_accion("abrir_app", "discord")
    memory.registrar_accion("abrir_app", "steam")

    assert memory.ultimo_de("abrir_app") == "steam"


def test_ultimo_de_sin_historial_es_none():
    assert memory.ultimo_de("abrir_app") is None


def test_repetir_valor_lo_mueve_al_frente_sin_duplicar():
    memory.registrar_accion("abrir_app", "discord")
    memory.registrar_accion("abrir_app", "steam")
    memory.registrar_accion("abrir_app", "discord")  # se repite

    historial = memory.obtener_historial("abrir_app")

    assert historial == ["discord", "steam"]
    assert historial.count("discord") == 1


def test_historial_se_recorta_al_maximo():
    for i in range(memory.HISTORIAL_MAX + 3):
        memory.registrar_accion("abrir_app", f"app{i}")

    historial = memory.obtener_historial("abrir_app")

    assert len(historial) == memory.HISTORIAL_MAX
    # el más reciente sigue siendo el último insertado
    assert historial[0] == f"app{memory.HISTORIAL_MAX + 2}"


def test_valor_vacio_no_se_registra():
    memory.registrar_accion("abrir_app", "")
    memory.registrar_accion("abrir_app", None)

    assert memory.obtener_historial("abrir_app") == []


def test_accion_sin_historial_configurado_no_hace_nada():
    # "listar_recordatorios" no está en ACCIONES_CON_HISTORIAL — no
    # debe crashear ni crear una clave nueva
    memory.registrar_accion("listar_recordatorios", "algo")
    assert "listar_recordatorios" not in memory.memoria["historial"]


def test_historiales_de_distintas_acciones_no_se_mezclan():
    memory.registrar_accion("abrir_app", "discord")
    memory.registrar_accion("cerrar_app", "steam")

    assert memory.obtener_historial("abrir_app") == ["discord"]
    assert memory.obtener_historial("cerrar_app") == ["steam"]
