import sys
import time
import atexit
import ctypes
from logger import log
from session import sesion, es_cancelacion, es_despedida, es_repetir, es_dormir, DESPIERTA_WORD
import no_molestar

# =====================================================
# MANEJO DE CRASHES EN EL .EXE (sin consola)
# Con console=False en el .spec, si el proceso muere por una
# excepción no manejada, simplemente desaparece sin dejar
# ningún rastro visible. En vez de redirigir stdout (que
# interfiere con pygame/faster-whisper que llaman a fileno()),
# se instala un hook global que:
#   1. Escribe el traceback completo en el log persistente.
#   2. Muestra un messagebox de Windows con el error, para
#      que el usuario sepa qué pasó en vez de ver nada.
# Cuando corre desde VS Code / terminal (frozen=False) este
# bloque no se ejecuta — la consola sigue igual que siempre.
# =====================================================

if getattr(sys, "frozen", False):
    import traceback
    import ctypes as _ctypes

    def _crash_handler(exc_type, exc_value, exc_tb):
        texto = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        # escribir al log
        try:
            from logger import ARCHIVO_LOG
            with open(ARCHIVO_LOG, "a", encoding="utf-8") as f:
                f.write("\n[CRASH]\n" + texto + "\n")
        except Exception:
            pass
        # mostrar messagebox (disponible porque tenemos tkinter)
        try:
            _ctypes.windll.user32.MessageBoxW(
                0,
                f"El asistente se cerró por un error:\n\n{exc_value}\n\n"
                f"Revisa el log en:\n%LOCALAPPDATA%\\AsistenteIA\\asistente.log",
                "AsistenteIA — Error",
                0x10  # MB_ICONERROR
            )
        except Exception:
            pass

    sys.excepthook = _crash_handler

# =====================================================
# MUTEX DE INSTANCIA ÚNICA
# Registra un mutex nombrado en Windows para que:
# 1. El instalador (instalador.iss, CheckForMutexes) pueda
#    detectar si el asistente está corriendo antes de instalar.
# 2. Evitar que el usuario abra dos instancias del asistente
#    al mismo tiempo (dos instancias peleando por el micrófono
#    causaría comportamiento impredecible).
# El mutex se libera automáticamente cuando el proceso termina.
# =====================================================

_MUTEX_NOMBRE = "AsistenteIA_Running"
_mutex_handle = None

try:
    _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, _MUTEX_NOMBRE)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        print(f"[Main] Ya hay una instancia del asistente corriendo. Cerrando.")
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        sys.exit(1)
except Exception as e:
    print(f"[Main] No se pudo crear el mutex de instancia única: {e}")

# =====================================================
# VENTANA DE CARGA (splash)
# FIX/NUEVO: antes, todo lo que sigue (imports pesados, preparar
# Ollama, configurar Groq, etc.) corría en la consola sin nada
# visible — en el .exe empaquetado (console=False) eso significaba
# varios segundos donde el programa parecía no haber hecho nada. El
# splash se muestra ACÁ, lo antes posible (antes de los imports
# pesados de abajo), y main.py va actualizando su texto de estado en
# cada etapa (ver splash.py) — se cierra recién cuando la interfaz
# principal (ui.py) ya está lista para mostrarse.
# =====================================================

from splash import mostrar_splash, actualizar_splash, cerrar_splash
mostrar_splash()
actualizar_splash("Cargando módulos...")

try:
    from voice import escuchar, escuchar_wake_word, recalibrar
    from tts import hablar, ultimo_mensaje
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
    from config import WAKE_WORD
    from startup import (
        activar_inicio_automatico,
        desactivar_inicio_automatico,
        startup_activado
    )
except Exception as _import_err:
    cerrar_splash()
    import traceback, ctypes as _ct
    _ct.windll.user32.MessageBoxW(
        0,
        f"Error al cargar módulos del asistente:\n\n{_import_err}\n\n"
        f"Revisa el log en:\n%LOCALAPPDATA%\\AsistenteIA\\asistente.log",
        "AsistenteIA — Error de inicio",
        0x10
    )
    try:
        from logger import log
        log.exception("Error de importación al arrancar")
    except Exception:
        pass
    sys.exit(1)

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
# ACTUALIZACIONES AUTOMÁTICAS
# Se verifica ACÁ, mientras el splash todavía está visible y ANTES
# de configurar Groq/Ollama — si hay una actualización y el usuario
# decide instalarla, no tiene sentido perder tiempo preparando IA
# que se va a descartar apenas el instalador reemplace esta versión.
#
# FIX/NUEVO: antes esto corría en background durante toda la sesión
# y avisaba por VOZ en medio de la conversación (ver actualizador.py
# para el detalle completo del rediseño). Ahora se resuelve acá, con
# una ventana (ver setup_actualizacion_gui.py), antes de que la
# sesión de voz siquiera empiece.
#
# FIX/NUEVO: además, esto solo corre si el proceso está "frozen"
# (el .exe empaquetado) — antes corría igual corriendo desde código
# fuente (ej. python main.py en VS Code), lo cual era confuso durante
# el desarrollo: el config.json comparte la misma carpeta de datos
# que la instalación real, así que un chequeo de versión mientras se
# programa podía disparar un aviso de "actualización disponible" sin
# relación con el código que se está editando en ese momento. No
# tiene sentido descargar/instalar un .exe de todas formas sobre un
# entorno de desarrollo.
# =====================================================

if getattr(sys, "frozen", False):
    actualizar_splash("Buscando actualizaciones...")
    from actualizador import verificar_actualizacion_arranque
    if not verificar_actualizacion_arranque(callback_progreso=actualizar_splash):
        # el asistente se está cerrando para instalar la actualización
        # (en la práctica, verificar_actualizacion_arranque() ya hizo
        # sys.exit(0) antes de llegar acá — esto es solo un resguardo)
        cerrar_splash()
        sys.exit(0)
else:
    print("[Actualizador] Corriendo desde código fuente — se omite la "
          "verificación de actualizaciones.")

# =====================================================
# CONFIGURAR GROQ (primer arranque)
# FIX/NUEVO: antes esto pedía la key por consola (input()), lo cual
# se rompe en el .exe empaquetado (console=False, ver
# asistente.spec) — sin consola, ese input() lanzaba una excepción
# que tumbaba el arranque completo antes de mostrar nada. Ahora se
# usa una ventana gráfica (ver setup_groq_gui.py) que abre la
# página para crear la key, la pide, la valida con una llamada
# real, y permite omitir el paso — mismo comportamiento que antes,
# pero funcionando también sin consola.
#
# Si la key ya estaba configurada de antes, esto no hace nada y
# retorna de inmediato, así que no se repite en cada arranque.
#
# Se hace ANTES de preparar_ia() (que instala/arranca Ollama) a
# propósito: si el usuario configura Groq con éxito acá, puede que
# ni necesite que Ollama esté listo para empezar a usar el asistente
# normalmente mientras haya internet.
# =====================================================

actualizar_splash("Configurando IA...")
from setup_groq_gui import asegurar_groq_configurado_gui
asegurar_groq_configurado_gui()

# =====================================================
# CONFIG
# =====================================================

TIMEOUT = 20
ultimo_comando = time.time()

actualizar_splash("Preparando IA local...")
if not preparar_ia(callback_progreso=actualizar_splash):
    cerrar_splash()
    print("No se pudo preparar la IA.")
    # FIX/NUEVO: antes esto solo hacía print() + sleep(10) — invisible
    # en el .exe empaquetado (console=False), así que el usuario solo
    # veía el splash cerrarse y el proceso desaparecer sin ninguna
    # explicación. Mismo patrón que el crash handler y el error de
    # imports de más arriba: un messagebox de Windows que sí se ve
    # sin consola, explicando qué pasó y dónde revisar el log.
    log.error("preparar_ia() falló durante el arranque — el asistente "
              "no puede continuar sin Ollama ni Groq disponibles")
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            "No se pudo preparar la IA local (Ollama).\n\n"
            "Revisa tu conexión a internet e intenta abrir el "
            "asistente de nuevo.\n\nSi el problema sigue, revisa el "
            "log en:\n%LOCALAPPDATA%\\AsistenteIA\\asistente.log",
            "AsistenteIA — Error de inicio",
            0x10  # MB_ICONERROR
        )
    except Exception:
        pass
    sys.exit(1)

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
actualizar_splash("Verificando conexión...")
from gestor_ia import motor_a_usar
motor_inicial = motor_a_usar()

if motor_inicial == "ollama":
    precalentar_modelo_en_segundo_plano()
else:
    print(f"[IA] Motor seleccionado: Groq (hay internet). "
          f"Ollama apagado durante el arranque.")

# =====================================================
# INTERFAZ FLOTANTE
# =====================================================

actualizar_splash("Abriendo interfaz...")

from ui import iniciar_ui
from ui_estado import (
    set_modo, set_motor_ia, set_wake_word, agregar_historial
)

# FIX/NUEVO: antes se llamaba iniciar_ui() (que crea su PROPIO
# tk.Tk() en su propio hilo para el orbe flotante) ANTES de
# cerrar_splash() — durante ese instante convivían dos roots de
# Tkinter en dos hilos distintos (el del splash, todavía cerrando, y
# el de la UI principal, recién creado). Ahora se cierra el splash
# PRIMERO y se espera (cerrar_splash ya hace join(timeout=2)) a que
# su root termine de destruirse del todo antes de crear el de la UI
# principal — nunca quedan dos roots de Tkinter vivos al mismo
# tiempo. El costo es un instante sin ninguna ventana visible entre
# que el splash desaparece y el orbe aparece, imperceptible en la
# práctica frente al riesgo que evita.
cerrar_splash()
iniciar_ui()
set_motor_ia("Groq" if motor_inicial == "groq" else "Ollama")
set_wake_word(WAKE_WORD)

# =====================================================
# INICIO
# =====================================================

asegurar_archivos()

# FIX/NUEVO: antes acá se preguntaba por consola (input()) si el
# usuario quería inicio automático con Windows — mismo problema que
# el setup de Groq: se rompe en el .exe empaquetado (sin consola) y
# tumbaba el arranque. Se quita del todo, sin reemplazarla por una
# ventana equivalente, porque ya no hace falta: el instalador
# (instalador.iss) ofrece esta misma opción como una casilla durante
# la instalación (ver [Tasks] "startupauto"), que internamente llama
# a "AsistenteIA.exe --activar-startup" (ver el bloque de arriba) con
# el mismo manejo de permisos de administrador. Si alguien lo omitió
# ahí, puede activarlo en cualquier momento diciéndole al asistente
# "activa el inicio automático" (ver activar_startup en
# acciones_sistema.py / tools.py) — mismo mecanismo, sin duplicar
# lógica ni pedir nada extra al arrancar.

print("[Sistema] Iniciando asistente...")

threading.Thread(target=indexar_apps,         daemon=True).start()
threading.Thread(target=indexar_juegos,          daemon=True).start()

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
        elif sesion["dormido"]:
            # NUEVO: en modo dormido, se escucha con el mismo mecanismo
            # de la wake word pero sesgado hacia la palabra de
            # despertar en vez de la wake word normal — ver el manejo
            # completo más abajo, en la sección WAKE WORD.
            comando = escuchar_wake_word(DESPIERTA_WORD)
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
            # NUEVO: mientras está dormido, se ignora la wake word
            # normal por completo — lo único que se revisa es si esto
            # fue la palabra de despertar. Cualquier otra cosa dicha
            # mientras está "dormido" se descarta sin más (ni se
            # activa sesión, ni se procesa como comando, ni cambia el
            # estado visual a "escuchando" — se revisa ANTES de eso a
            # propósito, para que la UI se mantenga en "Durmiendo..."
            # de forma estable en vez de parpadear).
            if sesion["dormido"]:
                if detectar_wakeword(comando, DESPIERTA_WORD):
                    sesion["dormido"] = False
                    set_modo("escuchando")
                    hablar("Ya estoy de vuelta")
                    # NUEVO: esto reproduce cualquier recordatorio/
                    # temporizador que haya sonado MIENTRAS estaba
                    # dormido (quedaron diferidos por no_molestar en
                    # vez de interrumpir el silencio) — si no quedó
                    # nada pendiente, no dice nada de más.
                    #
                    # FIX: solo se desactiva no_molestar acá si fue
                    # "duérmete" quien lo activó (ver
                    # sesion["dormido_activo_no_molestar"], escrito en
                    # el bloque de es_dormir() más abajo). Si ya
                    # estaba activo DE ANTES por su cuenta (el usuario
                    # lo había puesto manualmente, con su propia
                    # duración), no se toca — antes esto lo cortaba
                    # siempre, aunque el usuario hubiera pedido
                    # explícitamente, por ejemplo, "no molestar por 2
                    # horas" y todavía le quedara la mayor parte de
                    # ese tiempo.
                    if sesion["dormido_activo_no_molestar"]:
                        no_molestar.desactivar()
                        sesion["dormido_activo_no_molestar"] = False
                continue

            set_modo("escuchando")
            if not detectar_wakeword(comando, WAKE_WORD):
                continue

            sesion["activa"] = True
            ultimo_comando   = time.time()
            set_modo("hablando")
            hablar("¿En qué puedo ayudarte?")

            # FIX: recalibrar el ruido de fondo en cada nueva sesión,
            # no solo al arrancar el programa. Si el volumen del juego
            # o el ambiente cambió, esto evita que el micrófono se
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
            set_modo("inactivo")
            continue

        # =====================================================
        # TERMINAR SESIÓN
        # =====================================================

        if es_despedida(comando):
            hablar("Hasta luego")
            sesion["activa"]          = False
            esperando_respuesta_aviso = False
            set_modo("inactivo")
            continue

        # =====================================================
        # MODO DORMIDO
        # NUEVO: ver es_dormir() en session.py — suspende la reacción
        # a la wake word normal hasta que se diga la palabra de
        # despertar. Termina la sesión igual que una despedida, pero
        # deja marcado sesion["dormido"] para que la sección WAKE WORD
        # de más arriba ignore la wake word normal hasta despertar.
        #
        # FIX/NUEVO: al principio, dormido solo afectaba la wake
        # word — un recordatorio o temporizador programado para
        # sonar mientras el usuario estaba "dormido" lo interrumpía
        # igual, hablando en voz alta, aunque el usuario hubiera
        # pedido explícitamente silencio. Ahora dormir TAMBIÉN activa
        # no_molestar (ver no_molestar.py) — recordatorios.py y
        # temporizadores.py ya consultan no_molestar.modo_activo()
        # antes de hablar sus avisos, así que esto los difiere en vez
        # de interrumpir, y se reproducen solos al despertar (ver el
        # bloque de "despierta" más arriba).
        #
        # Se usa una duración larga (12 horas) en vez de "indefinida"
        # porque no_molestar.activar() está pensado para una duración
        # concreta — 12 horas alcanza de sobra para cualquier siesta
        # real, y desactivar() al despertar corta el modo de
        # inmediato de todas formas, sin esperar a que se cumplan las
        # 12 horas.
        #
        # FIX: antes esto llamaba a no_molestar.activar(60*12) SIEMPRE,
        # sin importar si ya estaba activo por su cuenta — si el
        # usuario había puesto "no molestar por 2 horas" y DESPUÉS
        # decía "duérmete", esto pisaba esas 2 horas con 12, y al
        # despertar (ver el bloque de "despierta" más arriba) se
        # cortaba TODO de inmediato — el usuario perdía por completo
        # la duración que había elegido a propósito. Ahora solo se
        # activa (y se marca como "nuestro" para desactivarlo después)
        # si no_molestar NO estaba ya activo — si ya lo estaba, se
        # respeta tal cual, sin tocar su duración ni desactivarlo
        # antes de tiempo al despertar.
        # =====================================================

        if es_dormir(comando):
            hablar(f"Me quedo en silencio. Decí \"{DESPIERTA_WORD}\" cuando me necesites")
            sesion["activa"]          = False
            sesion["dormido"]         = True

            ya_estaba_activo = no_molestar.modo_activo()
            sesion["dormido_activo_no_molestar"] = not ya_estaba_activo
            if not ya_estaba_activo:
                no_molestar.activar(60 * 12)

            esperando_respuesta_aviso = False
            set_modo("dormido")
            continue

        # =====================================================
        # REPETIR ÚLTIMO MENSAJE
        # NUEVO: ver es_repetir() en session.py / ultimo_mensaje() en
        # tts.py — no cuenta como un comando real, así que no pasa
        # por intents/IA, solo repite lo último que se dijo (o avisa
        # que todavía no se dijo nada en esta sesión).
        # =====================================================

        if es_repetir(comando):
            ultimo_comando = time.time()
            texto_previo   = ultimo_mensaje()
            if texto_previo:
                hablar(texto_previo)
            else:
                hablar("Todavía no dije nada")
            continue

        # =====================================================
        # DEBUG
        # =====================================================

        print("Escuché:", comando)
        ultimo_comando = time.time()
        set_modo("procesando")

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

        # actualizar motor en la UI (puede cambiar si la conectividad cambió)
        try:
            from gestor_ia import motor_a_usar as _motor
            set_motor_ia("Groq" if _motor() == "groq" else "Ollama")
        except Exception:
            pass

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
            # FIX/NUEVO: antes el mensaje era genérico "Se está demorando
            # mucho", que solo describe el caso de Ollama lento por GPU
            # saturada. Ahora cubre también el caso donde Groq Y Ollama
            # fallaron por motivos distintos (sin internet + Ollama caído,
            # o cuota de Groq agotada + Ollama no instalado, etc.).
            # El mensaje sigue siendo una sola frase para no confundir,
            # pero distingue la causa real para que el usuario sepa qué
            # esperar — "en un momento" aplica al caso de GPU ocupada,
            # "revisa tu conexión" al de ambos motores caídos.
            from conectividad import hay_internet
            from verificacion import ollama_ejecutandose
            if not hay_internet(forzar=True) and not ollama_ejecutandose():
                hablar("No tengo forma de procesar eso ahora: no hay internet y Ollama no está disponible")
            else:
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
            ia_fallo        = False
            try:
                respuesta_libre = responder_charla(comando)
            except Exception as e:
                print("Error en charla:", e)

            if respuesta_libre is None:
                from conectividad import hay_internet
                from verificacion import ollama_ejecutandose
                if not hay_internet(forzar=True) and not ollama_ejecutandose():
                    respuesta_libre = ("No tengo forma de procesar eso ahora: "
                                      "no hay internet y Ollama no está disponible")
                    ia_fallo = True

            ultimo_comando = time.time()
            set_modo("hablando")
            agregar_historial(comando, respuesta_libre or "")

            comando_pendiente = hablar(
                respuesta_libre or "No entendí qué quieres que haga, ¿puedes repetirlo?",
                permitir_interrupcion=not ia_fallo,
            )
            set_modo("escuchando")
            continue

        # =====================================================
        # EJECUTAR
        # =====================================================

        ejecuto = False

        set_modo("procesando")
        agregar_historial(comando)

        for intent, valor in acciones:
            try:
                resultado = ejecutar(intent, valor)
                if resultado:
                    ejecuto = True
            except Exception as e:
                print("Error ejecutando:", e)

        set_modo("hablando")

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

        # FIX/NUEVO: antes acá se revisaba hay_actualizacion_pendiente()
        # y, si había una actualización lista, se avisaba por VOZ antes
        # de "¿Algo más?" — una interrupción fuera de contexto en medio
        # de la conversación normal. Ese chequeo ahora se hace ANTES de
        # que la sesión de voz empiece, con una ventana durante el
        # splash (ver verificar_actualizacion_arranque en
        # actualizador.py), así que ya no hace falta nada acá.

        comando_pendiente = hablar("¿Algo más?", permitir_interrupcion=True)
        set_modo("escuchando")
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