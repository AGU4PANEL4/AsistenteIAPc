import concurrent.futures
import numpy as np
import speech_recognition as sr
from faster_whisper import WhisperModel
from logger import log

# =========================================================
# RECOGNIZER - configurar una sola vez
# Se usa SOLO para capturar el audio del micrófono (su detección
# de "cuándo empieza/termina de hablar" sigue siendo útil) — la
# TRANSCRIPCIÓN real ya no la hace recognize_google(), la hace
# Whisper local (ver más abajo). Ver FIX más abajo del por qué.
# =========================================================

recognizer = sr.Recognizer()
recognizer.energy_threshold         = 300
recognizer.dynamic_energy_threshold = True

# FIX: con recognize_google() (servidor remoto, vía internet) tenía
# sentido un pause_threshold bajo para no sumar más delay encima de
# la latencia de red. Ahora que la transcripción es 100% local con
# Whisper (sin red de por medio), se puede dar un poco más de margen
# para que una pausa natural a mitad de frase (pensando la próxima
# palabra) no corte el audio antes de tiempo — sin que se sienta
# lento, porque ya no hay que esperar una respuesta de Google.
recognizer.pause_threshold          = 0.9

recognizer.phrase_threshold         = 0.3
recognizer.non_speaking_duration    = 0.5


def _calibrar(duracion=2):
    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=duracion)


# FIX/NUEVO: _calibrar() corre acá mismo, a nivel de módulo, apenas
# se importa voice.py — que es de los primeros imports de main.py,
# así que esto pasa muy temprano en el arranque. Si el PC no tiene
# ningún micrófono conectado/configurado (ej. probando el asistente
# en un equipo de escritorio sin uno, o con drivers de audio mal
# instalados), sr.Microphone() lanza una excepción (típicamente
# OSError "No Default Input Device Available") que antes no se
# atrapaba acá — el asistente moría con un traceback críptico de
# PyAudio/portaudio antes de imprimir nada útil, sin que quedara
# claro para quien lo está probando que el problema es simplemente
# "no hay micrófono", no un bug del código.
#
# Ahora se atrapa el error, se imprime un mensaje claro en español
# señalando exactamente eso, y se SALE del proceso de forma limpia
# (sys.exit) en vez de dejar que el traceback crudo sea lo último
# que se ve — no tiene sentido seguir arrancando el resto del
# asistente (wake word, comandos, etc) si no hay ninguna forma de
# escuchar al usuario.
print("[Micrófono] Calibrando...")
try:
    _calibrar(duracion=2)
    print("[Micrófono] Listo")
except Exception as e:
    print("\n[Micrófono] No pude acceder a ningún micrófono.")
    print("[Micrófono] Motivo técnico:", e)
    print("[Micrófono] Revisa que haya un micrófono conectado y")
    print("[Micrófono] configurado como dispositivo de entrada")
    print("[Micrófono] predeterminado en Windows (Configuración >")
    print("[Micrófono] Sistema > Sonido > Entrada), y vuelve a intentar.")
    # FIX: si esto corre como .exe empaquetado (doble clic, sin
    # consola ya abierta de antes), un sys.exit() inmediato cierra la
    # ventana tan rápido que nadie llega a leer el mensaje de arriba.
    # Se espera unos segundos antes de salir — mismo patrón ya usado
    # en main.py para el caso de "no se pudo preparar la IA".
    import time
    import sys
    time.sleep(10)
    sys.exit(1)


def recalibrar():
    """
    Vuelve a medir el ruido de fondo. La calibración inicial se
    hace una sola vez al arrancar, pero si el volumen del juego,
    de la música, o el ruido del cuarto cambia durante el uso, el
    umbral de energía se queda desactualizado y empieza a cortar
    palabras o a no detectar que estás hablando. Llamar esto de
    vez en cuando (por ejemplo, cada vez que se activa una nueva
    sesión con la wake word) ayuda a mantenerlo al día sin tener
    que recalibrar antes de cada comando, lo cual sí se notaría
    como demora.
    """
    try:
        _calibrar(duracion=0.6)
    except Exception as e:
        print("[Micrófono] No pude recalibrar:", e)

# =========================================================
# WHISPER LOCAL (faster-whisper) — SOLO CPU
# FIX/NUEVO: recognize_google() es el servicio gratuito de Google,
# pensado para demos, no para uso diario — transcribía mal bastante
# seguido (palabras cambiadas, cortes), independientemente de qué tan
# buena fuera la conexión a internet, porque el problema era de
# precisión del modelo, no de red.
#
# Se reemplaza por Whisper corriendo LOCAL, EN CPU (modelo "small",
# int8) usando faster-whisper. Se eligió CPU en vez de GPU a propósito:
# - Instalación: "pip install faster-whisper" y listo. Nada de CUDA,
#   nada de cuDNN, cero riesgo de incompatibilidad de versiones de
#   drivers (que sí es un problema real y documentado al usar GPU).
# - Velocidad real: los benchmarks oficiales de faster-whisper muestran
#   que el modelo "small" en CPU con int8 transcribe a ~0.13x tiempo
#   real (13 min de audio en ~1m42s en un i7-12700K). Para FRASES
#   CORTAS de comando de voz (2-5 segundos, no archivos largos), esto
#   es bien por debajo de medio segundo — no se nota como demora.
# - Así la GPU queda libre por completo para Ollama y para tus juegos,
#   sin competir por VRAM con la transcripción de voz.
#
# Igual que en ia.py con Ollama: si por lo que sea la transcripción
# tarda más de la cuenta (CPU bajo mucha carga en ese instante), la
# llamada tiene un timeout real en un hilo aparte — no se cuelga el
# asistente esperando indefinidamente.
# =========================================================

MODELO_WHISPER = "small"

# FIX: sin especificar cpu_threads, CTranslate2 (el motor que usa
# faster-whisper por debajo) puede quedarse con un valor por defecto
# bastante conservador, sin aprovechar los núcleos reales de la CPU.
# Esto se notó como timeouts de 6s+ incluso SIN carga pesada real del
# sistema (un juego mayormente de GPU no debería competir tan fuerte
# por CPU) — la transcripción simplemente no tenía suficientes hilos
# asignados para ir rápido, sin importar qué tan libre estuviera el
# resto de la máquina.
#
# Se usa la MITAD de los núcleos físicos (no lógicos — hyperthreading
# no ayuda igual de bien a cargas de cómputo intensivo como esta) en
# vez de todos, a propósito: _executor_whisper más abajo permite hasta
# 2 transcripciones en paralelo (la normal y la de vigilancia de
# barge-in), y si cada una pidiera TODOS los núcleos para sí misma,
# correr dos a la vez generaría más cambio de contexto que beneficio
# real. La mitad deja margen para eso y para el resto del sistema
# (un juego corriendo al mismo tiempo), con un mínimo de 2 para no
# quedarse con casi nada en máquinas con pocos núcleos.
import multiprocessing

_NUCLEOS_LOGICOS = multiprocessing.cpu_count() or 4

# Aproximadamente la mitad de los núcleos lógicos, con un mínimo de 2
# y un máximo razonable de 8 (más que eso, según los benchmarks
# oficiales de faster-whisper, da retornos decrecientes para este
# tamaño de modelo).
CPU_THREADS_WHISPER = max(2, min(8, _NUCLEOS_LOGICOS // 2))

# FIX/NUEVO: con pocos hilos asignados (CPUs de pocos núcleos, ej. 6
# hilos lógicos -> 3 para Whisper), la transcripción tarda más incluso
# en condiciones normales, y más todavía con un juego compitiendo por
# el resto de la CPU. Un timeout fijo de 6s para cualquier hardware
# significaba que máquinas con pocos hilos cancelaban y caían a
# Google (menos preciso, depende de internet) más seguido de lo
# necesario, solo por no haberle dado un margen acorde a sus recursos
# reales.
#
# TIMEOUT_BASE_WHISPER escala de forma inversa a CPU_THREADS_WHISPER:
# menos hilos -> más margen de espera antes de rendirse. Con el
# máximo de 8 hilos (CPUs grandes) el timeout base es 6s (el valor
# original); con el mínimo de 2 hilos (CPUs chicas) sube hasta 10s.
TIMEOUT_BASE_WHISPER = round(6 + (8 - CPU_THREADS_WHISPER) * (4 / 6))

try:
    _modelo_whisper = WhisperModel(
        MODELO_WHISPER,
        device="cpu",
        compute_type="int8",
        cpu_threads=CPU_THREADS_WHISPER,
    )
    print(f"[Whisper] Modelo '{MODELO_WHISPER}' cargado en CPU "
          f"({CPU_THREADS_WHISPER} hilos)")
    log.info(f"Whisper '{MODELO_WHISPER}' cargado en CPU ({CPU_THREADS_WHISPER} hilos)")
except Exception as e:
    print("[Whisper] No se pudo cargar el modelo:", e)
    log.exception("No se pudo cargar el modelo Whisper")
    _modelo_whisper = None

# =========================================================
# MODELO LIVIANO, SOLO PARA LA WAKE WORD
# FIX/NUEVO: problema real reportado en pruebas — incluso con
# beam_size=1 (ver escuchar_wake_word más abajo), el modelo "small"
# sigue siendo costoso de correr en CADA frase de fondo que el
# micrófono capta mientras se espera la wake word (la gran mayoría
# del tiempo que el asistente está prendido). En un Ryzen 5 7600x (12
# hilos lógicos), CPU_THREADS_WHISPER calcula 6 hilos para el modelo
# "small" — esos 6 hilos saturados en cada transcripción de fondo se
# ven como ~50% de uso total de CPU, incluso hablando de cosas que no
# tienen nada que ver con la wake word.
#
# La wake word es una sola palabra corta y conocida, con tolerancia
# difusa en la comparación (ver wakeword.py, 80% de parecido) — no
# necesita ni de lejos la capacidad del modelo "small". Un modelo
# "tiny" (bastante más liviano en cómputo) con muy pocos hilos
# asignados a propósito (2, deliberadamente bajo — acá se prioriza
# techo de CPU sobre velocidad, a diferencia del modelo principal)
# alcanza de sobra para reconocer si lo que se dijo se parece a
# "jarvis", a una fracción del costo de CPU por cada intento.
#
# El modelo "small" principal NO se toca y sigue siendo el que
# transcribe comandos reales una vez la sesión está activa — ahí sí
# importa la precisión, y esas llamadas son mucho menos frecuentes
# (una por comando, no una por cada frase de fondo).
MODELO_WHISPER_WAKEWORD  = "base"
CPU_THREADS_WAKEWORD     = 2

try:
    _modelo_whisper_wakeword = WhisperModel(
        MODELO_WHISPER_WAKEWORD,
        device="cpu",
        compute_type="int8",
        cpu_threads=CPU_THREADS_WAKEWORD,
    )
    print(f"[Whisper] Modelo liviano '{MODELO_WHISPER_WAKEWORD}' cargado "
          f"para la wake word ({CPU_THREADS_WAKEWORD} hilos)")
    log.info(f"Whisper '{MODELO_WHISPER_WAKEWORD}' (wake word) cargado "
             f"en CPU ({CPU_THREADS_WAKEWORD} hilos)")
except Exception as e:
    # si esto falla, no es grave — escuchar_wake_word() cae de vuelta
    # al modelo "small" principal (ver _transcribir_whisper más abajo),
    # exactamente el comportamiento de antes de este cambio. Se pierde
    # la ganancia de CPU, pero la wake word sigue funcionando.
    print("[Whisper] No se pudo cargar el modelo liviano de wake word, "
          "se usará el modelo principal también para eso:", e)
    log.warning(f"No se pudo cargar el modelo liviano de wake word: {e}")
    _modelo_whisper_wakeword = None

_executor_whisper = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def _audio_a_array(audio_data):
    """
    Convierte el AudioData de speech_recognition (WAV) al formato
    que espera faster-whisper: array de NumPy float32, mono, 16kHz.
    """
    wav_bytes = audio_data.get_wav_data(convert_rate=16000, convert_width=2)

    # los datos WAV de 16-bit PCM se leen como int16 y se normalizan
    # a float32 en el rango [-1, 1], que es lo que Whisper espera
    muestras_int16 = np.frombuffer(wav_bytes[44:], dtype=np.int16)
    return muestras_int16.astype(np.float32) / 32768.0


def _transcribir_whisper(audio_data, initial_prompt=None, beam_size=5, hotwords=None, modelo=None):
    """Transcribe usando Whisper local. Devuelve el texto, o None si
    el modelo no está disponible o la transcripción falló.

    initial_prompt: texto de contexto que sesga el ESTILO de lo que
    Whisper espera escuchar — útil para frases cortas como la wake
    word (ver escuchar_wake_word).

    hotwords: lista de palabras/frases separadas por coma que se le
    da prioridad de reconocimiento, SIN el límite de 224 tokens ni
    el efecto de "estilo de prompt" que tiene initial_prompt — es el
    mecanismo correcto para listas largas de nombres propios (apps,
    juegos), ver escuchar() más abajo.

    modelo: instancia de WhisperModel a usar — por defecto el modelo
    principal (_modelo_whisper). escuchar_wake_word() pasa el modelo
    liviano dedicado (_modelo_whisper_wakeword) para esa ruta en
    particular (ver el comentario detallado junto a su carga, más
    arriba). Si el modelo pedido es None (ej. el liviano falló al
    cargar), se cae automáticamente al modelo principal en vez de
    fallar — la wake word sigue funcionando, solo sin la ganancia de
    CPU en ese caso puntual.
    """
    modelo = modelo or _modelo_whisper

    if modelo is None:
        return None

    array_audio = _audio_a_array(audio_data)

    segmentos, _ = modelo.transcribe(
        array_audio,
        language="es",
        beam_size=beam_size,
        vad_filter=True,
        condition_on_previous_text=False,
        initial_prompt=initial_prompt,
        hotwords=hotwords,
    )

    texto = " ".join(segmento.text.strip() for segmento in segmentos)
    return texto.strip()


def _transcribir_con_timeout(audio_data, timeout=None, initial_prompt=None, beam_size=5, hotwords=None, modelo=None):
    """
    Llama a Whisper con un límite de tiempo real, igual que
    _llamar_ollama en ia.py — si la CPU está ocupada (ej: un juego
    pesado corriendo) y la transcripción tarda más de la cuenta, no
    se cuelga el asistente esperando indefinidamente.

    Si no se especifica `timeout`, se usa TIMEOUT_BASE_WHISPER —
    calculado según los hilos disponibles en esta máquina (ver más
    arriba), en vez de un valor fijo igual para cualquier hardware.

    `modelo` se pasa tal cual a _transcribir_whisper (ver ese
    comentario para el detalle de cuándo se usa el liviano de wake
    word en vez del principal).
    """
    if timeout is None:
        timeout = TIMEOUT_BASE_WHISPER

    futuro = _executor_whisper.submit(
        _transcribir_whisper, audio_data, initial_prompt, beam_size, hotwords, modelo
    )

    try:
        return futuro.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        # FIX: este mensaje decía "¿hay un juego usando la GPU?",
        # copiado sin adaptar del mensaje equivalente en ia.py (que sí
        # usa GPU, vía Ollama). Whisper corre en CPU (ver
        # CPU_THREADS_WHISPER más arriba), así que la pregunta sobre
        # GPU no tenía sentido acá y solo generaba confusión.
        print(f"[Whisper] Tardó más de {timeout}s, se cancela la espera "
              f"(¿hay mucha carga de CPU en este momento?)")
        log.warning(f"Whisper tardó más de {timeout}s, se canceló la espera")
        return None
    except Exception as e:
        print("[Whisper] Error transcribiendo:", e)
        log.exception("Error transcribiendo con Whisper")
        return None


def _transcribir(audio_data, initial_prompt=None, beam_size=5, hotwords=None,
                  permitir_groq=True, modelo=None):
    """
    Transcribe el audio usando el modo híbrido (ver gestor_ia.py):
    con internet se prueba Groq Whisper primero (modelo más grande
    y preciso, corriendo en hardware especializado — mejora notable
    con nombres propios en inglés que el Whisper local "small" en
    CPU transcribía mal de forma consistente, ej. "Wuthering Waves",
    "Stellar Blade"). Sin internet, o si Groq falla, se usa el
    Whisper local como siempre funcionó, y si ESE también falla,
    cae a recognize_google() como último respaldo.

    FIX/NUEVO: permitir_groq=False fuerza a NO usar Groq sin importar
    si hay internet o no, saltando directo al Whisper local. Se usa
    desde escuchar_wake_word() — mientras el asistente espera la wake
    word (la gran mayoría del tiempo que está encendido, en loop
    constante) cada frase de fondo que el micrófono captaba terminaba
    gastando una llamada a la API de Groq, agotando la cuota gratuita
    en poco tiempo SIN que el usuario haya pedido nada todavía. Una
    vez que la sesión está activa (escuchar(), escuchar_confirmacion(),
    escuchar_rapido()), sí tiene sentido pagar el costo de Groq — ahí
    cada llamada corresponde a un comando real que el usuario quiere
    que se entienda lo mejor posible, garantizando que el uso de la
    API quede prácticamente limitado a comandos reales, no a la
    espera pasiva de la wake word.

    `modelo` se pasa tal cual a _transcribir_con_timeout/_transcribir_whisper
    — None usa el modelo principal; escuchar_wake_word() pasa el
    modelo liviano dedicado (ver el comentario junto a su carga, más
    arriba) para reducir el uso de CPU en esa ruta, que corre en loop
    constante.
    """
    from gestor_ia import motor_a_usar

    if permitir_groq and motor_a_usar() == "groq":
        from groq_cliente import transcribir_groq

        wav_bytes = audio_data.get_wav_data(convert_rate=16000, convert_width=2)

        # el prompt de contexto de Groq cumple el mismo rol que
        # initial_prompt/hotwords en el Whisper local — se combinan
        # ambos si están presentes, priorizando initial_prompt (más
        # corto y específico, ej. la wake word) sobre hotwords (lista
        # larga de nombres de apps) si por algún motivo se pasaran
        # los dos juntos en una misma llamada
        contexto = initial_prompt or hotwords

        texto = transcribir_groq(wav_bytes, prompt_contexto=contexto)

        if texto is not None:
            return texto.lower()

        print("[Groq] Transcripción falló, usando Whisper local como respaldo")
        log.warning("Groq Whisper falló, cayendo a Whisper local")

    texto = _transcribir_con_timeout(
        audio_data, initial_prompt=initial_prompt, beam_size=beam_size,
        hotwords=hotwords, modelo=modelo
    )

    if texto is not None:
        return texto.lower()

    print("[Whisper] No disponible, usando Google como respaldo")

    try:
        return recognizer.recognize_google(
            audio_data,
            language="es-CO"
        ).lower()
    except sr.UnknownValueError:
        return ""
    except sr.RequestError:
        return ""

# =========================================================
# HOTWORDS DE APPS/JUEGOS
# NUEVO: nombres en inglés dichos sueltos ("brawlhalla", "wuthering
# waves") son el mismo problema que "jarvis" — Whisper, sesgado al
# español, los fragmenta en palabras que sí conoce ("braujala",
# "sierra brau chala", etc), aunque el VAD detecte el audio bien.
#
# Acá se usa el parámetro `hotwords` de faster-whisper en vez de
# initial_prompt: no tiene el límite de 224 tokens "estilo prompt",
# está pensado específicamente para listas de términos a reconocer
# mejor (ver hotwords en _transcribir_whisper). Aun así, pasarle un
# texto absurdamente largo no ayuda y puede ser contraproducente, así
# que se limita a un máximo de caracteres razonable.
#
# FIX: la primera versión priorizaba aliases > juegos > apps, y dentro
# de cada grupo los nombres más cortos primero. Eso funciona bien con
# pocas apps, pero en una PC con muchas (100+), las apps que quedan
# más abajo en esa jerarquía fija NUNCA entran en el límite de
# caracteres — siempre las mismas se benefician, siempre las mismas
# se cortan, sin importar cuáles realmente usa la persona.
#
# Ahora TODOS los nombres (aliases + juegos + apps) tienen la MISMA
# prioridad — se tratan como un solo conjunto sin jerarquía. Se usa
# un punto de inicio que ROTA en cada llamada a escuchar(): cada vez
# se manda un subconjunto distinto de ese conjunto completo, empezando
# en un lugar diferente. Con el uso normal del asistente (muchos
# comandos a lo largo de una sesión), cada nombre pasa por la lista de
# hotwords aproximadamente la misma cantidad de veces, sin que ninguno
# quede permanentemente excluido por ser largo o estar "de último".
# =========================================================

_LIMITE_CARACTERES_HOTWORDS = 600
_indice_rotacion_hotwords   = 0


def _construir_hotwords():
    global _indice_rotacion_hotwords

    try:
        import app_finder
        from aliases import aliases as alias_dict
    except Exception:
        return None

    candidatos = []

    try:
        candidatos.extend(alias_dict.keys())
    except Exception:
        pass

    try:
        candidatos.extend(app_finder.games_index.keys())
    except Exception:
        pass

    try:
        candidatos.extend(app_finder.apps_index.keys())
    except Exception:
        pass

    # quitar duplicados, sin ninguna jerarquía entre ellos — todos
    # entran al mismo conjunto en igualdad de condiciones
    vistos  = set()
    unicos  = []
    for nombre in candidatos:
        clave = nombre.lower().strip()
        if clave and clave not in vistos:
            vistos.add(clave)
            unicos.append(clave)

    if not unicos:
        return None

    # ROTACIÓN: en vez de empezar siempre desde el índice 0 (lo cual
    # repetiría siempre los mismos primeros nombres), se empieza desde
    # un punto que avanza en cada llamada — dando la vuelta completa
    # al conjunto con el tiempo, como una rueda.
    n      = len(unicos)
    inicio = _indice_rotacion_hotwords % n
    orden_rotado = unicos[inicio:] + unicos[:inicio]

    resultado = []
    largo     = 0
    for nombre in orden_rotado:
        # +2 por la coma y el espacio que separan cada hotword
        if largo + len(nombre) + 2 > _LIMITE_CARACTERES_HOTWORDS:
            break
        resultado.append(nombre)
        largo += len(nombre) + 2

    # avanzar el punto de rotación para la PRÓXIMA llamada, según
    # cuántos nombres entraron esta vez — así la siguiente tanda
    # empieza justo donde esta se quedó, sin saltarse ni repetir de
    # más ningún tramo del conjunto completo
    _indice_rotacion_hotwords = (inicio + len(resultado)) % n

    return ", ".join(resultado) if resultado else None

# =========================================================
# ESCUCHAR WAKE WORD
# NUEVO: "jarvis" dicho solo (sin contexto de frase, nombre propio
# en inglés en medio de español) es justo el peor caso para Whisper
# — el modelo, sesgado a producir palabras "normales" en español,
# a veces lo transcribía como "ya debes", "jerbys" u otras frases
# sin relación, en vez del nombre real.
#
# Dos ajustes específicos para ESTA escucha (no para comandos
# normales, que no los necesitan y donde sumarían latencia sin
# necesidad):
#
# - initial_prompt: le da a Whisper el WAKE_WORD como contexto
#   esperado, sesgando la transcripción a reconocerlo cuando el
#   audio se parezca, en vez de "corregirlo" hacia otra palabra
#   común en español. Es el mecanismo estándar para nombres propios
#   o términos poco frecuentes en el idioma configurado.
# - beam_size más alto: más hipótesis exploradas antes de decidir
#   el texto final — ayuda especialmente con palabras cortas y
#   ambiguas. Cuesta algo de tiempo extra, pero sigue siendo
#   rápido para un audio de 1-3 segundos (ver crear_temporizador
#   y demás: en CPU, Whisper small transcribe frases cortas en
#   bien menos de 1 segundo incluso con más beam_size).
#
# FIX/NUEVO: lo de arriba describe bien el COSTO POR LLAMADA (rápido,
# sub-segundo), pero no la FRECUENCIA de llamadas — y ahí estaba el
# problema real reportado: escuchar_wake_word() corre en loop
# constante mientras no hay sesión activa (la gran mayoría del tiempo
# que el asistente está prendido), así que CUALQUIER frase de fondo
# que el micrófono capte (TV, una conversación cerca, lo que sea, no
# solo la wake word) dispara una transcripción completa. Con
# beam_size=8 sobre el modelo "small", cada una de esas transcripciones
# satura varios hilos de CPU durante esa fracción de segundo — y si
# hay conversación de fondo frecuente, esos picos se sienten casi
# continuos (la CPU subiendo a 80%+ aunque nadie haya dicho la wake
# word en absoluto).
#
# A diferencia de un comando real (que se transcribe UNA vez por
# sesión activa), acá no hace falta tanta precisión: detectar_wakeword()
# (wakeword.py) ya compara con tolerancia difusa (80% de parecido), no
# texto exacto — así que no necesita la mejor transcripción posible,
# solo una lo bastante cercana fonéticamente. Bajar el beam_size acá
# (de 8 a 1, decodificación "greedy") reduce mucho el costo de cada
# transcripción de fondo sin perder la capacidad real de reconocer la
# wake word, gracias a esa tolerancia ya existente.
# =========================================================

def escuchar_wake_word(wake_word):

    with sr.Microphone() as source:
        print("Escuchando...")
        try:
            audio = recognizer.listen(
                source,
                timeout=5,
                phrase_time_limit=4
            )
        except sr.WaitTimeoutError:
            return ""

    prompt = f"Comandos de voz en español. Palabra de activación: {wake_word}."

    # FIX/NUEVO: permitir_groq=False — ver el detalle completo en
    # _transcribir() (voice.py). En resumen: esta función se llama en
    # loop constante mientras no hay sesión activa, así que sin esto
    # cada ciclo de espera de la wake word gastaba una llamada real a
    # la API de Groq, agotando la cuota gratuita diaria sin que el
    # usuario hubiera pedido nada todavía. Forzando el Whisper local
    # acá, Groq queda reservado para cuando ya hay una sesión activa
    # y el usuario está dando un comando real.
    #
    # beam_size=1 (en vez de 8) — ver el comentario completo arriba:
    # reduce mucho el uso de CPU en cada ciclo de este loop constante,
    # sin perder la wake word gracias a la tolerancia difusa de
    # detectar_wakeword().
    #
    # modelo=_modelo_whisper_wakeword — usa el modelo "tiny" liviano
    # dedicado (ver el comentario completo junto a su carga, más
    # arriba) en vez del modelo "small" principal, para reducir aún
    # más el uso de CPU en esta ruta de loop constante. Si ese modelo
    # no se pudo cargar (None), _transcribir_whisper cae automática-
    # mente al modelo principal — la wake word sigue funcionando.
    return _transcribir(
        audio, initial_prompt=prompt, beam_size=1, permitir_groq=False,
        modelo=_modelo_whisper_wakeword,
    )

# =========================================================
# ESCUCHAR CONFIRMACIÓN (sí/no/confirmo/etc)
# NUEVO: mismo problema que con la wake word — una respuesta corta
# dicha SOLA ("sí", "hazlo", "confirmo") es el peor caso para Whisper,
# que sin contexto de frase puede transcribir algo completamente
# distinto. Esto causaba que confirmaciones reales de "sí, hazlo,
# confirmo" terminaran interpretándose como "no" (silencio o texto
# que no matcheaba ninguna palabra de afirmación) — el usuario decía
# que sí, pero el asistente actuaba como si hubiera dicho que no.
#
# Mismo mecanismo que escuchar_wake_word(): initial_prompt sesga a
# Whisper hacia el tipo de respuesta esperado, y un beam_size más
# alto ayuda específicamente con palabras cortas y ambiguas.
# =========================================================

def escuchar_confirmacion(timeout=8):

    with sr.Microphone() as source:
        print("Escuchando...")
        try:
            audio = recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=4
            )
        except sr.WaitTimeoutError:
            return ""

    prompt = "Responde sí, no, confirmo, dale, cancela u otra confirmación corta."

    return _transcribir(audio, initial_prompt=prompt, beam_size=8)

# =========================================================
# ESCUCHAR NORMAL
# =========================================================

def escuchar():

    with sr.Microphone() as source:
        print("Escuchando...")
        try:
            audio = recognizer.listen(
                source,
                timeout=5,
                # FIX: 8s cortaba comandos un poco más largos
                # ("registra alias para tal app y tal otro alias").
                phrase_time_limit=12
            )
        except sr.WaitTimeoutError:
            return ""

    # FIX: se construye la lista de hotwords en CADA llamada, no una
    # sola vez al importar el módulo — los índices de apps/juegos se
    # llenan en hilos daemon que arrancan en main.py y tardan varios
    # segundos, así que si se armara una sola vez al inicio podría
    # quedar vacía. Construirla cada vez también significa que un
    # alias nuevo que agregues durante la sesión mejora el
    # reconocimiento de inmediato, sin reiniciar el asistente.
    hotwords = _construir_hotwords()

    return _transcribir(audio, hotwords=hotwords)

# =========================================================
# ESCUCHAR CON TIMEOUT CORTO
# Para el hilo de cancelación — escucha rápido y no bloquea
# =========================================================

def escuchar_rapido(timeout=2, phrase_time_limit=3):

    with sr.Microphone() as source:
        try:
            audio = recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=phrase_time_limit
            )
        except sr.WaitTimeoutError:
            return ""

    try:
        return _transcribir(audio)
    except:
        return ""

# =========================================================
# DETECTAR VOZ BREVE (sin transcribir)
# NUEVO: usada por el mecanismo de barge-in en tts.py. A diferencia
# de escuchar_rapido() (que espera una FRASE completa con su
# silencio final antes de devolver algo, y luego la transcribe con
# Whisper), esta función solo necesita responder lo más rápido
# posible a la pregunta "¿hay alguien hablando ahora mismo?" — sin
# pagar el costo de esperar una frase completa ni de transcribir.
#
# phrase_time_limit muy corto (0.3s) significa que listen() devuelve
# en cuanto detecta ~0.3s de energía por encima del umbral, sin
# esperar a que la persona termine de hablar. No se transcribe nada
# acá — eso se hace DESPUÉS, una vez que ya se cortó el audio del
# TTS, con una escucha normal completa (ver _vigilar_interrupcion en
# tts.py).
# =========================================================

def detectar_voz_breve(timeout=1):
    with sr.Microphone() as source:
        try:
            recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=0.3
            )
            return True
        except sr.WaitTimeoutError:
            return False