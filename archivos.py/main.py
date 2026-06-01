import time
from config import WAKE_WORD
from session import sesion
from voice import escuchar
from tts import hablar
from wakeword import detectar_wakeword
from intents import detectar_intent
from ia import interpretar_con_ia
from executor import ejecutar
from app_finder import limpiar_cache_duplicados
import threading
from app_finder import *

# =====================================================
# CONFIG
# =====================================================

TIMEOUT = 20

ultimo_comando = time.time()


# =====================================================
# INICIO
# =====================================================

print(
    "[Sistema] Iniciando asistente..."
)
threading.Thread(
    target=indexar_apps,
    daemon=True
).start()

threading.Thread(
    target=indexar_juegos_steam,
    daemon=True
).start()

try:

    limpiar_cache_duplicados()

except Exception as e:

    print(
        "Error limpiando cache:",
        e
    )

print(
    "[Sistema] Asistente listo"
)


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

        and

        time.time()

        - ultimo_comando

        > TIMEOUT

    ):

        hablar(
            "Sesión finalizada"
        )

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

        if not detectar_wakeword(

            comando,

            WAKE_WORD

        ):

            continue


        sesion["activa"] = True

        ultimo_comando = time.time()

        hablar(
            "¿En qué puedo ayudarte?"
        )

        continue


    # =====================================================
    # TERMINAR SESIÓN
    # =====================================================

    if comando.lower().strip() in [

        "termina",

        "adiós",

        "gracias",

        "nada más",

        "eso es todo"

    ]:

        hablar(
            "Hasta luego"
        )

        sesion["activa"] = False

        continue


    # =====================================================
    # DEBUG
    # =====================================================

    print(
        "Escuché:",
        comando
    )

    ultimo_comando = time.time()


    # =====================================================
    # DETECCIÓN RÁPIDA
    # =====================================================

    acciones = []


    try:

        intent_rapido, valor_rapido = detectar_intent(
            comando
        )

    except Exception as e:

        print(
            "Error intents:",
            e
        )

        intent_rapido = None
        valor_rapido = None


    # =====================================================
    # SISTEMA DE REGLAS
    # =====================================================

    if (

        intent_rapido

        and

        valor_rapido

    ):

        print(

            "Intent rápido:",

            intent_rapido,

            valor_rapido

        )

        acciones = [

            (

                intent_rapido,

                valor_rapido

            )

        ]


    # =====================================================
    # IA
    # =====================================================

    else:

        acciones = interpretar_con_ia(
            comando
        )

        print(
            "Acciones IA:",
            acciones
        )


    # =====================================================
    # SIN ACCIONES
    # =====================================================

    if not acciones:

        hablar(
            "No entendí qué acción quieres realizar"
        )

        continue


    # =====================================================
    # EJECUTAR
    # =====================================================

    ejecuto = False


    for intent, valor in acciones:

        try:

            resultado = ejecutar(

                intent,

                valor

            )

            if resultado:

                ejecuto = True


        except Exception as e:

            print(
                "Error ejecutando:",
                e
            )


    # =====================================================
    # RESPUESTA FINAL
    # =====================================================

    if ejecuto:

        hablar(
            "¿Algo más?"
        )

    else:

        hablar(
            "No pude realizar esa acción"
        )