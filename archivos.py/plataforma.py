"""
Detección de sistema operativo — punto único para toda la lógica de
"¿estoy en Windows o en Linux?" que el resto del proyecto necesita
para elegir la implementación correcta de cada funcionalidad
específica del sistema operativo (rutas de datos, apagar/reiniciar,
inicio automático, control de medios, gestión de ventanas, etc).

NUEVO: centralizado acá en vez de que cada archivo haga su propio
`sys.platform == "win32"` suelto — un solo lugar para consultar, y si
algún día hiciera falta soportar un tercer sistema operativo (macOS,
por ejemplo), un solo lugar para extender en vez de perseguir cada
comparación repartida por el proyecto.
"""

import sys

ES_WINDOWS = sys.platform == "win32"
ES_LINUX   = sys.platform.startswith("linux")


def es_windows():
    return ES_WINDOWS


def es_linux():
    return ES_LINUX


def nombre_so():
    """Nombre corto para logs/diagnóstico ('windows', 'linux', u otro)."""
    if ES_WINDOWS:
        return "windows"
    if ES_LINUX:
        return "linux"
    return sys.platform