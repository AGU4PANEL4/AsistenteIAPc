"""
visual_utils.mezclar_hex — interpola entre dos colores hex, usado
por el spinner del splash/UI. Pura: números adentro, hex afuera.
"""

import pytest

from visual_utils import mezclar_hex


def test_factor_cero_da_el_fondo():
    assert mezclar_hex("#2de6c0", "#0b1a1f", 0.0) == "#0b1a1f"


def test_factor_uno_da_el_color():
    assert mezclar_hex("#2de6c0", "#0b1a1f", 1.0) == "#2de6c0"


def test_factor_intermedio_esta_entre_ambos():
    resultado = mezclar_hex("#ffffff", "#000000", 0.5)
    # con blanco/negro puro, el punto medio debería ser un gris ~50%
    assert resultado in ("#7f7f7f", "#808080")


@pytest.mark.parametrize("factor", [-5, -0.5, 1.5, 10])
def test_factor_fuera_de_rango_se_recorta(factor):
    # la función debe recortar (clamp) a [0, 1] en vez de devolver
    # valores fuera de rango o crashear con hex inválido
    resultado = mezclar_hex("#2de6c0", "#0b1a1f", factor)
    esperado = mezclar_hex("#2de6c0", "#0b1a1f", max(0.0, min(1.0, factor)))
    assert resultado == esperado


def test_resultado_siempre_es_hex_valido():
    resultado = mezclar_hex("#2de6c0", "#0b1a1f", 0.37)
    assert resultado.startswith("#")
    assert len(resultado) == 7
    int(resultado[1:], 16)  # no debe lanzar ValueError
