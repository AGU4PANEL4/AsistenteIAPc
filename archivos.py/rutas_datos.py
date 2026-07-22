"""
Carpeta de datos del asistente — punto único, multiplataforma.

FIX/NUEVO: antes CADA módulo que guarda algo en disco (aliases.py,
memory.py, macros.py, recordatorios.py, temporizadores.py, logger.py,
config.py) repetía la misma línea:

    CARPETA_DATOS = Path(os.environ["LOCALAPPDATA"]) / "AsistenteIA"

Eso funciona solo en Windows — LOCALAPPDATA no existe como variable de
entorno en Linux, así que CUALQUIERA de esos módulos tiraba KeyError
apenas se importaba en un sistema no-Windows, tumbando el asistente
completo antes de llegar a hacer nada útil (ni siquiera se llegaba a
mostrar el splash).

Ahora esto vive en un solo lugar: en Windows sigue siendo EXACTAMENTE
la misma carpeta de siempre (%LOCALAPPDATA%\\AsistenteIA — ningún dato
existente de instalaciones ya hechas se pierde ni se mueve). En Linux
se usa el estándar XDG Base Directory (~/.local/share/AsistenteIA, o
$XDG_DATA_HOME/AsistenteIA si esa variable está configurada) — la
ubicación esperada por cualquier usuario de Linux para datos de una
app que no viene empaquetada por el gestor de paquetes del sistema.

Uso desde otros módulos:
    from rutas_datos import CARPETA_DATOS
    ARCHIVO_ALIASES = CARPETA_DATOS / "aliases.json"
"""

import os
from pathlib import Path

from plataforma import es_windows

NOMBRE_CARPETA = "AsistenteIA"


def _calcular_carpeta_datos():
    if es_windows():
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            # no debería pasar en un Windows normal (LOCALAPPDATA
            # siempre está seteada por el propio Windows) — pero por
            # si acaso, se cae a la carpeta de home en vez de crashear
            # con un KeyError como pasaba antes.
            base = str(Path.home() / "AppData" / "Local")
        return Path(base) / NOMBRE_CARPETA

    # Linux (y cualquier otro *nix): estándar XDG Base Directory —
    # ver https://specifications.freedesktop.org/basedir-spec/
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / NOMBRE_CARPETA


CARPETA_DATOS = _calcular_carpeta_datos()

# se crea acá, una sola vez, al importar — así ningún módulo que
# solo lee/escribe archivos necesita acordarse de crear la carpeta
# por su cuenta antes de usarla (varios de los módulos que migran a
# usar esto ya hacían su propio mkdir defensivo antes de cada
# operación; se puede simplificar, pero no hace falta tocarlo — no
# está de más que la carpeta ya exista desde el import).
CARPETA_DATOS.mkdir(parents=True, exist_ok=True)