"""
app_finder.limpiar_nombre — normaliza nombres de apps/juegos para
poder compararlos (cache, alias, búsqueda difusa) sin que acentos,
mayúsculas, símbolos de marca registrada, etc. generen falsos
negativos.

NOTA: app_finder.py importa `winreg` (solo existe en Windows) al
nivel de módulo, así que este archivo se salta solo (no falla) si se
corre en Linux/Mac — correlo en tu máquina Windows para que se
ejecute de verdad. El resto de la suite (session, macros, aliases,
etc.) no tiene esta restricción.
"""

import pytest

app_finder = pytest.importorskip("app_finder")

limpiar_nombre = app_finder.limpiar_nombre
parecido = app_finder.parecido


@pytest.mark.parametrize("entrada, esperado", [
    ("osu!(lazer)",                          "osulazer"),
    ("Marvel's Spider-Man: Remastered",       "marvels spider man remastered"),
    ("  Café_del Mar  ",                      "cafe del mar"),
    ("Wuthering Waves\u2122",                  "wuthering waves"),   # símbolo ™
    ("STELLAR BLADE",                         "stellar blade"),
])
def test_limpiar_nombre_normaliza(entrada, esperado):
    assert limpiar_nombre(entrada) == esperado


def test_limpiar_nombre_es_idempotente():
    # limpiar un nombre ya limpio no debe cambiar nada
    limpio = limpiar_nombre("Grand Theft Auto V")
    assert limpiar_nombre(limpio) == limpio


def test_limpiar_nombre_colapsa_espacios_multiples():
    assert limpiar_nombre("gta   v") == "gta v"


def test_limpiar_nombre_vacio():
    assert limpiar_nombre("") == ""


def test_parecido_identico():
    assert parecido("discord", "discord") == 1.0


def test_parecido_distinto_es_bajo():
    assert parecido("discord", "steam") < 0.5
