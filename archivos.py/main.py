import sys

# FIX: en Distrobox/contenedores (ej. Bazzite), el event loop por
# defecto de Python usa epoll y falla con "epoll_ctl: Invalid argument"
# por las restricciones del sandbox. La versión anterior de este fix
# reemplazaba asyncio.new_event_loop como atributo del módulo asyncio,
# pero eso NO cubre a librerías que crean su loop llamando directo a
# asyncio.events.new_event_loop() o a la política (ej. el cliente HTTP
# de Groq vía httpx/anyio) — de ahí que el error siguiera apareciendo
# más tarde, ya con el asistente corriendo.
#
# Ahora se reemplaza selectors.DefaultSelector ANTES de importar
# asyncio o cualquier otra cosa: como SelectorEventLoop() usa
# selectors.DefaultSelector() internamente si no se le pasa selector,
# esto hace que CUALQUIER loop creado en el proceso (sin importar
# quién ni cómo lo pida) use select() en vez de epoll(). No toca
# set_event_loop_policy (deprecado en 3.14+), así que tampoco genera
# el DeprecationWarning que salía antes.
if sys.platform == "linux":
    import selectors
    selectors.DefaultSelector = selectors.SelectSelector

import time
import atexit
import threading
from logger import log
from session import sesion, es_cancelacion, es_despedida, es_repetir, es_dormir, DESPIERTA_WORD
import no_molestar
import instancia
from plataforma import es_windows
from rutas_datos import CARPETA_DATOS


def _mostrar_error_fatal(titulo, texto):
    """
    Messagebox de error MULTIPLATAFORMA — reemplaza los usos sueltos
    de ctypes.windll.user32.MessageBoxW (que solo existe en Windows)
    por tkinter.messagebox, disponible en cualquier plataforma donde
    corra el asistente (Tkinter ya es una dependencia del proyecto,
    ver ui.py/splash.py). Crea su PROPIO root oculto porque estos
    errores pueden ocurrir ANTES de que exista cualquier otra ventana
    (incluso antes del splash, ej. un error de import).
    """
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(titulo, texto)
        root.destroy()
    except Exception:
        # último recurso si ni Tkinter está disponible — al menos
        # que el mensaje quede en algún lado visible.
        print(f"[{titulo}] {texto}")


# =====================================================
# MANEJO DE CRASHES EN EL .EXE (sin consola)
# =====================================================

if getattr(sys, "frozen", False):
    import traceback

    def _crash_handler(exc_type, exc_value, exc_tb):
        texto = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            from logger import ARCHIVO_LOG
            with open(ARCHIVO_LOG, "a", encoding="utf-8") as f:
                f.write("\n[CRASH]\n" + texto + "\n")
        except Exception:
            pass
        _mostrar_error_fatal(
            "AsistenteIA — Error",
            f"El asistente se cerró por un error:\n\n{exc_value}\n\n"
            f"Revisa el log en:\n{CARPETA_DATOS / 'asistente.log'}",
        )

    sys.excepthook = _crash_handler

# =====================================================
# INSTANCIA ÚNICA
# =====================================================

if not instancia.crear():
    print("[Main] Ya hay una instancia del asistente corriendo. Cerrando.")
    sys.exit(1)

# =====================================================
# APP USER MODEL ID (barra de tareas de Windows)
# =====================================================

if es_windows():
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AsistenteIA.Jarvis")
    except Exception as e:
        log.warning(f"No se pudo fijar el AppUserModelID: {e}")

# =====================================================
# VENTANA DE CARGA (splash)
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
    _mostrar_error_fatal(
        "AsistenteIA — Error de inicio",
        f"Error al cargar módulos del asistente:\n\n{_import_err}\n\n"
        f"Revisa el log en:\n{CARPETA_DATOS / 'asistente.log'}",
    )
    try:
        from logger import log
        log.exception("Error de importación al arrancar")
    except Exception:
        pass
    sys.exit(1)

atexit.register(apagar_todo_al_salir)

# =====================================================
# MODO "SOLO CONFIGURAR STARTUP"
# =====================================================

if "--activar-startup" in sys.argv:
    print("[Startup] Configurando inicio automático (modo instalador)...")
    if activar_inicio_automatico():
        print("[Startup] Tarea programada creada correctamente.")
        sys.exit(0)
    else:
        print("[Startup] No se pudo crear la tarea programada.")
        sys.exit(1)

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
# =====================================================

if getattr(sys, "frozen", False):
    actualizar_splash("Buscando actualizaciones...")
    from actualizador import verificar_actualizacion_arranque
    if not verificar_actualizacion_arranque(callback_progreso=actualizar_splash):
        cerrar_splash()
        sys.exit(0)
else:
    print("[Actualizador] Corriendo desde código fuente — se omite la "
          "verificación de actualizaciones.")

# =====================================================
# CONFIGURAR GROQ (primer arranque)
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
    log.error("preparar_ia() falló durante el arranque — el asistente "
              "no puede continuar sin Ollama ni Groq disponibles")
    _mostrar_error_fatal(
        "AsistenteIA — Error de inicio",
        "No se pudo preparar la IA local (Ollama).\n\n"
        "Revisa tu conexión a internet e intenta abrir el "
        "asistente de nuevo.\n\nSi el problema sigue, revisa el "
        f"log en:\n{CARPETA_DATOS / 'asistente.log'}",
    )
    sys.exit(1)

actualizar_splash("Verificando conexión...")
from gestor_ia import motor_a_usar
motor_inicial = motor_a_usar()

if motor_inicial == "ollama":
    precalentar_modelo_en_segundo_plano()
else:
    print(f"[IA] Motor seleccionado: Groq (hay internet). "
          f"Ollama apagado durante el arranque.")

# =====================================================
# INTERFAZ WEB (pywebview + orbe_tk)
# =====================================================

actualizar_splash("Abriendo interfaz...")

from ui_estado import (
    set_modo, set_motor_ia, set_wake_word, agregar_historial
)

# FIX/NUEVO: creamos el orbe ANTES de cerrar el splash. OrbeFlotante
# arranca en un hilo propio y tiene un Event _listo que se setea cuando
# el root de Tkinter ya está creado y listo para mostrarse. Esperamos
# a que esté listo antes de cerrar el splash, así nunca hay un gap sin
# nada visible en pantalla.
import orbe_tk

# Placeholder para el callback de expansión — se conecta de verdad
# cuando _crear_ventana_y_arrancar() crea la ventana web
_orbe_expandir_placeholder = None

def _al_expandir_orbe():
    if _orbe_expandir_placeholder:
        _orbe_expandir_placeholder()

orbe = orbe_tk.OrbeFlotante(on_expandir=_al_expandir_orbe)

# Esperamos a que el orbe esté realmente visible (su Tk está listo)
# antes de quitar el splash — máximo 3 segundos por si algo falla
try:
    orbe._listo.wait(timeout=3)
except Exception:
    pass

# Ahora sí cerramos el splash — el orbe ya está ahí, no hay gap
cerrar_splash()

set_motor_ia("Groq" if motor_inicial == "groq" else "Ollama")
set_wake_word(WAKE_WORD)

# =====================================================
# INICIO DEL ASISTENTE (loop de voz en hilo aparte)
# =====================================================

asegurar_archivos()

print("[Sistema] Iniciando asistente...")

threading.Thread(target=indexar_apps, daemon=True).start()
threading.Thread(target=indexar_juegos, daemon=True).start()

try:
    limpiar_cache_duplicados()
except Exception as e:
    print("Error limpiando cache:", e)

print("[Sistema] Asistente listo")
hablar("Asistente listo")

threading.Thread(target=reprogramar_recordatorios, daemon=True).start()
threading.Thread(target=reprogramar_temporizadores, daemon=True).start()

# =====================================================
# LOOP PRINCIPAL DE VOZ (en hilo daemon)
# =====================================================

aviso_inactividad_dado = False
esperando_respuesta_aviso = False
comando_pendiente = None

def _loop_voz():
    global ultimo_comando, aviso_inactividad_dado, esperando_respuesta_aviso, comando_pendiente
    
    while True:
        try:
            if comando_pendiente is not None:
                comando = comando_pendiente
                comando_pendiente = None
            elif sesion["activa"]:
                comando = escuchar()
            elif sesion["dormido"]:
                comando = escuchar_wake_word(DESPIERTA_WORD)
            else:
                comando = escuchar_wake_word(WAKE_WORD)

            tiempo_inactivo = time.time() - ultimo_comando

            if sesion["activa"] and not comando and tiempo_inactivo > TIMEOUT:
                hablar("Sesión finalizada")
                sesion["activa"] = False
                aviso_inactividad_dado = False
                continue

            AVISO_INACTIVIDAD = 12

            if (
                sesion["activa"]
                and not comando
                and not aviso_inactividad_dado
                and tiempo_inactivo > AVISO_INACTIVIDAD
            ):
                hablar("¿Sigues ahí?")
                aviso_inactividad_dado = True
                esperando_respuesta_aviso = True
                continue

            if not comando:
                continue

            aviso_inactividad_dado = False

            if esperando_respuesta_aviso:
                esperando_respuesta_aviso = False
                ultimo_comando = time.time()
                hablar("Te escucho, dime qué necesitas")
                continue

            if not sesion["activa"]:
                if sesion["dormido"]:
                    # FIX: despertar ya no toca no_molestar — son modos independientes
                    if detectar_wakeword(comando, DESPIERTA_WORD):
                        sesion["dormido"] = False
                        set_modo("escuchando")
                        hablar("Ya estoy de vuelta")
                    continue

                set_modo("escuchando")
                if not detectar_wakeword(comando, WAKE_WORD):
                    continue

                sesion["activa"] = True
                ultimo_comando = time.time()
                set_modo("hablando")
                hablar("¿En qué puedo ayudarte?")
                recalibrar()
                continue

            if es_cancelacion(comando):
                sesion["cancelar"] = True
                hablar("Cancelado")
                sesion["activa"] = False
                esperando_respuesta_aviso = False
                set_modo("inactivo")
                continue

            if es_despedida(comando):
                hablar("Hasta luego")
                sesion["activa"] = False
                esperando_respuesta_aviso = False
                set_modo("inactivo")
                continue

            if es_dormir(comando):
                # FIX: dormir ya no activa no_molestar — son modos completamente independientes
                hablar(f"Me quedo en silencio. Decí \"{DESPIERTA_WORD}\" cuando me necesites")
                sesion["activa"] = False
                sesion["dormido"] = True
                esperando_respuesta_aviso = False
                set_modo("dormido")
                continue

            if es_repetir(comando):
                ultimo_comando = time.time()
                texto_previo = ultimo_mensaje()
                if texto_previo:
                    hablar(texto_previo)
                else:
                    hablar("Todavía no dije nada")
                continue

            print("Escuché:", comando)
            ultimo_comando = time.time()
            set_modo("procesando")

            acciones = []

            try:
                intent_rapido, valor_rapido = detectar_intent(comando)
            except Exception as e:
                print("Error intents:", e)
                intent_rapido = None
                valor_rapido = None

            try:
                from gestor_ia import motor_a_usar as _motor
                set_motor_ia("Groq" if _motor() == "groq" else "Ollama")
            except Exception:
                pass

            if intent_rapido and valor_rapido:
                print("Intent rápido:", intent_rapido, valor_rapido)
                acciones = [(intent_rapido, valor_rapido)]
            else:
                acciones = interpretar_con_ia(comando)
                print("Acciones IA:", acciones)

            if acciones is None:
                ultimo_comando = time.time()
                from conectividad import hay_internet
                from verificacion import ollama_ejecutandose
                if not hay_internet(forzar=True) and not ollama_ejecutandose():
                    hablar("No tengo forma de procesar eso ahora: no hay internet y Ollama no está disponible")
                else:
                    hablar("Se está demorando mucho en responder, intenta de nuevo en un momento")
                continue

            if any(intent == "terminar_sesion" for intent, _ in acciones):
                hablar("Hasta luego")
                sesion["activa"] = False
                esperando_respuesta_aviso = False
                continue

            if not acciones:
                respuesta_libre = None
                ia_fallo = False
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

                # FIX: detectar si la IA ya incluyó una pregunta de cierre
                # para evitar preguntar dos veces seguidas
                FRASES_CIERRE_IA = {
                    "algo más", "necesitás algo", "necesitas algo",
                    "querés que haga", "quieres que haga",
                    "te ayudo", "te puedo ayudar", "puedo ayudarte",
                    "algo más que", "más que", "en algo más",
                    "hago algo", "necesitás algo más", "necesitas algo más",
                }

                tiene_pregunta_cierre = False
                if respuesta_libre:
                    respuesta_lower = respuesta_libre.lower()
                    tiene_pregunta_cierre = any(
                        frase in respuesta_lower for frase in FRASES_CIERRE_IA
                    )

                if respuesta_libre and not ia_fallo and not tiene_pregunta_cierre:
                    # La IA respondió pero NO preguntó si necesita algo más
                    # Nosotros agregamos la pregunta de cierre
                    hablar(f"{respuesta_libre}. ¿Necesitás algo más?", permitir_interrupcion=False)
                    # Escuchamos brevemente (3s) a ver si el usuario responde inmediatamente
                    from voice import escuchar_rapido
                    respuesta_seguir = escuchar_rapido(timeout=3, phrase_time_limit=5)
                    if respuesta_seguir:
                        comando_pendiente = respuesta_seguir
                elif respuesta_libre and not ia_fallo:
                    # La IA ya incluyó la pregunta de cierre → solo hablamos lo que dijo
                    hablar(respuesta_libre, permitir_interrupcion=False)
                    # FIX: NO escuchamos aquí — la IA ya invitó a seguir, y el loop
                    # normal de escucha (escuchar_wake_word/escuchar) se encarga
                    # de capturar la respuesta del usuario en la próxima iteración.
                    # Escuchar "por la fuerza" aquí causaba que comandos dichos
                    # durante la respuesta de la IA se procesaran sin contexto.
                else:
                    # Fallback o error
                    # FIX: hablar() devuelve None, no tiene sentido asignarlo a
                    # comando_pendiente. Se habla el mensaje y se continúa.
                    hablar(
                        respuesta_libre or "No entendí qué quieres que haga, ¿podés repetirlo?",
                        permitir_interrupcion=not ia_fallo,
                    )
                
                set_modo("escuchando")
                continue

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

            ultimo_comando = time.time()

            # FIX: hablar() devuelve None. No asignar a comando_pendiente.
            # El loop normal de escucha se encarga de la siguiente interacción.
            hablar("¿Algo más?", permitir_interrupcion=True)
            set_modo("escuchando")
            
        except Exception as e:
            log.exception(f"Error no manejado en el loop principal: {e}")
            try:
                hablar("Tuve un error inesperado, sigamos")
            except Exception:
                pass

# Arrancar el loop de voz en un hilo daemon ANTES de webview.start()
# porque webview.start() bloquea el hilo principal.
threading.Thread(target=_loop_voz, daemon=True, name="VozLoop").start()

# =====================================================
# INTERFAZ WEB — webview.start() BLOQUEA, va en hilo principal
# =====================================================

from main_web import _crear_ventana_y_arrancar

# Pasamos el orbe ya creado para que no haya que recrearlo (evita
# el gap entre splash y orbe)
try:
    _crear_ventana_y_arrancar(orbe_existente=orbe)
except KeyboardInterrupt:
    # FIX: manejar Ctrl+C de forma limpia, sin mostrar error fatal
    print("[Main] Interrupción por teclado (Ctrl+C). Cerrando...")
except Exception as e:
    log.exception(f"Error en la interfaz web: {e}")
    _mostrar_error_fatal(
        "AsistenteIA — Error de interfaz",
        f"La interfaz web falló al arrancar:\n\n{e}\n\n"
        f"Revisa el log en:\n{CARPETA_DATOS / 'asistente.log'}",
    )

# Si webview.start() retorna (ventana cerrada), terminamos todo.
print("[Main] Interfaz cerrada. Cerrando asistente...")
sys.exit(0)