import json
import os
from pathlib import Path

# =========================================================
# ARCHIVO
# =========================================================

CARPETA_DATOS   = Path(os.environ["LOCALAPPDATA"]) / "AsistenteIA"
ARCHIVO_ALIASES = CARPETA_DATOS / "aliases.json"

# =========================================================
# ALIASES INICIALES
# =========================================================

ALIASES_INICIALES = {
    # osu
    "osu":             "osu!(lazer)",
    "oso":             "osu!(lazer)",
    "osu lazer":       "osu!(lazer)",
    "oso lazer":       "osu!(lazer)",
    "os lazer":        "osu!(lazer)",
    "oz":              "osu!(lazer)",

    # phasmophobia
    "phasmofobia":     "phasmophobia",
    "fasmofobia":      "phasmophobia",

    # dead by daylight
    "dbd":             "dead by daylight",
    "deadbydaylight":  "dead by daylight",

    # stellar blade
    "estelar blade":   "stellar blade",

    # gta
    "gta":                   "grand theft auto v enhanced",
    "gta 5":                 "grand theft auto v enhanced",
    "gta cinco":             "grand theft auto v enhanced",
    "gta v":                 "grand theft auto v enhanced",

    # spider man
    "spider man":            "marvels spider man remastered",
    "espider man":           "marvels spider man remastered",
    "spiderman":             "marvels spider man remastered",

    # wuthering waves
    "wuthering waves":       "wuthering waves game",
    "udering waves":         "wuthering waves game",
    "withering waves":       "wuthering waves game",
    "utering waves":         "wuthering waves game",
    "butter in waves":       "wuthering waves game",
    "uterine waves":         "wuthering waves game",


    # brawlhalla
    "brawl hala":            "brawlhalla",
    "brawl jala":            "brawlhalla",
    "bleja":                 "brawlhalla",
    "brawljala":             "brawlhalla",
}

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
    except:
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