"""
actualizador._hay_version_nueva — compara dos tags "vX.Y.Z" para
decidir si hay una actualización disponible. Pura: no descarga nada,
no toca GitHub, no toca disco (eso vive en otras funciones del mismo
módulo, ver _consultar_release/_descargar_exe, que sí necesitan red
y quedan fuera de esta suite).
"""

import pytest

from actualizador import _hay_version_nueva


@pytest.mark.parametrize("remoto, local, esperado", [
    ("v1.2.0", "v1.1.0", True),    # remoto más nuevo
    ("v1.1.0", "v1.2.0", False),   # remoto más viejo (no debería pasar en la práctica)
    ("v1.2.0", "v1.2.0", False),   # misma versión
    ("v2.0.0", "v1.9.9", True),    # cambio de versión mayor
    ("v1.10.0", "v1.9.0", True),   # FIX: comparación numérica, no de texto
                                    # ("1.10" no puede ser "menor" que "1.9"
                                    # por ser string más corto)
])
def test_comparacion_semantica(remoto, local, esperado):
    assert _hay_version_nueva(remoto, local) is esperado


def test_sin_version_local_no_hay_nueva():
    # FIX/NUEVO documentado en el código: el caso de "primera
    # ejecución sin versión registrada" se maneja APARTE (en
    # verificar_actualizacion_arranque), no ofreciendo una
    # actualización acá — por eso esta función devuelve False
    # cuando no hay tag_local, dejando que quien llama decida qué
    # hacer con ese caso especial.
    assert _hay_version_nueva("v1.2.0", "") is False
    assert _hay_version_nueva("v1.2.0", None) is False


def test_tags_no_semanticos_caen_a_comparacion_de_strings():
    # tags que no siguen el formato vX.Y.Z (poco común, pero posible
    # si alguna release no se etiquetó bien) — no debe crashear
    assert _hay_version_nueva("beta-2", "beta-1") is True
    assert _hay_version_nueva("beta-1", "beta-1") is False
