"""
macros.obtener_macro — busca una macro por nombre exacto o difuso.

La lógica de matching es pura, pero el módulo guarda su estado en un
dict global (`macros._macros`) que normalmente se carga desde
macros.json en disco. Para testear SOLO la lógica de matching, sin
tocar el archivo real del usuario, se reemplaza `macros._macros`
directamente con monkeypatch — nunca se llama a _cargar()/_guardar().
"""

import pytest

import macros


PASOS_JUEGO = [{"intent": "abrir_app", "valor": "steam"}]
PASOS_TRABAJO = [{"intent": "abrir_app", "valor": "discord"}]


@pytest.fixture(autouse=True)
def macros_de_prueba(monkeypatch):
    """
    Reemplaza el dict interno de macros por uno de prueba, para cada
    test — se restaura solo al terminar (monkeypatch lo revierte).
    """
    monkeypatch.setattr(macros, "_macros", {
        "modo juego": PASOS_JUEGO,
        "modo trabajo": PASOS_TRABAJO,
    })


def test_coincidencia_exacta():
    nombre, pasos = macros.obtener_macro("modo juego")
    assert nombre == "modo juego"
    assert pasos == PASOS_JUEGO


def test_coincidencia_exacta_normaliza_mayusculas_y_espacios():
    nombre, pasos = macros.obtener_macro("  MODO JUEGO  ")
    assert nombre == "modo juego"
    assert pasos == PASOS_JUEGO


def test_coincidencia_difusa_encuentra_la_mas_parecida():
    # "modo juegos" (con "s" de más) se parece mucho más a
    # "modo juego" (ratio ~0.95) que a "modo trabajo" (~0.61) —
    # supera el umbral de 0.80 y elige la correcta
    nombre, pasos = macros.obtener_macro("modo juegos")
    assert nombre == "modo juego"
    assert pasos == PASOS_JUEGO


def test_sin_coincidencia_devuelve_none_none():
    nombre, pasos = macros.obtener_macro("algo completamente distinto")
    assert nombre is None
    assert pasos is None


def test_macro_existe():
    assert macros.macro_existe("modo juego") is True
    assert macros.macro_existe("MODO JUEGO") is True
    assert macros.macro_existe("no existe") is False


def test_listar_macros_devuelve_copia_no_la_referencia():
    copia = macros.listar_macros()
    copia["nueva"] = []
    # modificar la copia no debe afectar el estado real del módulo
    assert "nueva" not in macros._macros
