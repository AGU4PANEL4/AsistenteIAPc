"""
conversiones.detectar_conversion — 100% pura, sin IA ni red ni disco.
Cubre longitud, peso, volumen y temperatura, distintas formas de
frasear la pregunta, tildes, unidades abreviadas, y sobre todo los
falsos positivos: frases con números que NO son conversiones no
deben dispararse (chocarían con temporizadores/volumen/etc).
"""

import pytest

from conversiones import detectar_conversion, _formatear_numero, _quitar_tildes


# =========================================================
# LONGITUD
# =========================================================

@pytest.mark.parametrize("texto, esperado", [
    ("cuántos milímetros hay en 1 centímetro", "1 centímetro son 10 milímetros"),
    ("cuántos mm hay en 1 cm", "1 centímetro son 10 milímetros"),
    ("cuántos milimetros hay en un centimetro", "1 centímetro son 10 milímetros"),
    ("convierte 5 km a metros", "5 kilómetros son 5000 metros"),
    ("cuántos metros hay en 2.5 kilómetros", "2.5 kilómetros son 2500 metros"),
    ("cuánto es 300 centímetros en metros", "300 centímetros son 3 metros"),
])
def test_longitud(texto, esperado):
    assert detectar_conversion(texto) == esperado


# =========================================================
# PESO
# =========================================================

@pytest.mark.parametrize("texto, esperado", [
    ("cuánto es 5 kg en gramos", "5 kilogramos son 5000 gramos"),
    ("convierte 2 kilos a gramos", "2 kilogramos son 2000 gramos"),
    ("cuántos kilogramos son 500 gramos", "500 gramos son 0.5 kilogramos"),
])
def test_peso(texto, esperado):
    assert detectar_conversion(texto) == esperado


# =========================================================
# VOLUMEN
# =========================================================

@pytest.mark.parametrize("texto, esperado", [
    ("cuántos litros son 500 mililitros", "500 mililitros son 0.5 litros"),
    ("convierte 2 litros a mililitros", "2 litros son 2000 mililitros"),
])
def test_volumen(texto, esperado):
    assert detectar_conversion(texto) == esperado


# =========================================================
# TEMPERATURA (fórmula especial, no lineal desde cero)
# =========================================================

@pytest.mark.parametrize("texto, esperado", [
    ("convierte 20 celsius a fahrenheit", "20 grados celsius son 68 grados fahrenheit"),
    ("cuánto es 98 fahrenheit en celsius", "98 grados fahrenheit son 36.67 grados celsius"),
    ("cuánto es 0 celsius en fahrenheit", "0 grados celsius son 32 grados fahrenheit"),
    ("cuánto es 100 celsius en fahrenheit", "100 grados celsius son 212 grados fahrenheit"),
])
def test_temperatura(texto, esperado):
    assert detectar_conversion(texto) == esperado


# =========================================================
# FALSOS POSITIVOS — no deben dispararse
# (crítico: si esto fallara mal, chocaría con temporizadores,
# volumen, o cualquier otro comando que use un número)
# =========================================================

@pytest.mark.parametrize("texto", [
    "",
    None,
    "pon un temporizador de 10 minutos",
    "recuérdame en 10 minutos que llame",
    "sube el volumen a 50",
    "pon el volumen de spotify al 70",
    "abre counter strike 2",
    "cuánto es 47 por 12",
    "qué hora es",
    "activa el modo no molestar por 30 minutos",
])
def test_no_dispara_en_frases_normales(texto):
    assert detectar_conversion(texto) is None


def test_categorias_distintas_no_convierten():
    # no tiene sentido convertir gramos a metros -- debe ignorarse,
    # no inventar un resultado
    assert detectar_conversion("cuántos gramos hay en un metro") is None


def test_solo_una_unidad_no_convierte():
    assert detectar_conversion("cuántos centímetros son") is None
    assert detectar_conversion("5 kilómetros") is None


# =========================================================
# _formatear_numero
# =========================================================

@pytest.mark.parametrize("numero, esperado", [
    (1.0, "1"),
    (10.0, "10"),
    (0.5, "0.5"),
    (2500.0, "2500"),
    (36.666666, "36.67"),
])
def test_formatear_numero(numero, esperado):
    assert _formatear_numero(numero) == esperado


# =========================================================
# _quitar_tildes
# =========================================================

@pytest.mark.parametrize("texto, esperado", [
    ("centímetro", "centimetro"),
    ("kilómetros", "kilometros"),
    ("año", "año"),  # la ñ se preserva a propósito, no es una tilde
    ("fahrenheit", "fahrenheit"),
])
def test_quitar_tildes(texto, esperado):
    assert _quitar_tildes(texto) == esperado