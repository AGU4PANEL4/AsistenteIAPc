import sys
import time
import atexit
from logger import log
from session import sesion, es_cancelacion, es_despedida
from voice import escuchar, escuchar_wake_word, recalibrar
from tts import hablar
from wakeword import detectar_wakeword
from intents import detectar_intent
from ia import interpretar_con_ia, responder_charla
from executor import ejecutar
from app_finder import limpiar_cache_duplicados
import threading
from app_finder import *
from recordatorios import reprogramar_pendientes as reprogramar_recordatorios
from temporizadores import reprogramar_pendientes as reprogramar_temporizadores
from gestor_ia import apagar_todo_al_salir
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

# NUEVO: si el modo híbrido de IA encendió Ollama como respaldo local
# (porque no había internet en algún momento), esto garantiza que se
# apague de nuevo al cerrar el asistente — sin importar si el cierre
# fue normal o por una excepción/Ctrl+C, atexit corre siempre. Evita
# dejar un proceso de Ollama huérfano consumiendo recursos después de
# cerrar el asistente.
atexit.register(apagar_todo_al_salir)

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

# FIX/NUEVO: mismo patrón que --activar-startup, usado por el paso
# de DESINSTALACIÓN (ver instalador.iss, [UninstallRun]). Antes ese
# paso llamaba a "schtasks /Delete" directamente, sin pasar por
# startup.py — lo cual significa que no se beneficiaba del manejo de
# permisos de administrador que sí tiene desactivar_inicio_automatico()
# (ver _es_admin()/_ejecutar_elevado() en startup.py). Si borrar una
# tarea con privilegios elevados también requiere admin (lo cual es
# probable, igual que crearla), ese paso podía fallar en silencio
# durante la desinstalación, dejando la tarea programada huérfana en
# Windows. Ahora el desinstalador llama a "AsistenteIA.exe
# --desactivar-startup" en vez de invocar schtasks directo, así
# reusa exactamente el mismo mecanismo de elevación ya probado.
if "--desactivar-startup" in sys.argv:
    print("[Startup] Eliminando inicio automático (modo desinstalador)...")
    if desactivar_inicio_automatico():
        print("[Startup] Tarea programada eliminada correctamente.")
        sys.exit(0)
    else:
        print("[Startup] No se pudo eliminar la tarea programada.")
        sys.exit(1)

from verificacion import preparar_ia, precalentar_modelo_en_segundo_plano

# =====================================================
# CONFIGURAR GROQ (primer arranque)
# NUEVO: si esta PC nunca configuró una GROQ_API_KEY (ej. es la
# primera vez que un amigo prueba el proyecto en su propio equipo),
# esto la pide de forma guiada: abre la página para crear una key
# gratis, la pide por consola, y la valida con una llamada real antes
# de guardarla — ver setup_groq.py para el detalle completo. Si la
# key ya estaba configurada de antes, esta llamada no hace nada y
# retorna de inmediato, así que no se repite en cada arranque.
#
# Se hace ANTES de preparar_ia() (que instala/arranca Ollama) a
# propósito: si el usuario configura Groq con éxito acá, puede que
# ni necesite que Ollama esté listo para empezar a usar el asistente
# normalmente mientras haya internet.
# =====================================================

from setup_groq import asegurar_groq_configurado
asegurar_groq_configurado()

# =====================================================
# CONFIG
# =====================================================

TIMEOUT = 20
ultimo_comando = time.time()

if not preparar_ia():
    print("No se pudo preparar la IA.")
    time.sleep(10)
    exit()

# FIX/NUEVO: gestor_ia.motor_a_usar() decide si usar Groq u Ollama
# según haya internet, y de paso apaga/enciende Ollama para que quede
# en el estado correcto. Antes, esto pasaba DENTRO de la primera
# llamada real de IA (interpretar_con_ia / responder_charla), es
# decir: el usuario decía la wake word, daba su primer comando, y
# ahí recién se detectaba el internet y se disparaba el taskkill de
# Ollama — que tarda ~1-2 segundos y bloqueaba esa primera respuesta,
# haciendo que el asistente se sintiera "colgado" justo después del
# primer comando.
#
# Ahora se llama UNA VEZ acá, durante el arranque (donde el usuario
# ya espera una pausa), así el estado de Ollama queda resuelto ANTES
# de entrar al loop de escucha. Si hay internet: Ollama se apaga acá,
# antes de que nadie haya dicho nada. Si no hay internet: Ollama ya
# está arriba (lo dejó preparar_ia()), y motor_a_usar() lo confirma
# sin hacer nada extra. En ambos casos, la primera interacción real
# ya no paga ese costo.
#
# precalentar_modelo_en_segundo_plano() solo tiene sentido si Ollama
# va a usarse de verdad (hay conexión a internet → Groq, no Ollama),
# así que solo se lanza si motor_a_usar() decidió que el motor a usar
# es Ollama — si hay internet y se va a usar Groq, precalentar sería
# encender Ollama para nada y luego apagarlo de inmediato.
from gestor_ia import motor_a_usar
motor_inicial = motor_a_usar()

if motor_inicial == "ollama":
    # FIX: precalentar solo tiene sentido si se va a usar Ollama —
    # ver el comentario completo anterior arriba.
    precalentar_modelo_en_segundo_plano()
else:
    print(f"[IA] Motor seleccionado: Groq (hay internet). "
          f"Ollama apagado durante el arranque.")

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

# FIX/NUEVO: si había recordatorios o temporizadores pendientes
# guardados de una sesión anterior, se reprograman aquí. Los que ya
# vencieron mientras el asistente estaba apagado se avisan ahora mismo
# (ver reprogramar_pendientes en recordatorios.py / temporizadores.py).
# Se hace en hilos para no demorar el arranque si hubiera varios
# vencidos a la vez — cada hablar() ya está protegido contra
# solaparse gracias al lock agregado en tts.py.
threading.Thread(target=reprogramar_recordatorios, daemon=True).start()
threading.Thread(target=reprogramar_temporizadores, daemon=True).start()

# =====================================================
# LOOP PRINCIPAL
# =====================================================

# NUEVO: ver bloque TIMEOUT SESIÓN más abajo — controla si ya se
# avisó "¿sigues ahí?" en el período de silencio actual, para no
# repetir el aviso en cada vuelta del loop antes del cierre real.
aviso_inactividad_dado = False

# NUEVO: distingue "estoy esperando la respuesta AL AVISO de
# inactividad" de un comando normal cualquiera — ver el FIX en el
# bloque VACÍO más abajo, que es donde esto se usa.
esperando_respuesta_aviso = False

# NUEVO: si hablar(..., permitir_interrupcion=True) devuelve un
# texto (ver tts.py), significa que el usuario interrumpió hablando
# mientras el asistente decía algo — ese texto YA ES el próximo
# comando del usuario. Se guarda acá para usarlo en la siguiente
# vuelta del loop en vez de volver a llamar a escuchar() (lo cual
# haría que el usuario tuviera que repetir lo que ya dijo durante
# la interrupción).
comando_pendiente = None

while True:
    try:

        # FIX: mientras se espera la wake word, se usa escuchar_wake_word()
        # en vez de escuchar() normal — usa un initial_prompt con la wake
        # word configurada y más beam_size, lo cual mejora mucho la
        # detección de nombres propios/palabras cortas dichas solas (ver
        # escuchar_wake_word en voice.py para el detalle). Una vez que la
        # sesión está activa, se vuelve a escuchar() normal para comandos,
        # que no necesita ese sesgo y es más rápido sin él.
        #
        # NUEVO: si ya hay un comando_pendiente (capturado por una
        # interrupción mientras el asistente hablaba), se usa ESE en vez
        # de escuchar de nuevo — el usuario ya dijo lo que quería decir,
        # no hace falta pedírselo otra vez.
        if comando_pendiente is not None:
            comando           = comando_pendiente
            comando_pendiente = None
        elif sesion["activa"]:
            comando = escuchar()
        else:
            comando = escuchar_wake_word(WAKE_WORD)

        # =====================================================
        # TIMEOUT SESIÓN
        # FIX: antes la sesión se cerraba en silencio apenas se cumplían
        # los 20s sin actividad — sin ningún aviso previo. Si el usuario
        # estaba pensando qué decir, se encontraba con "Sesión finalizada"
        # de la nada y tenía que repetir la wake word para seguir, lo cual
        # se siente como una interrupción brusca en vez de una
        # conversación natural.
        #
        # Ahora hay un aviso intermedio a los AVISO_INACTIVIDAD segundos
        # ("¿sigues ahí?"), UNA sola vez por período de silencio (la
        # bandera aviso_inactividad_dado evita repetirlo en cada vuelta
        # del loop mientras se sigue esperando). Si después del aviso
        # llega CUALQUIER audio no vacío, se trata como actividad normal
        # — no hace falta que el usuario confirme nada explícito, basta
        # con que diga algo para que la sesión siga (ver más abajo, donde
        # se reinicia ultimo_comando y se resetea la bandera apenas llega
        # un comando no vacío). Si no llega nada en los TIMEOUT segundos
        # totales, se cierra exactamente igual que antes.
        # =====================================================

        tiempo_inactivo = time.time() - ultimo_comando

        # FIX: el bug real era de ORDEN. escuchar() puede tardar hasta su
        # propio timeout (5s) bloqueada esperando que el usuario hable.
        # Si el usuario reaccionaba al aviso "¿Sigues ahí?" pero tardaba
        # un poco en empezar a hablar, para cuando escuchar() finalmente
        # capturaba la frase y retornaba, el RELOJ de tiempo_inactivo ya
        # podía haber superado los 20s — y como el chequeo de TIMEOUT se
        # hacía ANTES de mirar si `comando` ya tenía algo válido, la
        # sesión se cerraba ignorando por completo que el usuario SÍ
        # había hablado, solo que la captura tardó en completarse. Por
        # eso aparecía "Sesión finalizada" seguido de "Te escucho, dime
        # qué necesitas" — la respuesta llegó, pero después de que el
        # código ya había decidido cerrar la sesión sin mirarla.
        #
        # Ahora, si `comando` ya tiene algo (no vacío), eso por sí solo
        # ya demuestra que el usuario está presente — el cierre por
        # timeout solo aplica cuando de verdad no se capturó nada.
        if sesion["activa"] and not comando and tiempo_inactivo > TIMEOUT:
            hablar("Sesión finalizada")
            sesion["activa"]          = False
            aviso_inactividad_dado    = False
            continue

        AVISO_INACTIVIDAD = 12

        if (
            sesion["activa"]
            and not comando
            and not aviso_inactividad_dado
            and tiempo_inactivo > AVISO_INACTIVIDAD
        ):
            hablar("¿Sigues ahí?")
            aviso_inactividad_dado    = True
            esperando_respuesta_aviso = True
            continue

        # =====================================================
        # VACÍO
        # =====================================================

        if not comando:
            continue

        # NUEVO: cualquier audio no vacío cuenta como "sigo aquí" — se
        # resetea la bandera de aviso para que, si la sesión vuelve a
        # quedarse en silencio más adelante, se pueda avisar de nuevo en
        # ese nuevo período (sin esto, el aviso solo se daría una vez en
        # toda la sesión, no una vez por cada período de silencio).
        aviso_inactividad_dado = False

        # FIX: si esto es la respuesta AL AVISO "¿Sigues ahí?", no debe
        # pasar por despedida/cancelación/IA — el usuario solo está
        # confirmando presencia, no dando un comando real. Sin esto,
        # respuestas naturales como "sí, aquí sigo" o "sí, sigo aquí"
        # podían interpretarse como despedida (la IA las asociaba con
        # frases de cierre tipo "ya quedé así" por la ambigüedad de
        # "sigo aquí" sin contexto de que se le había preguntado algo).
        # Como ya sabemos que el propósito de ESTA respuesta puntual es
        # solo señal de presencia, se confirma directo y se espera al
        # siguiente turno para el comando real.
        if esperando_respuesta_aviso:
            esperando_respuesta_aviso = False
            ultimo_comando            = time.time()
            hablar("Te escucho, dime qué necesitas")
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
            sesion["cancelar"]        = True
            hablar("Cancelado")
            sesion["activa"]          = False
            esperando_respuesta_aviso = False
            continue

        # =====================================================
        # TERMINAR SESIÓN
        # =====================================================

        if es_despedida(comando):
            hablar("Hasta luego")
            sesion["activa"]          = False
            esperando_respuesta_aviso = False
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
            sesion["activa"]          = False
            esperando_respuesta_aviso = False
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

            # NUEVO: permitir_interrupcion=True — si el usuario empieza a
            # hablar mientras el asistente todavía está diciendo esta
            # respuesta, se corta de inmediato y lo que dijo se captura
            # como el próximo comando (ver comando_pendiente más arriba),
            # en vez de obligarlo a esperar que termine de hablar.
            comando_pendiente = hablar(
                respuesta_libre or "No entendí qué quieres que haga, ¿puedes repetirlo?",
                permitir_interrupcion=True
            )
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

        # NUEVO: mismo mecanismo de barge-in que en la respuesta de charla
        # libre — "¿Algo más?" es el mensaje que más se repite en una
        # conversación típica, así que es donde más se nota la espera de
        # tener que aguantar a que termine de hablar antes de poder decir
        # el siguiente comando.
        comando_pendiente = hablar("¿Algo más?", permitir_interrupcion=True)
    except Exception as e:
        # FIX/NUEVO: antes, cualquier excepcion no manejada en
        # cualquier punto del loop principal tiraba abajo TODO el
        # proceso del asistente, sin dejar ningun rastro util de
        # que paso (el usuario solo veia la consola cerrada, o el
        # traceback se perdia si no estaba mirando en ese momento).
        # Ahora se registra el error completo (con traceback) en el
        # log persistente, y el loop SIGUE vivo en la siguiente
        # vuelta en vez de morir -- un fallo puntual en un ciclo no
        # deberia tirar abajo toda la sesion del asistente.
        log.exception(f"Error no manejado en el loop principal: {e}")
        try:
            hablar("Tuve un error inesperado, sigamos")
        except Exception:
            pass
        continue