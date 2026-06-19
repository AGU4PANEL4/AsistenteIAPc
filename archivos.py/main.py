import sys
import time
from session import sesion, es_cancelacion, es_despedida
from voice import escuchar, recalibrar
from tts import hablar
from wakeword import detectar_wakeword
from intents import detectar_intent
from ia import interpretar_con_ia, responder_charla
from executor import ejecutar
from app_finder import limpiar_cache_duplicados
import threading
from app_finder import *
from config import (
    cargar_config,
    guardar_config,
    WAKE_WORD
)
from startup import (
    activar_inicio_automatico,
    desactivar_inicio_automatico,
    startup_activado
)

# =====================================================
# MODO "SOLO CONFIGURAR STARTUP" (usado por el instalador)
# El instalador de Inno Setup llama:
#   AsistenteIA.exe --activar-startup
# y espera que SOLO se registre la tarea programada y el
# proceso termine — no que arranque el micrófono/wakeword/Ollama.
# Sin este bloque, ese argumento se ignoraba y el .exe lanzaba
# el asistente completo durante la instalación.
# =====================================================

if "--activar-startup" in sys.argv:
    print("[Startup] Configurando inicio automático (modo instalador)...")
    if activar_inicio_automatico():
        print("[Startup] Tarea programada creada correctamente.")
        sys.exit(0)
    else:
        print("[Startup] No se pudo crear la tarea programada.")
        sys.exit(1)

from verificacion import preparar_ia

# =====================================================
# CONFIG
# =====================================================

TIMEOUT = 20
ultimo_comando = time.time()

if not preparar_ia():
    print("No se pudo preparar la IA.")
    time.sleep(10)
    exit()

# =====================================================
# INICIO
# =====================================================

asegurar_archivos()

config = cargar_config()

if not config.get("pregunta_inicio_realizada", False):

    respuesta = input(
        "\n¿Deseas que el asistente inicie automáticamente con Windows? (s/n): "
    ).strip().lower()

    if respuesta in [
        "s", "si", "sí", "ci", "cí",
        "zi", "zí", "dale", "hazlo", "activalo"
    ]:
        activar_inicio_automatico()
        config["inicio_automatico"] = True
        print("Inicio automático activado.")
    else:
        desactivar_inicio_automatico()
        config["inicio_automatico"] = False
        print("Inicio automático desactivado.")

    config["pregunta_inicio_realizada"] = True
    guardar_config(config)

print("[Sistema] Iniciando asistente...")

threading.Thread(target=indexar_apps,         daemon=True).start()
threading.Thread(target=indexar_juegos_steam, daemon=True).start()

try:
    limpiar_cache_duplicados()
except Exception as e:
    print("Error limpiando cache:", e)

print("[Sistema] Asistente listo")
hablar("Asistente listo")

# =====================================================
# LOOP PRINCIPAL
# =====================================================

while True:

    comando = escuchar()

    # =====================================================
    # TIMEOUT SESIÓN
    # =====================================================

    if (
        sesion["activa"]
        and time.time() - ultimo_comando > TIMEOUT
    ):
        hablar("Sesión finalizada")
        sesion["activa"] = False
        continue

    # =====================================================
    # VACÍO
    # =====================================================

    if not comando:
        continue

    # =====================================================
    # WAKE WORD
    # =====================================================

    if not sesion["activa"]:
        if not detectar_wakeword(comando, WAKE_WORD):
            continue

        sesion["activa"] = True
        ultimo_comando   = time.time()
        hablar("¿En qué puedo ayudarte?")

        # FIX: recalibrar el ruido de fondo en cada nueva sesión,
        # no solo al arrancar el programa. Si el volumen del juego
        # o el ambiente cambió, esto evita que el micrófono se
        # quede con un umbral desactualizado y corte palabras.
        recalibrar()
        continue

    # =====================================================
    # CANCELACIÓN DESDE EL LOOP PRINCIPAL
    # Captura cancelaciones que llegan mientras el asistente
    # no está en una operación larga (ej: preguntando algo)
    # =====================================================

    if es_cancelacion(comando):
        sesion["cancelar"] = True
        hablar("Cancelado")
        sesion["activa"] = False
        continue

    # =====================================================
    # TERMINAR SESIÓN
    # =====================================================

    if es_despedida(comando):
        hablar("Hasta luego")
        sesion["activa"] = False
        continue

    # =====================================================
    # DEBUG
    # =====================================================

    print("Escuché:", comando)
    ultimo_comando = time.time()

    # =====================================================
    # DETECCIÓN RÁPIDA
    # =====================================================

    acciones = []

    try:
        intent_rapido, valor_rapido = detectar_intent(comando)
    except Exception as e:
        print("Error intents:", e)
        intent_rapido = None
        valor_rapido  = None

    # =====================================================
    # SISTEMA DE REGLAS
    # =====================================================

    if intent_rapido and valor_rapido:
        print("Intent rápido:", intent_rapido, valor_rapido)
        acciones = [(intent_rapido, valor_rapido)]

    # =====================================================
    # IA
    # =====================================================

    else:
        acciones = interpretar_con_ia(comando)
        print("Acciones IA:", acciones)

    # =====================================================
    # LA IA NO RESPONDIÓ A TIEMPO
    # FIX: interpretar_con_ia devuelve None (no []) cuando Ollama
    # tardó demasiado o falló — normalmente porque la GPU está
    # ocupada (ej: un juego corriendo). En ese caso NO intentamos
    # la charla libre, porque sería otra llamada a un Ollama que
    # ya sabemos que está lento, y solo añadiría otra espera larga.
    # Se avisa y se sigue, en vez de quedarse callado e indefinido.
    # =====================================================

    if acciones is None:
        ultimo_comando = time.time()
        hablar("Se está demorando mucho en responder, intenta de nuevo en un momento")
        continue

    # =====================================================
    # DESPEDIDA DETECTADA POR LA IA
    # FIX: es_despedida() solo atrapa frases ya conocidas de una
    # lista. Para cualquier otra forma de despedirse ("ya quedé
    # así", "no necesito nada más", "nos vemos"...), la IA la
    # reconoce como la acción terminar_sesion en vez de caer en
    # la charla libre sin sentido.
    # =====================================================

    if any(intent == "terminar_sesion" for intent, _ in acciones):
        hablar("Hasta luego")
        sesion["activa"] = False
        continue

    # =====================================================
    # SIN ACCIONES
    # FIX: antes esto siempre respondía lo mismo ("No entendí
    # qué acción quieres realizar"), sin importar qué dijeras.
    # Ahora, si no hay un comando claro, se le pide al modelo
    # una respuesta conversacional (saludo, pregunta, pedir que
    # aclare, etc.) en vez de la frase fija.
    # =====================================================

    if not acciones:
        respuesta_libre = None
        try:
            respuesta_libre = responder_charla(comando)
        except Exception as e:
            print("Error en charla:", e)

        # FIX: reiniciar el timeout DESPUÉS de la respuesta, no antes,
        # para que el tiempo de espera empiece a contar desde que el
        # usuario ya escuchó la respuesta y no desde antes.
        ultimo_comando = time.time()
        hablar(respuesta_libre or "No entendí qué quieres que haga, ¿puedes repetirlo?")
        continue

    # =====================================================
    # EJECUTAR
    # =====================================================

    ejecuto = False

    for intent, valor in acciones:
        try:
            resultado = ejecutar(intent, valor)
            if resultado:
                ejecuto = True
        except Exception as e:
            print("Error ejecutando:", e)

    # =====================================================
    # RESPUESTA FINAL
    # FIX: antes solo se preguntaba "¿Algo más?" si la acción
    # tuvo éxito. Si fallaba (ej: "no encontré la app"), el
    # asistente se quedaba callado después del mensaje de error
    # de executor.py, y el timeout de sesión seguía contando
    # desde ANTES de ejecutar la acción. Si la búsqueda tardaba
    # más que el timeout (por ejemplo buscar en todo el disco),
    # la sesión se cerraba en silencio apenas terminaba, sin
    # darle al usuario otra oportunidad de responder.
    #
    # Ahora, haya funcionado o no, se reinicia el timeout DESPUÉS
    # de ejecutar y siempre se pregunta "¿algo más?" (el motivo
    # del fallo ya lo dijo executor.py antes), dando una nueva
    # ventana de tiempo para responder en vez de cortar la sesión.
    # =====================================================

    ultimo_comando = time.time()
    hablar("¿Algo más?")