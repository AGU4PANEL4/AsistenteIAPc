import json
import sys
from pathlib import Path

# =====================================
# CARPETA DATOS
# =====================================

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent

CONFIG_DIR = Path.home() / "AppData" / "Local" / "AsistenteIA"

CONFIG_DIR.mkdir(parents=True, exist_ok=True)

ARCHIVO_CONFIG = CONFIG_DIR / "config.json"

# =====================================
# VALORES POR DEFECTO
# =====================================

VALORES_DEFECTO = {
    "wake_word":                 "jarvis",
    "pregunta_inicio_realizada": False,
    "inicio_automatico":         False,
}

# =====================================
# CARGAR / GUARDAR
# =====================================

def cargar_config():

    if not ARCHIVO_CONFIG.exists():
        guardar_config(VALORES_DEFECTO)
        return dict(VALORES_DEFECTO)

    try:
        with open(ARCHIVO_CONFIG, "r", encoding="utf-8") as f:
            data = json.load(f)

        # agregar claves nuevas que no existían en versiones anteriores
        cambiado = False
        for clave, valor in VALORES_DEFECTO.items():
            if clave not in data:
                data[clave] = valor
                cambiado = True

        if cambiado:
            guardar_config(data)

        return data

    except:
        guardar_config(VALORES_DEFECTO)
        return dict(VALORES_DEFECTO)


def guardar_config(data):

    with open(ARCHIVO_CONFIG, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# =====================================
# WAKE WORD
# FIX: viene del config, no hardcodeado
# =====================================

WAKE_WORD = cargar_config().get("wake_word", "jarvis")

# =====================================
# MODELO DE IA (Ollama)
# FIX: antes ia.py usaba "qwen2.5:3b" pero verificacion.py
# revisaba/instalaba "gemma3" → el modelo que la IA realmente
# necesitaba nunca se descargaba. Ahora hay una sola fuente de
# verdad: este valor lo usan tanto ia.py como verificacion.py.
# Si quieres cambiar de modelo, cámbialo solo aquí.
# =====================================

MODELO_OLLAMA = "qwen2.5:3b"