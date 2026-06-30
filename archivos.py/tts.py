import asyncio
import io
import threading
import edge_tts
import pygame
from logger import log

# =========================================================
# VOZ
# es-CO-SalomeNeural = voz colombiana femenina
# es-CO-GonzaloNeural = voz colombiana masculina
# =========================================================

VOZ = "es-CO-SalomeNeural"

# =========================================================
# INICIALIZAR PYGAME MIXER UNA SOLA VEZ
# =========================================================

pygame.mixer.init()

# =========================================================
# LOCK DE VOZ
# FIX: hablar() no tenía ninguna protección contra llamadas
# simultáneas desde distintos hilos. Mientras solo el hilo
# principal hablaba, no importaba — pero con recordatorios.py
# (un hilo daemon por recordatorio que llama a hablar() cuando
# se cumple la hora) ahora sí puede pasar que el hilo principal
# esté diciendo algo justo cuando un recordatorio se dispara.
# pygame.mixer.music.load() de un hilo pisaría el audio que el
# otro hilo acaba de cargar/empezar a reproducir.
#
# Con este Lock, si dos hilos llaman a hablar() al mismo tiempo,
# el segundo simplemente espera a que el primero termine de
# hablar antes de empezar — nunca se pisan, nunca se pierde un
# aviso.
# =========================================================

_lock_voz = threading.Lock()

# =========================================================
# RESPALDO SIN INTERNET (SAPI5 de Windows)
# Edge TTS depende de un servicio de Microsoft que de vez en
# cuando devuelve error 403 (problema conocido y reportado del
# lado de ellos, no de este código — ver github.com/rany2/edge-tts).
# Mientras eso pase (o si no hay internet), usar la voz local de
# Windows evita que el asistente se quede completamente mudo,
# aunque suene más robótica que la voz neuronal de Edge.
# =========================================================

def _hablar_respaldo(texto):
    try:
        import pyttsx3
        motor = pyttsx3.init()
        motor.say(texto)
        motor.runAndWait()
        return True
    except Exception as e:
        print("[TTS] Respaldo también falló:", e)
        return False

# =========================================================
# BARGE-IN (interrumpir al asistente hablando)
# NUEVO: mientras el audio se reproduce, un hilo aparte vigila el
# micrófono en ventanas cortas. Si detecta que el usuario empezó a
# hablar, CORTA la reproducción de inmediato (en vez de esperar a
# que termine la frase completa) y devuelve lo que se llegó a
# escuchar — así el usuario no tiene que esperar a que el asistente
# termine de hablar para poder decir algo.
#
# Se usa escuchar_rapido() (la misma función ya usada por
# cancelacion.py, mismo patrón ya probado) en vez de acceso directo
# al audio crudo del micrófono — es menos instantáneo (hasta ~0.5s
# de retraso en detectar que empezaste a hablar, por el tamaño de la
# ventana) pero muchísimo más simple y seguro, reusando
# infraestructura ya validada en vez de construir algo nuevo de cero.
#
# IMPORTANTE: con parlantes (no auriculares), el propio micrófono
# puede captar la voz del asistente saliendo por los parlantes, lo
# cual puede autointerrumpir la reproducción — esto es un trade-off
# consciente y conocido de priorizar reacción rápida sobre evitar
# falsos positivos (ver la conversación de diseño): no hay forma de
# eliminarlo del todo sin antes distinguir "es mi propia voz" de
# "es el usuario", lo cual queda fuera del alcance de esta primera
# versión.
# =========================================================

def _vigilar_interrupcion(evento_detener, resultado):
    """
    Corre en un hilo aparte mientras el audio se reproduce.

    FASE 1 — detección rápida: usa detectar_voz_breve() (ventanas de
    ~0.3s, sin transcribir nada) en loop, repitiendo hasta que se
    detecte energía de voz o el audio termine solo. Esto es lo que
    permite cortar la reproducción casi de inmediato en vez de
    esperar a que el usuario termine de decir una frase completa.

    FASE 2 — una vez detectada la voz, se corta la reproducción
    PRIMERO (pygame.mixer.music.stop()), y SOLO DESPUÉS se hace una
    escucha completa normal (escuchar_rapido) para capturar qué dijo
    el usuario realmente — ya sin el audio del TTS de fondo
    compitiendo con su voz. Ese texto es lo que hablar() devuelve
    como resultado de la interrupción.
    """
    from voice import detectar_voz_breve, escuchar_rapido

    while not evento_detener.is_set():
        try:
            hay_voz = detectar_voz_breve(timeout=1)
        except Exception:
            continue

        if evento_detener.is_set():
            # el audio ya terminó solo mientras hacíamos esta
            # detección — no es una interrupción real
            return

        if hay_voz:
            pygame.mixer.music.stop()

            try:
                texto = escuchar_rapido(timeout=2, phrase_time_limit=8)
            except Exception:
                texto = ""

            resultado[0] = texto or None
            return

# =========================================================
# HABLAR
# =========================================================

async def _hablar_async(texto, permitir_interrupcion):

    communicate = edge_tts.Communicate(texto, voice=VOZ)

    audio_data = b""

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]

    if not audio_data:
        raise RuntimeError("Edge TTS no devolvió audio")

    pygame.mixer.music.load(io.BytesIO(audio_data))
    pygame.mixer.music.play()

    # FIX: pygame.mixer.music.play() inicia la reproducción de forma
    # asíncrona — toma unos milisegundos en arrancar de verdad. Sin
    # este pequeño margen, el primer chequeo de get_busy() de abajo
    # podía ocurrir ANTES de que el audio empezara a sonar, devolver
    # False de inmediato, y el while se saltaba sin esperar nada. El
    # código terminaba "exitosamente" sin haber esperado a que el
    # audio realmente se reprodujera — esto causaba que, después del
    # primer hablar() (que por timing sí alcanzaba a arrancar), los
    # siguientes se cortaran o ni llegaran a sonar.
    await asyncio.sleep(0.1)

    resultado_interrupcion = [None]
    hilo_vigilancia         = None
    evento_detener          = threading.Event()

    if permitir_interrupcion:
        hilo_vigilancia = threading.Thread(
            target=_vigilar_interrupcion,
            args=(evento_detener, resultado_interrupcion),
            daemon=True
        )
        hilo_vigilancia.start()

    while pygame.mixer.music.get_busy():
        pygame.time.wait(50)

    # el audio ya terminó (sea porque sonó completo, o porque el
    # hilo de vigilancia lo cortó) — se avisa al hilo de vigilancia
    # para que no siga escuchando de más si todavía no detectó nada
    evento_detener.set()

    # FIX: sin este join(), el hilo principal podía seguir de
    # inmediato hacia la siguiente llamada a escuchar() (en main.py)
    # MIENTRAS el hilo de vigilancia todavía estaba a mitad de un
    # `with sr.Microphone()` (detectar_voz_breve puede tardar hasta
    # ~1s en su propio listen() con timeout). Dos hilos abriendo
    # sr.Microphone() al mismo tiempo causaba un crash real:
    # "Audio source must be entered before listening" / "'NoneType'
    # object has no attribute 'close'" — el stream de PyAudio queda
    # en None cuando dos aperturas se pisan.
    #
    # Es el mismo tipo de problema (y la misma solución) que ya
    # resolvimos en cancelacion.py con detener_cancelacion(): esperar
    # a que el hilo realmente termine y suelte el micrófono antes de
    # devolver el control, en vez de asumir que set() es instantáneo.
    # El timeout del join da margen de sobra (detectar_voz_breve
    # nunca debería tardar más de ~1.3s en notar la bandera y salir).
    if hilo_vigilancia is not None and hilo_vigilancia.is_alive():
        hilo_vigilancia.join(timeout=3)

    return resultado_interrupcion[0]


def hablar(texto, permitir_interrupcion=False):
    """
    Habla el texto dado. Devuelve None normalmente.

    Si permitir_interrupcion=True, mientras el audio suena se vigila
    el micrófono — si el usuario empieza a hablar, la reproducción
    se corta de inmediato y hablar() devuelve el texto transcrito de
    esa interrupción, en vez de None. El código que llama a hablar()
    puede revisar ese valor para usarlo como el siguiente comando en
    vez de esperar a escuchar() de nuevo.

    Por defecto permitir_interrupcion es False — mensajes cortos
    (confirmaciones, "Cancelado", etc) no se benefician de esto y
    activar la vigilancia para cada mensaje sumaría carga e
    incertidumbre sin necesidad. Se activa explícitamente solo en
    los mensajes donde más se siente la espera (ver main.py).
    """

    with _lock_voz:
        print("Asistente:", texto)

        try:
            return asyncio.run(_hablar_async(texto, permitir_interrupcion))
        except Exception as e:
            print("[TTS] Error con Edge TTS, usando respaldo local:", e)
            # FIX/NUEVO: Edge TTS fallando es un caso ya conocido y con
            # respaldo diseñado (ver _hablar_respaldo arriba) — no es
            # grave por sí solo, así que se registra como warning (útil
            # para notar si pasa muy seguido, sin tratarlo como un
            # error grave cada vez). Lo que SÍ es importante y antes
            # NO quedaba registrado en ningún lado es que el respaldo
            # local TAMBIÉN falle — en ese caso el asistente se queda
            # completamente mudo en silencio, sin ningún rastro de qué
            # mensaje se perdió ni por qué, ni en consola (la única
            # pista era la del log de Edge TTS) ni en el log de errores.
            log.warning(f"Edge TTS falló, usando respaldo local. Texto: '{texto}'. Motivo: {e}")
            if not _hablar_respaldo(texto):
                log.error(f"El asistente quedó MUDO — fallaron Edge TTS Y el "
                          f"respaldo local para el mensaje: '{texto}'")
            return None