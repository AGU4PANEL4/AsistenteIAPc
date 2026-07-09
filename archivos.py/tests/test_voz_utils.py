"""
voz_utils.es_afirmacion / es_negacion / elegir_de_lista — todas
puras. interpretar_confirmacion() también se prueba, pero SOLO en
sus ramas de match local (que son puras); la rama que consulta a la
IA (ia._llamar_ollama) queda fuera de esta suite a propósito — no es
una función pura, depende de Ollama/Groq corriendo.
"""

import pytest

from voz_utils import es_afirmacion, es_negacion, elegir_de_lista, interpretar_confirmacion


# =========================================================
# es_afirmacion / es_negacion
# =========================================================

@pytest.mark.parametrize("respuesta", [
    "si", "sí", "dale", "ok", "okay", "claro", "confirmo",
    "sí, dale", "SI", "  si  ",
])
def test_es_afirmacion_casos_base(respuesta):
    assert es_afirmacion(respuesta) is True


@pytest.mark.parametrize("respuesta", [
    "no", "nel", "cancela", "cancelar", "negativo", "no gracias",
])
def test_es_negacion_casos_base(respuesta):
    assert es_negacion(respuesta) is True


def test_es_afirmacion_con_extras_contextuales():
    assert es_afirmacion("ábrelo", extras_si=["ábrelo", "hazlo"]) is True
    assert es_afirmacion("ábrelo") is False  # sin el extra, no está en la base


def test_es_afirmacion_vacio_o_no_relacionado():
    assert es_afirmacion("") is False
    assert es_afirmacion("mañana quizás") is False


def test_es_negacion_no_reconoce_afirmaciones():
    assert es_negacion("si dale") is False


# =========================================================
# interpretar_confirmacion — solo ramas locales (sin IA)
# =========================================================

def test_interpretar_confirmacion_afirmacion_directa():
    assert interpretar_confirmacion("sí, dale") is True


def test_interpretar_confirmacion_negacion_directa():
    assert interpretar_confirmacion("no, cancela") is False


def test_interpretar_confirmacion_vacio_es_none_sin_llamar_ia():
    # respuesta vacía -> None inmediato, nunca debería intentar
    # importar/llamar a ia.py
    assert interpretar_confirmacion("") is None
    assert interpretar_confirmacion(None) is None


# =========================================================
# elegir_de_lista
# =========================================================

OPCIONES = ["osu", "phasmophobia", "brawlhalla"]


@pytest.mark.parametrize("respuesta, indice_esperado", [
    ("el primero", 0),
    ("primero", 0),
    ("uno", 0),
    ("el 2", 1),
    ("dos", 1),
    ("segundo", 1),
    ("tres", 2),
    ("tercero", 2),
])
def test_elegir_de_lista_por_numero(respuesta, indice_esperado):
    assert elegir_de_lista(respuesta, OPCIONES) == indice_esperado


def test_elegir_de_lista_por_texto_aproximado():
    assert elegir_de_lista("phasmophobia", OPCIONES) == 1
    assert elegir_de_lista("quiero brawlhalla", OPCIONES) == 2


def test_elegir_de_lista_sin_coincidencia_devuelve_none():
    assert elegir_de_lista("no sé", OPCIONES) is None
    assert elegir_de_lista("", OPCIONES) is None


def test_elegir_de_lista_numero_fuera_de_rango_no_cuenta():
    # "quinto" no existe en una lista de 3 opciones — no debe
    # devolver un índice inválido ni crashear
    assert elegir_de_lista("el quinto", OPCIONES) is None


def test_elegir_de_lista_ambiguo_entre_varias_opciones_devuelve_none():
    # si el texto coincide con MÁS de una opción a la vez, no se
    # puede elegir una sola con certeza
    opciones = ["gta", "gta san andreas"]
    assert elegir_de_lista("gta", opciones) is None
