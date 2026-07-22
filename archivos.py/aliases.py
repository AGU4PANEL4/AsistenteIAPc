import json
import os
import threading
from pathlib import Path

from rutas_datos import CARPETA_DATOS

# =========================================================
# ARCHIVO
# NUEVO: CARPETA_DATOS ahora viene de rutas_datos.py (multiplataforma
# — ver ese archivo para el detalle) en vez de calcularse acá con
# os.environ["LOCALAPPDATA"], que solo existe en Windows.
# =========================================================

ARCHIVO_ALIASES = CARPETA_DATOS / "aliases.json"

# =========================================================
# LOCK
# FIX/NUEVO: agregar_alias()/eliminar_alias() hacen un ciclo
# leer-modificar-guardar (cargar_aliases() -> mutar el dict en
# memoria -> guardar_aliases() -> reemplazar el global `aliases`)
# que antes no tenía NINGÚN lock — a diferencia de macros.py y
# temporizadores.py, que sí protegen exactamente este mismo patrón
# con threading.Lock(). Si dos llamadas a agregar_alias()/
# eliminar_alias() llegaran a solaparse desde hilos distintos (hoy
# no pasa en la práctica, pero nada en el código lo impedía), la más
# lenta en guardar terminaría pisando en disco el cambio que la otra
# ya había hecho, perdiéndolo en silencio — el mismo tipo de "lost
# update" ya documentado y resuelto en temporizadores.py._guardar().
# =========================================================

_lock = threading.Lock()

# =========================================================
# ALIASES INICIALES
# FIX/NUEVO: antes este dict traía una lista de alias predefinidos
# (osu, phasmophobia, dead by daylight, stellar blade, gta, spider
# man, wuthering waves, brawlhalla) — específicos de la biblioteca de
# juegos de una sola persona (la del desarrollo original), sin
# ninguna relación con lo que tenga instalado cualquier otro usuario
# nuevo del asistente. Quedaba guardado en el aliases.json de CADA
# instalación nueva desde el primer arranque (ver cargar_aliases()
# más abajo), mezclado sin distinción con los alias que la persona
# fuera creando por su cuenta — ruido de entrada para alguien que ni
# siquiera tiene esos juegos instalados, y confuso si more adelante
# quisiera "empezar de cero".
#
# Ahora arranca vacío — cualquier instalación nueva empieza sin
# ningún alias predefinido, y el usuario construye los suyos propios
# desde el primer "registra un alias" que use.
# =========================================================

ALIASES_INICIALES = {}

# =========================================================
# CARGAR
# =========================================================

def cargar_aliases():

    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)

    if not ARCHIVO_ALIASES.exists():
        guardar_aliases(ALIASES_INICIALES)
        return dict(ALIASES_INICIALES)

    try:
        with open(ARCHIVO_ALIASES, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return dict(ALIASES_INICIALES)

# =========================================================
# GUARDAR
# =========================================================

def guardar_aliases(data):

    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)

    with open(ARCHIVO_ALIASES, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# =========================================================
# AGREGAR
# =========================================================

def agregar_alias(alias, nombre_real):

    with _lock:
        data = cargar_aliases()
        data[alias.lower().strip()] = nombre_real
        guardar_aliases(data)

        global aliases
        aliases = data

    print(f"[Alias] '{alias}' → '{nombre_real}' guardado")

# =========================================================
# ELIMINAR
# =========================================================

def eliminar_alias(alias):

    with _lock:
        data  = cargar_aliases()
        alias = alias.lower().strip()

        if alias in data:
            del data[alias]
            guardar_aliases(data)

            global aliases
            aliases = data

            print(f"[Alias] Eliminado: '{alias}'")
            return True

        return False

# =========================================================
# CONSULTAR
# =========================================================

def existe_alias(alias):
    return alias.lower().strip() in aliases


def traducir_alias(nombre):
    return aliases.get(nombre.lower().strip(), nombre)


def listar_aliases():
    return dict(aliases)


def alias_por_app(nombre_real):
    """
    Devuelve la lista de alias (claves) que apuntan al nombre_real
    dado, sin distinguir mayúsculas/minúsculas. Usado por el flujo
    de eliminación guiada: primero se identifica la app, luego se
    muestran solo SUS alias para elegir cuál borrar — mucho más
    tolerante a errores de transcripción que pedir el alias exacto
    de una sola vez.
    """
    nombre_real = (nombre_real or "").lower().strip()
    return [
        alias for alias, real in aliases.items()
        if (real or "").lower().strip() == nombre_real
    ]

# =========================================================
# CARGAR AL IMPORTAR
# =========================================================

aliases = cargar_aliases()