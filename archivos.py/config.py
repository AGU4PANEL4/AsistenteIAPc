import json
import os
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
    "groq_api_key":              "",
    # FIX/NUEVO: clave requerida por actualizador.py para saber qué
    # versión está instalada actualmente. Vacío = primera ejecución
    # sin versión registrada (ej. instalaciones previas al sistema de
    # actualizaciones) — actualizador.py detecta este caso y guarda
    # la versión de la release actual sin ofrecer actualizar, ya que
    # el usuario evidentemente ya tiene esa versión instalada.
    "version":                   "",
    # NUEVO: credenciales para reproducir una canción específica por
    # voz (ver spotify_cliente.py / youtube_cliente.py / setup_musica.py).
    # Vacío = esa función avisa que falta configurar, sin romper nada más.
    "spotify_client_id":         "",
    "spotify_client_secret":     "",
    "youtube_api_key":           "",
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

# =====================================
# GROQ (modo híbrido de IA)
# NUEVO: API en la nube usada cuando hay internet, en vez de Ollama
# local — ver gestor_ia.py para el detalle completo de por qué.
#
# La API key se busca PRIMERO en la variable de entorno
# GROQ_API_KEY (más seguro — así nunca queda en texto plano en un
# archivo que podrías subir a GitHub por accidente). Si no está ahí,
# se busca en config.json (más simple de configurar, pero menos
# seguro si compartís el proyecto con otros).
#
# Para conseguir una key gratis: https://console.groq.com/keys
#
# Si no hay ninguna key configurada, el modo híbrido simplemente
# cae siempre a Ollama local (comportamiento idéntico a como
# funcionaba antes de este cambio) — no es un error, es el respaldo
# esperado para quien no quiera configurar Groq.
# =====================================

_config_actual = cargar_config()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY") or _config_actual.get("groq_api_key", "")

# Modelo rápido y liviano de Groq, adecuado para comandos cortos
# (action|value, o charla de 1-2 frases) — no necesitamos un modelo
# grande para esto, y los modelos chicos de Groq responden casi
# instantáneo.
MODELO_GROQ = "llama-3.1-8b-instant"
# =====================================
# GROQ_API_KEY "EN CALIENTE"
# FIX/NUEVO: GROQ_API_KEY (arriba) se calcula UNA sola vez, en el
# momento en que este módulo se importa por primera vez. Eso es un
# problema para setup_groq.py: si el asistente arranca SIN key
# configurada, ese flujo la pide por consola, la valida, y la guarda
# en config.json recién DESPUÉS de que config.py ya se importó —
# con la constante congelada, groq_cliente.py seguiría viendo
# GROQ_API_KEY="" para siempre en esa misma ejecución, aunque el
# archivo en disco ya tenga la key recién guardada.
#
# Esta función lee siempre el valor ACTUAL (variable de entorno
# primero, si no config.json), sin cachear nada — así no importa en
# qué momento del arranque se configuró la key.
# =====================================

def obtener_groq_api_key():
    return os.environ.get("GROQ_API_KEY") or cargar_config().get("groq_api_key", "")


def guardar_groq_api_key(key):
    """
    Guarda la key en config.json Y la deja disponible de inmediato
    en esta misma ejecución vía variable de entorno.
    """
    data = cargar_config()
    data["groq_api_key"] = key
    guardar_config(data)
    os.environ["GROQ_API_KEY"] = key

# =====================================
# SPOTIFY / YOUTUBE — reproducir canción específica
# NUEVO: mismo patrón que GROQ_API_KEY arriba — variable de entorno
# primero, config.json después. Ver spotify_cliente.py y
# youtube_cliente.py para cómo se usan, y setup_musica.py para
# configurarlas la primera vez (script manual, no se pide en cada
# arranque como con Groq, porque no son necesarias para el
# funcionamiento base del asistente).
# =====================================

def obtener_spotify_credenciales():
    data = cargar_config()
    client_id     = os.environ.get("SPOTIFY_CLIENT_ID")     or data.get("spotify_client_id", "")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET") or data.get("spotify_client_secret", "")
    return client_id, client_secret


def guardar_spotify_credenciales(client_id, client_secret):
    data = cargar_config()
    data["spotify_client_id"]     = client_id
    data["spotify_client_secret"] = client_secret
    guardar_config(data)
    os.environ["SPOTIFY_CLIENT_ID"]     = client_id
    os.environ["SPOTIFY_CLIENT_SECRET"] = client_secret


def obtener_youtube_api_key():
    return os.environ.get("YOUTUBE_API_KEY") or cargar_config().get("youtube_api_key", "")


def guardar_youtube_api_key(key):
    data = cargar_config()
    data["youtube_api_key"] = key
    guardar_config(data)
    os.environ["YOUTUBE_API_KEY"] = key