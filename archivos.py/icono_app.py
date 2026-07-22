"""
Ruta del ícono de la app — un solo lugar que resuelve dónde está
asistente-ia.ico/.png tanto corriendo desde fuente (python main.py)
como ya empaquetado con PyInstaller, para que cualquier módulo que
necesite fijar el ícono de una ventana (ver splash.py) no tenga que
repetir esta lógica.

Mismo patrón que BASE_DIR en config.py: sys.frozen distingue los dos
casos. Al empaquetar, asistente-ia.ico/.png viajan como datos sueltos
declarados en asistente.spec (datas=[...]) — quedan en la MISMA
carpeta que AsistenteIA.exe, así que la ruta relativa a
sys.executable los encuentra igual que la ruta relativa a este
archivo los encuentra en desarrollo.
"""

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys.executable).parent
else:
    _BASE_DIR = Path(__file__).resolve().parent

RUTA_ICONO_ICO = _BASE_DIR / "asistente-ia.ico"
RUTA_ICONO_PNG = _BASE_DIR / "asistente-ia.png"


def existe_icono():
    """True si al menos uno de los dos archivos de ícono está
    presente — usado para saltear en silencio si por algún motivo no
    se copiaron (ej. alguien corriendo el código sin los assets del
    repo completo), en vez de que fijar el ícono tumbe el arranque."""
    return RUTA_ICONO_ICO.exists() or RUTA_ICONO_PNG.exists()
