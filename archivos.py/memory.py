import json
import os
from pathlib import Path

# =========================================================
# ARCHIVO
# =========================================================

CARPETA_DATOS   = Path(os.environ["LOCALAPPDATA"]) / "AsistenteIA"
ARCHIVO_MEMORIA = CARPETA_DATOS / "memoria.json"

VALORES_DEFECTO = {
    "ultima_app":    None,
    "ultima_accion": None,
}

# =========================================================
# CARGAR
# =========================================================

def cargar_memoria():

    try:
        with open(ARCHIVO_MEMORIA, "r", encoding="utf-8") as f:
            data = json.load(f)

        # agregar claves nuevas si se añaden en el futuro
        cambiado = False
        for clave, valor in VALORES_DEFECTO.items():
            if clave not in data:
                data[clave] = valor
                cambiado = True

        if cambiado:
            _guardar(data)

        return data

    except:
        return dict(VALORES_DEFECTO)

# =========================================================
# GUARDAR
# =========================================================

def _guardar(data):
    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
    with open(ARCHIVO_MEMORIA, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def guardar_memoria():
    _guardar(memoria)

# =========================================================
# CARGAR AL IMPORTAR
# =========================================================

memoria = cargar_memoria()