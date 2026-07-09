"""
aliases.traducir_alias / existe_alias / alias_por_app — lecturas
puras contra el dict global `aliases.aliases`. Se aislan de disco
reemplazando ese dict con monkeypatch (nunca se llama a
cargar_aliases()/guardar_aliases() en esta suite).
"""

import pytest

import aliases


@pytest.fixture(autouse=True)
def aliases_de_prueba(monkeypatch):
    monkeypatch.setattr(aliases, "aliases", {
        "osu":       "osu!(lazer)",
        "oso":       "osu!(lazer)",
        "dbd":       "dead by daylight",
        "gta":       "grand theft auto v enhanced",
        "gta v":     "grand theft auto v enhanced",
    })


def test_traducir_alias_conocido():
    assert aliases.traducir_alias("osu") == "osu!(lazer)"
    assert aliases.traducir_alias("dbd") == "dead by daylight"


def test_traducir_alias_normaliza_mayusculas_y_espacios():
    assert aliases.traducir_alias("  OSU  ") == "osu!(lazer)"


def test_traducir_alias_desconocido_devuelve_el_mismo_texto():
    # si no hay alias registrado, se usa el nombre tal cual (para
    # intentar abrirlo directamente, ver executor.py)
    assert aliases.traducir_alias("discord") == "discord"


def test_existe_alias():
    assert aliases.existe_alias("osu") is True
    assert aliases.existe_alias("OSU") is True
    assert aliases.existe_alias("discord") is False


def test_alias_por_app_devuelve_todos_los_que_apuntan_ahi():
    resultado = aliases.alias_por_app("osu!(lazer)")
    assert set(resultado) == {"osu", "oso"}


def test_alias_por_app_es_insensible_a_mayusculas():
    resultado = aliases.alias_por_app("OSU!(LAZER)")
    assert set(resultado) == {"osu", "oso"}


def test_alias_por_app_sin_alias_devuelve_lista_vacia():
    assert aliases.alias_por_app("una app sin alias") == []


def test_listar_aliases_devuelve_copia():
    copia = aliases.listar_aliases()
    copia["nuevo"] = "algo"
    assert "nuevo" not in aliases.aliases
