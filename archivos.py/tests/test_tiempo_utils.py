"""
tiempo_utils.parsear_duracion — usada por recordatorios.py y
temporizadores.py para interpretar frases como "10 minutos" dichas
por voz. 100% pura: texto adentro, segundos (o None) afuera.
"""

import pytest

from tiempo_utils import parsear_duracion


@pytest.mark.parametrize("texto, esperado", [
    ("10 minutos",                 600),
    ("1 hora",                    3600),
    ("2 horas",                   7200),
    ("30 segundos",                 30),
    ("1 hora 30 minutos",         5400),
    ("2 horas 15 minutos",       8100),
    ("5 min",                      300),
    ("5 mins",                     300),
    ("1 minuto",                    60),
    ("1 segundo",                    1),
])
def test_duraciones_validas(texto, esperado):
    assert parsear_duracion(texto) == esperado


def test_frase_completa_con_relleno():
    # el usuario nunca dice solo "10 minutos" a secas — viene envuelto
    # en una frase, y la función debe encontrar el patrón igual
    assert parsear_duracion("recuérdame en 10 minutos que llame") == 600
    assert parsear_duracion("pon un temporizador de 1 hora y 30 minutos") == 5400


@pytest.mark.parametrize("texto", [
    "",
    None,
    "mañana a las tres",       # hora exacta, no duración relativa — no es de acá
    "no dijo ningún número",
    "cero minutos",             # "cero" no es un dígito, regex no lo matchea
])
def test_sin_duracion_devuelve_none(texto):
    assert parsear_duracion(texto) is None


def test_cero_segundos_explicito_devuelve_none():
    # "0 minutos" matchea el patrón pero suma 0 — no tiene sentido
    # crear un recordatorio/temporizador para "ya mismo"
    assert parsear_duracion("0 minutos") is None


def test_mayusculas_y_espacios_extra():
    assert parsear_duracion("  10   MINUTOS  ") == 600


def test_varias_unidades_se_suman_aunque_esten_repetidas():
    # caso raro pero posible si Whisper transcribe mal — no debería
    # crashear, solo sumar todo lo que encuentre
    assert parsear_duracion("10 minutos 5 minutos") == 900
