"""
Cliente de Groq — la API en la nube usada cuando hay internet (ver
gestor_ia.py para el routing completo entre Groq y Ollama).

Requiere:
  pip install groq
  Una API key gratuita de https://console.groq.com (variable de
  entorno GROQ_API_KEY, o pegada directo en config.py — ver abajo).
"""

import concurrent.futures
from logger import log

try:
    from groq import Groq
    GROQ_DISPONIBLE = True
except ImportError:
    GROQ_DISPONIBLE = False
    print("[Groq] El paquete 'groq' no está instalado (pip install groq). "
          "El modo híbrido caerá siempre a Ollama local.")

from config import obtener_groq_api_key, MODELO_GROQ

_cliente_groq = None
_executor_groq = concurrent.futures.ThreadPoolExecutor(max_workers=2)
# recuerda con qué key se construyó _cliente_groq, para detectar si
# cambió (ej. setup_groq.py guardó una key nueva en esta misma
# ejecución) y reconstruir el cliente en vez de seguir usando uno
# armado con una key vieja o vacía
_key_cliente_actual = None


def _obtener_cliente():
    global _cliente_groq, _key_cliente_actual

    if not GROQ_DISPONIBLE:
        return None

    api_key = obtener_groq_api_key()

    if not api_key:
        # FIX/NUEVO: antes esto devolvía None en silencio — el único
        # rastro de que Groq no se usó era el mensaje genérico
        # "Transcripción falló, usando Whisper local como respaldo"
        # en voice.py, que no distingue "no hay key configurada" de
        # "la key existe pero algo falló" (red, cuota agotada, etc).
        # Esto generó confusión real: alguien que solo recibe el .exe
        # sin configurar su propia GROQ_API_KEY (ej. compartiendo el
        # ejecutable con un amigo, sin pasarle instrucciones de
        # configuración) ve este mensaje SIEMPRE, sin entender que es
        # exactamente el comportamiento esperado — no hay key, así que
        # cae al Whisper local, que es justamente el respaldo
        # diseñado para este caso.
        global _avisado_sin_key
        if not _avisado_sin_key:
            print("[Groq] No hay GROQ_API_KEY configurada — usando Whisper/Ollama "
                  "local exclusivamente. Esto es normal si no configuraste una key "
                  "de Groq; ver instrucciones en config.py si querés activarlo.")
            _avisado_sin_key = True
        return None

    # FIX/NUEVO: si la key cambió desde la última vez que se armó el
    # cliente (ej. el usuario acaba de configurarla vía setup_groq.py
    # en esta misma sesión), se reconstruye con la key nueva en vez
    # de seguir usando el cliente viejo cacheado.
    if _cliente_groq is None or api_key != _key_cliente_actual:
        _cliente_groq       = Groq(api_key=api_key)
        _key_cliente_actual = api_key

    return _cliente_groq


_avisado_sin_key = False


def resetear_cliente():
    """
    Olvida el cliente de Groq cacheado y el aviso de "sin key", para
    que la próxima llamada lo reconstruya desde cero leyendo la key
    actual. Se usa desde setup_groq.py justo después de guardar una
    key nueva, para que la validación (la llamada de prueba) use esa
    key recién ingresada y no un cliente viejo armado sin ella.
    """
    global _cliente_groq, _key_cliente_actual, _avisado_sin_key
    _cliente_groq       = None
    _key_cliente_actual = None
    _avisado_sin_key    = False


def _describir_error_groq(excepcion):
    """
    Traduce una excepción de la librería groq a una descripción
    legible y específica — usada para que el print en consola diga
    POR QUÉ falló (cuota agotada, key inválida, problema de red),
    en vez del genérico "Transcripción falló" que no daba ninguna
    pista real. Los tipos de excepción son los documentados por el
    SDK oficial de groq (todos heredan de groq.APIError).
    """
    try:
        import groq as groq_sdk
    except ImportError:
        return str(excepcion)

    if isinstance(excepcion, groq_sdk.RateLimitError):
        return ("límite de uso alcanzado (rate limit / cuota gratuita "
                "agotada por ahora) — cayendo a Whisper/Ollama local")

    if isinstance(excepcion, groq_sdk.AuthenticationError):
        return "la API key no es válida — revisá GROQ_API_KEY"

    if isinstance(excepcion, groq_sdk.APIConnectionError):
        return "no se pudo conectar al servidor de Groq (¿problema de red?)"

    if isinstance(excepcion, groq_sdk.APIStatusError):
        return f"error HTTP {excepcion.status_code} de la API"

    return str(excepcion)


def llamar_groq(prompt, timeout=8, num_predict=40, temperature=0.2):
    """
    Llama a Groq con un límite de tiempo real, mismo patrón que
    _llamar_ollama en ia.py — si la API tarda o falla, se devuelve
    None en vez de colgar el asistente, y quien llama puede caer a
    Ollama como respaldo (ver gestor_ia.py / ia.py).
    """
    cliente = _obtener_cliente()

    if cliente is None:
        return None

    def _tarea():
        respuesta = cliente.chat.completions.create(
            model=MODELO_GROQ,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=num_predict,
            temperature=temperature,
        )
        return respuesta.choices[0].message.content.strip()

    futuro = _executor_groq.submit(_tarea)

    try:
        return futuro.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        log.warning(f"Groq tardó más de {timeout}s, se cancela la espera")
        return None
    except Exception as e:
        motivo = _describir_error_groq(e)
        print(f"[Groq] Falló: {motivo}")
        log.exception(f"Error llamando a Groq ({motivo})")
        return None

# =========================================================
# TRANSCRIPCIÓN (Whisper en la nube, vía Groq)
# NUEVO: mismo motivo que el modo híbrido de texto — Whisper local
# (modelo "small" en CPU) transcribe mal nombres propios en inglés
# dichos en medio de frases en español ("Wuthering Waves", "Stellar
# Blade"), un problema de fondo que ya intentamos mitigar con
# hotwords pero sigue dando fallos reales en uso diario.
#
# Groq ofrece Whisper Large v3 Turbo gratis (2000 peticiones/día,
# ver groq_cliente.py) — un modelo notablemente más grande y preciso
# que el "small" local, corriendo en hardware especializado mucho
# más rápido. Con internet, se prueba esto primero; sin internet,
# se sigue usando el Whisper local como siempre (ver voice.py).
# =========================================================

MODELO_GROQ_WHISPER = "whisper-large-v3-turbo"


def transcribir_groq(audio_wav_bytes, timeout=8, idioma="es", prompt_contexto=None):
    """
    Transcribe audio (bytes WAV) usando Whisper en Groq. Devuelve el
    texto transcrito, o None si Groq no está disponible, falla, o
    tarda demasiado — quien llama puede caer al Whisper local como
    respaldo (ver _transcribir en voice.py).

    prompt_contexto funciona igual que initial_prompt/hotwords en el
    Whisper local — sesga la transcripción hacia palabras esperadas
    (ej. la wake word, o nombres de apps conocidas).

    FIX/NUEVO: Whisper (cualquier variante, local o en la nube) tiene
    un comportamiento conocido y documentado de "alucinar" — generar
    palabras reales del idioma pero sin relación con el audio, sobre
    todo en silencio o ruido ambiental de bajo nivel que de todas
    formas cruzó el umbral de energía y se mandó a transcribir. El
    Whisper LOCAL ya mitiga esto con vad_filter=True, pero la API de
    Groq no aplicaba ningún filtro equivalente, devolviendo a veces
    texto "real" sobre silencio total.

    Ahora se usa response_format="verbose_json" (en vez de "text"),
    que además del texto devuelve, por cada segmento, no_speech_prob
    — la probabilidad estimada por el propio modelo de que ESE
    segmento sea silencio o no contenga habla real. Se descartan los
    segmentos donde esa probabilidad es alta (> 0.6), reconstruyendo
    el texto final solo con los segmentos donde el modelo está
    razonablemente seguro de que sí hubo voz.

    temperature=0 (en vez de dejar el default del SDK) además reduce
    la aleatoriedad de la generación — la documentación oficial de
    Groq indica que con temperature=0 el modelo usa log-probability
    para ajustarse automáticamente en casos ambiguos, en vez de
    simplemente generar la opción más "creativa".
    """
    cliente = _obtener_cliente()

    if cliente is None:
        return None

    # umbral de no_speech_prob por encima del cual se descarta el
    # segmento — filtra los casos claros de silencio/ruido que
    # generaban texto fantasma, sin descartar habla real dicha en voz
    # baja o con ruido de fondo normal (que sigue devolviendo
    # no_speech_prob bajo, cerca de 0).
    #
    # FIX/REVERTIDO: se había bajado a 0.5 (ver el mismo revert en
    # voice.py) pero causó pérdida de audio real ocasional — "a veces
    # no detecta nada". Vuelve a 0.6; la defensa contra resultados
    # sin sentido ahora corre después, sobre el texto ya transcrito
    # completo (ver _parece_gibberish en voice.py), un lugar más
    # seguro para filtrar.
    UMBRAL_NO_SPEECH = 0.6

    def _tarea():
        archivo = ("audio.wav", audio_wav_bytes)
        respuesta = cliente.audio.transcriptions.create(
            file=archivo,
            model=MODELO_GROQ_WHISPER,
            language=idioma,
            prompt=prompt_contexto or "",
            response_format="verbose_json",
            temperature=0,
        )

        segmentos = getattr(respuesta, "segments", None) or []

        if not segmentos:
            # algunas respuestas pueden no incluir segments (audio
            # muy corto, o variación de la API) — se cae al texto
            # completo tal cual, sin poder filtrar por no_speech_prob
            return (respuesta.text or "").strip()

        partes_validas = [
            seg["text"] if isinstance(seg, dict) else seg.text
            for seg in segmentos
            if (seg["no_speech_prob"] if isinstance(seg, dict) else seg.no_speech_prob) < UMBRAL_NO_SPEECH
        ]

        return " ".join(p.strip() for p in partes_validas).strip()

    futuro = _executor_groq.submit(_tarea)

    try:
        return futuro.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        log.warning(f"Groq Whisper tardó más de {timeout}s, se cancela la espera")
        return None
    except Exception as e:
        motivo = _describir_error_groq(e)
        print(f"[Groq] Transcripción falló: {motivo}")
        log.exception(f"Error transcribiendo con Groq Whisper ({motivo})")
        return None