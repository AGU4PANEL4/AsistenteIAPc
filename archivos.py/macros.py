"""
Sistema de macros — secuencias de acciones guardadas con un nombre,
que se ejecutan de una sola vez con un comando de voz.

Ejemplo:
  Nombre: "modo juego"
  Acciones: [("cerrar_app", "discord"), ("media_volumen_exacto", "80"),
              ("abrir_app", "steam")]

Una macro se activa diciendo el nombre exacto (o aproximado) que se
le dio al crearla — el intent "ejecutar_macro" devuelve la lista de
pasos a ejecutar en secuencia, y main.py/executor.py los procesan
igual que cualquier otra lista de acciones.

Formato del archivo macros.json:
{
    "modo juego": [
        {"intent": "cerrar_app",          "valor": "discord"},
        {"intent": "media_volumen_exacto", "valor": "80"},
        {"intent": "abrir_app",            "valor": "steam"}
    ]
}
"""

import json
import os
import threading
from pathlib import Path
from difflib import SequenceMatcher

from logger import log
from voz_utils import UMBRAL_SIMILITUD_DIFUSA

# =========================================================
# ARCHIVO
# =========================================================

CARPETA_DATOS  = Path(os.environ["LOCALAPPDATA"]) / "AsistenteIA"
ARCHIVO_MACROS = CARPETA_DATOS / "macros.json"

_lock    = threading.Lock()
_macros  = {}   # nombre (str) -> lista de {"intent": ..., "valor": ...}

# =========================================================
# CARGAR / GUARDAR
# =========================================================

def _cargar():
    global _macros

    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)

    if not ARCHIVO_MACROS.exists():
        _macros = {}
        return

    try:
        with open(ARCHIVO_MACROS, "r", encoding="utf-8") as f:
            _macros = json.load(f)
    except Exception as e:
        print("[Macros] Error cargando, se empieza vacío:", e)
        log.exception("Error cargando macros.json")
        _macros = {}


def _guardar():
    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)

    with _lock:
        data = dict(_macros)

    try:
        with open(ARCHIVO_MACROS, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print("[Macros] Error guardando:", e)
        log.exception("Error guardando macros.json")

# =========================================================
# OPERACIONES
# =========================================================

def guardar_macro(nombre, pasos):
    """
    Guarda o sobreescribe una macro.

    `nombre` es el texto con el que el usuario la va a activar.
    `pasos` es una lista de dicts {"intent": ..., "valor": ...}.
    """
    nombre = nombre.lower().strip()

    with _lock:
        _macros[nombre] = pasos

    _guardar()
    print(f"[Macros] Guardada: '{nombre}' ({len(pasos)} pasos)")


def eliminar_macro(nombre):
    nombre = nombre.lower().strip()

    with _lock:
        existia = _macros.pop(nombre, None) is not None

    if existia:
        _guardar()
        print(f"[Macros] Eliminada: '{nombre}'")

    return existia


def listar_macros():
    """Devuelve una copia del dict de macros {nombre: pasos}."""
    with _lock:
        return dict(_macros)


def obtener_macro(nombre):
    """
    Busca una macro por nombre exacto primero, luego por similitud
    difusa (mismo umbral que usa wakeword.py, ver
    voz_utils.UMBRAL_SIMILITUD_DIFUSA) — así decir
    "modo gaming" puede activar "modo juego" si se parecen suficiente,
    igual que la tolerancia ya existente para la wake word.

    Devuelve (nombre_real, pasos) si encontró algo, o (None, None).
    """
    nombre = nombre.lower().strip()

    with _lock:
        copia = dict(_macros)

    # coincidencia exacta primero
    if nombre in copia:
        return nombre, copia[nombre]

    # coincidencia difusa
    mejor_nombre  = None
    mejor_ratio   = 0.0

    for clave in copia:
        ratio = SequenceMatcher(None, nombre, clave).ratio()
        if ratio > mejor_ratio:
            mejor_ratio  = ratio
            mejor_nombre = clave

    if mejor_ratio >= UMBRAL_SIMILITUD_DIFUSA:
        return mejor_nombre, copia[mejor_nombre]

    return None, None


def macro_existe(nombre):
    nombre = nombre.lower().strip()
    with _lock:
        return nombre in _macros

# =========================================================
# CARGAR AL IMPORTAR
# =========================================================

_cargar()