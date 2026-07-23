import concurrent.futures
import threading
import unicodedata
import atexit
import time
import numpy as np
import speech_recognition as sr
from faster_whisper import WhisperModel
from faster_whisper.vad import get_vad_model
from logger import log
from plataforma import es_windows
from enum import Enum

# =========================================================
# MEJORA 3: PAUSE THRESHOLD ADAPTATIVO POR CONTEXTO
# =========================================================

class ModoEscucha(Enum):
    COMANDO = "comando"
    CONVERSACION = "conversacion"
    WAKE_WORD = "wake_word"
    CONFIRMACION = "confirmacion"

PERFILES_ESCUCHA = {
    ModoEscucha.COMANDO:       (600,  12, 0.35),
    ModoEscucha.CONVERSACION:  (1500, 20, 0.25),
    ModoEscucha.WAKE_WORD:     (400,  4,  0.40),
    ModoEscucha.CONFIRMACION:  (800,  4,  0.30),
}

_modo_escucha_actual = ModoEscucha.COMANDO


def set_modo_escucha(modo: ModoEscucha):
    global _modo_escucha_actual
    _modo_escucha_actual = modo
    silencio, limite, umbral = PERFILES_ESCUCHA[modo]
    print(f"[Voice] Modo escucha: {modo.value} "
          f"(silencio={silencio}ms, límite={limite}s, umbral_VAD={umbral})")


def get_modo_escucha() -> ModoEscucha:
    return _modo_escucha_actual


# =========================================================
# LOCK DE MICRÓFONO
# =========================================================

_lock_microfono = threading.Lock()

# =========================================================
# MICRÓFONO PERSISTENTE
# =========================================================

_microfono        = None
_microfono_abierto = False


def _obtener_microfono():
    global _microfono, _microfono_abierto
    if _microfono is None:
        _microfono = sr.Microphone(sample_rate=16000)
    if not _microfono_abierto:
        _microfono.__enter__()
        _microfono_abierto = True
    return _microfono


def _reabrir_microfono():
    global _microfono, _microfono_abierto
    if _microfono is not None and _microfono_abierto:
        try:
            _microfono.__exit__(None, None, None)
        except Exception:
            pass
    _microfono         = None
    _microfono_abierto = False
    return _obtener_microfono()


def _cerrar_microfono_persistente():
    global _microfono_abierto
    if _microfono is not None and _microfono_abierto:
        try:
            _microfono.__exit__(None, None, None)
        except Exception:
            pass
    _microfono_abierto = False


atexit.register(_cerrar_microfono_persistente)


# =========================================================
# CALIBRACIÓN PROGRESIVA
# =========================================================

_FACTOR_SUICION_CALIBRACION = 0.3


def _calibrar_progresivo(duracion=2):
    with _lock_microfono:
        source = _obtener_microfono()
        umbral_anterior = recognizer.energy_threshold
        recognizer.adjust_for_ambient_noise(source, duration=duracion)
        umbral_nuevo = recognizer.energy_threshold
        umbral_suavizado = (umbral_anterior * (1 - _FACTOR_SUICION_CALIBRACION) +
                            umbral_nuevo * _FACTOR_SUICION_CALIBRACION)
        recognizer.energy_threshold = umbral_suavizado
        print(f"[Micrófono] Calibración suave: {umbral_anterior:.0f} → "
              f"{umbral_nuevo:.0f} (ajustado a {umbral_suavizado:.0f})")


def recalibrar():
    try:
        _calibrar_progresivo(duracion=0.6)
    except Exception as e:
        print("[Micrófono] No pude recalibrar:", e)


# =========================================================
# VAD (Silero)
# =========================================================

_VENTANA_VAD_MUESTRAS = 512
_GRUPO_VENTANAS_VAD   = 4
UMBRAL_VAD_INICIO     = 0.5


def _leer_muestras_crudas(source, n_muestras):
    """
    Lee `n_muestras` muestras (frames) de audio CRUDO del stream ya
    abierto (bytes PCM de 16 bits, sin pasar por recognizer.listen())
    y las devuelve como array float32 normalizado a [-1, 1] — el
    formato que espera el modelo Silero VAD. Asume que el micrófono
    está a 16kHz (ver _obtener_microfono, sample_rate=16000 forzado).

    FIX: source.stream.read(x) —vía PyAudio— espera la cantidad de
    FRAMES (muestras) a leer, NO la cantidad de bytes. La versión
    anterior de esta función pasaba n_bytes (= n_muestras * 2, para
    audio mono de 16 bits) como si fuera la cantidad de muestras a
    leer — PyAudio terminaba leyendo el DOBLE de frames reales de los
    que se pedían, y como cada frame son 2 bytes, la función devolvía
    el doble de muestras de las que el resto del código (_escuchar_
    con_vad, detectar_voz_breve) asumía que había leído.

    Esto no rompía nada de forma visible (no había excepción, no
    crasheaba), pero corrompía TODOS los cálculos de tiempo que
    dependen de "cuántos milisegundos representa un grupo de
    muestras" (ver duracion_grupo_seg en _escuchar_con_vad) — cada
    grupo en realidad contenía el doble de audio real del que se
    asumía, así que TODOS los umbrales configurados en
    PERFILES_ESCUCHA (silencio antes de cortar, timeout de espera,
    límite máximo de frase) terminaban corriendo al DOBLE de su valor
    nominal en tiempo real (ej. un silencio configurado a 600ms
    tardaba ~1200ms reales en disparar el corte de la escucha). Esta
    misma función alimenta tanto la escucha de comandos normales
    (_escuchar_con_vad) como la detección de interrupciones mientras
    el asistente habla (detectar_voz_breve, usada por tts.py) — el
    bug afectaba a ambas por igual.

    Ahora se lee la cantidad de FRAMES correcta (n_muestras, sin
    duplicar). El chequeo de longitud/padding se mantiene como red de
    seguridad (por si el stream devuelve menos datos de los pedidos,
    ej. al principio de la captura), pero ahora compara contra la
    cantidad de BYTES real y correctamente esperada (n_muestras * 2),
    no contra lo que antes se le pasaba a read().
    """
    datos = source.stream.read(n_muestras)

    n_bytes_esperados = n_muestras * 2

    if len(datos) % 2 != 0:
        datos = datos[:-1]
    if len(datos) < n_bytes_esperados:
        datos += b'\x00' * (n_bytes_esperados - len(datos))

    audio_int16 = np.frombuffer(datos, dtype=np.int16)
    return audio_int16.astype(np.float32) / 32768.0


def _escuchar_con_vad(timeout, phrase_time_limit, umbral_inicio=UMBRAL_VAD_INICIO,
                      umbral_fin=None, silencio_ms=None):
    if umbral_fin is None or silencio_ms is None:
        perfil = PERFILES_ESCUCHA.get(_modo_escucha_actual, PERFILES_ESCUCHA[ModoEscucha.COMANDO])
        if silencio_ms is None:
            silencio_ms = perfil[0]
        if umbral_fin is None:
            umbral_fin = perfil[2]

    try:
        modelo_vad = get_vad_model()
    except Exception as e:
        log.warning(f"VAD no disponible, cayendo a recognizer.listen(): {e}")
        return _escuchar_con_reintento_legacy(timeout, phrase_time_limit)

    muestras_por_grupo = _VENTANA_VAD_MUESTRAS * _GRUPO_VENTANAS_VAD
    duracion_grupo_seg = muestras_por_grupo / 16000

    grupos_timeout = max(1, round(timeout / duracion_grupo_seg))
    grupos_max_duracion = max(1, round(phrase_time_limit / duracion_grupo_seg))
    grupos_silencio = max(1, round((silencio_ms / 1000) / duracion_grupo_seg))

    audio_acumulado = []
    grupos_silencio_consecutivos = 0
    grupos_totales = 0

    with _lock_microfono:
        source = _obtener_microfono()
        try:
            for _ in range(grupos_timeout):
                audio = _leer_muestras_crudas(source, muestras_por_grupo)
                probabilidades = modelo_vad(audio)
                prob_max = float(np.max(probabilidades))
                if prob_max >= umbral_inicio:
                    audio_acumulado.append(audio)
                    grupos_totales += 1
                    break
            else:
                raise sr.WaitTimeoutError(f"No se detectó voz en {timeout}s (VAD)")

            while grupos_totales < grupos_max_duracion:
                audio = _leer_muestras_crudas(source, muestras_por_grupo)
                probabilidades = modelo_vad(audio)
                prob_max = float(np.max(probabilidades))
                audio_acumulado.append(audio)
                grupos_totales += 1
                if prob_max >= umbral_fin:
                    grupos_silencio_consecutivos = 0
                else:
                    grupos_silencio_consecutivos += 1
                    if grupos_silencio_consecutivos >= grupos_silencio:
                        break

        except sr.WaitTimeoutError:
            raise
        except Exception as e:
            log.warning(f"Error en VAD durante captura: {e}, reabriendo micrófono")
            _reabrir_microfono()
            raise

    audio_total = np.concatenate(audio_acumulado)
    audio_int16 = (audio_total * 32767).astype(np.int16)
    wav_bytes = audio_int16.tobytes()
    return sr.AudioData(wav_bytes, 16000, 2)


def _escuchar_con_reintento_legacy(timeout, phrase_time_limit):
    with _lock_microfono:
        source = _obtener_microfono()
        try:
            return recognizer.listen(source, timeout=timeout,
                                     phrase_time_limit=phrase_time_limit)
        except sr.WaitTimeoutError:
            raise
        except Exception as e:
            log.warning(f"Error leyendo del micrófono (legacy), reabriendo: {e}")
            source = _reabrir_microfono()
            return recognizer.listen(source, timeout=timeout,
                                     phrase_time_limit=phrase_time_limit)


# =========================================================
# RECOGNIZER
# =========================================================

recognizer = sr.Recognizer()
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = True
recognizer.pause_threshold          = 0.9
recognizer.phrase_threshold         = 0.3
recognizer.non_speaking_duration    = 0.5

print("[Micrófono] Calibrando...")
try:
    _calibrar_progresivo(duracion=2)
    print("[Micrófono] Listo")
except Exception as e:
    print("\n[Micrófono] No pude acceder a ningún micrófono.")
    print("[Micrófono] Motivo técnico:", e)
    print("[Micrófono] Revisa que haya un micrófono conectado y")
    print("[Micrófono] configurado como dispositivo de entrada")
    if es_windows():
        print("[Micrófono] predeterminado en Windows (Configuración >")
        print("[Micrófono] Sistema > Sonido > Entrada), y vuelve a intentar.")
    else:
        print("[Micrófono] predeterminado en la configuración de sonido")
        print("[Micrófono] de tu sistema, y vuelve a intentar.")
    import time
    import sys
    time.sleep(10)
    sys.exit(1)


# =========================================================
# WHISPER LOCAL
# =========================================================

MODELO_WHISPER = "small"

import multiprocessing
_NUCLEOS_LOGICOS = multiprocessing.cpu_count() or 4
CPU_THREADS_WHISPER = max(2, min(8, _NUCLEOS_LOGICOS // 2))
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
    print("[Whisper] No se pudo cargar el modelo liviano de wake word:", e)
    log.warning(f"No se pudo cargar el modelo liviano de wake word: {e}")
    _modelo_whisper_wakeword = None

_executor_whisper = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def _audio_a_array(audio_data):
    wav_bytes = audio_data.get_wav_data(convert_rate=16000, convert_width=2)
    muestras_int16 = np.frombuffer(wav_bytes[44:], dtype=np.int16)
    return muestras_int16.astype(np.float32) / 32768.0


# =========================================================
# FILTRO DE CONFIANZA + DENSIDAD
# =========================================================

UMBRAL_CONFIANZA_LOGPROB = -1.0
MAX_DENSIDAD_PALABRAS    = 8.0


def _calcular_duracion_audio(audio_data):
    n_muestras = len(audio_data.get_raw_data()) // audio_data.sample_width
    return n_muestras / audio_data.sample_rate


def _filtrar_por_confianza(segmentos, duracion_audio, texto_completo):
    if not segmentos or not texto_completo:
        return ""
    avg_logprobs = [s.avg_logprob for s in segmentos if hasattr(s, 'avg_logprob')]
    if avg_logprobs:
        confianza_promedio = sum(avg_logprobs) / len(avg_logprobs)
        if confianza_promedio < UMBRAL_CONFIANZA_LOGPROB:
            print(f"[Whisper] Descartado por baja confianza "
                  f"(avg_logprob={confianza_promedio:.2f}): {texto_completo!r}")
            log.info(f"  -> descartado (baja confianza: {confianza_promedio:.2f})")
            return ""
    n_palabras = len(texto_completo.split())
    if duracion_audio > 0:
        densidad = n_palabras / duracion_audio
        if densidad > MAX_DENSIDAD_PALABRAS:
            print(f"[Whisper] Descartado por densidad imposible "
                  f"({densidad:.1f} palabras/seg): {texto_completo!r}")
            log.info(f"  -> descartado (densidad: {densidad:.1f} pal/s)")
            return ""
    return texto_completo


def _transcribir_whisper(audio_data, initial_prompt=None, beam_size=5, hotwords=None, modelo=None):
    modelo = modelo or _modelo_whisper
    if modelo is None:
        return None
    array_audio = _audio_a_array(audio_data)
    segmentos, _ = modelo.transcribe(
        array_audio,
        language="es",
        beam_size=beam_size,
        vad_filter=True,
        condition_on_previous_text=True,
        initial_prompt=initial_prompt,
        hotwords=hotwords,
    )
    UMBRAL_NO_SPEECH = 0.6
    segmentos = list(segmentos)
    partes_validas = [
        s.text.strip() for s in segmentos if s.no_speech_prob < UMBRAL_NO_SPEECH
    ]
    texto = " ".join(partes_validas).strip()
    duracion = _calcular_duracion_audio(audio_data)
    texto = _filtrar_por_confianza(segmentos, duracion, texto)
    return texto


def _transcribir_con_timeout(audio_data, timeout=None, initial_prompt=None, beam_size=5, hotwords=None, modelo=None):
    if timeout is None:
        timeout = TIMEOUT_BASE_WHISPER
    futuro = _executor_whisper.submit(
        _transcribir_whisper, audio_data, initial_prompt, beam_size, hotwords, modelo
    )
    try:
        return futuro.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        print(f"[Whisper] Tardó más de {timeout}s, se cancela la espera")
        log.warning(f"Whisper tardó más de {timeout}s, se canceló la espera")
        return None
    except Exception as e:
        print("[Whisper] Error transcribiendo:", e)
        log.exception("Error transcribiendo con Whisper")
        return None


# =========================================================
# FRASES FANTASMA + GIBBERISH
# =========================================================

_FRASES_FANTASMA_CONOCIDAS = {
    "subtitulos realizados por la comunidad de amara.org",
    "subtitulado por la comunidad de amara.org",
    "subtitulos por la comunidad de amara.org",
    "subtitulos en espanol de amara.org",
    "equipo de subtitulacion",
    "gracias por ver el video",
    "gracias por ver este video",
    "gracias por ver",
    "suscribete a mi canal",
    "suscribete al canal",
    "dale like y suscribete",
    "no olvides suscribirte",
    "no olvides darle like",
    "activa la campanita",
    "mas videos en mi canal",
    "nos vemos en el proximo video",
    "nos vemos en el siguiente video",
    "www.youtube.com",
    "sigueme en instagram",
    "sigueme en redes sociales",
    "jarvis jarvis jarvis",
    "jarvis, jarvis",
}

_VOCALES = set("aeiouáéíóúü")


def _es_frase_fantasma_conocida(texto):
    if not texto:
        return False
    normalizado = unicodedata.normalize("NFKD", texto.lower())
    normalizado = "".join(c for c in normalizado if not unicodedata.combining(c))
    return any(frase in normalizado for frase in _FRASES_FANTASMA_CONOCIDAS)


def _parece_gibberish(texto):
    texto = (texto or "").strip().lower()
    if len(texto) < 2:
        return True
    if any(c.isdigit() for c in texto):
        return False
    letras = [c for c in texto if c.isalpha()]
    if not letras:
        return True
    return not any(c in _VOCALES for c in letras)


def _filtrar_resultado(texto, origen="?"):
    log.info(f"Transcripción [{origen}]: {texto!r}")
    if _es_frase_fantasma_conocida(texto):
        print(f"[Whisper] Descartada frase fantasma: {texto!r}")
        log.info(f"  -> descartada (frase fantasma)")
        return ""
    if _parece_gibberish(texto):
        print(f"[Whisper] Descartado resultado sin sentido: {texto!r}")
        log.info(f"  -> descartada (gibberish)")
        return ""
    return texto


# =========================================================
# TRANSCRIPCIÓN HÍBRIDA — CON CACHE DE MOTOR
# =========================================================
# FIX: importar motor_a_usar UNA VEZ a nivel de módulo en vez de
# dentro de _transcribir() en cada llamada. Además, usar una
# variable global _MOTOR_TRANSCRIPCION cacheada por sesión para
# evitar llamar a motor_a_usar() en cada audio.
# =========================================================

try:
    from gestor_ia import motor_a_usar as _motor_a_usar
except ImportError:
    _motor_a_usar = None

_MOTOR_TRANSCRIPCION_CACHE = None
_MOTOR_TRANSCRIPCION_TS = 0
_MOTOR_TRANSCRIPCION_TTL = 8  # segundos


def _motor_transcripcion_actual():
    """Devuelve el motor a usar para transcripción, con cache propio."""
    global _MOTOR_TRANSCRIPCION_CACHE, _MOTOR_TRANSCRIPCION_TS
    if _motor_a_usar is None:
        return "whisper-local"
    ahora = time.time()
    if _MOTOR_TRANSCRIPCION_CACHE is not None and (ahora - _MOTOR_TRANSCRIPCION_TS) < _MOTOR_TRANSCRIPCION_TTL:
        return _MOTOR_TRANSCRIPCION_CACHE
    motor = _motor_a_usar()
    _MOTOR_TRANSCRIPCION_CACHE = motor
    _MOTOR_TRANSCRIPCION_TS = ahora
    return motor


def _invalidar_cache_transcripcion():
    """Invalida el cache de motor de transcripción. Llamar cuando Groq falla."""
    global _MOTOR_TRANSCRIPCION_CACHE, _MOTOR_TRANSCRIPCION_TS
    _MOTOR_TRANSCRIPCION_CACHE = None
    _MOTOR_TRANSCRIPCION_TS = 0


try:
    from config import PROMPT_GROQ_HABILITADO
except ImportError:
    PROMPT_GROQ_HABILITADO = True

PROMPT_GROQ_COMANDOS = (
    "Comandos de voz en español para un asistente: abrir o cerrar una "
    "aplicación, pausar, reanudar, subir o bajar el volumen, activar o "
    "desactivar el modo no molestar, duérmete, despierta, crear un "
    "recordatorio o un temporizador, cancela."
)


def _transcribir(audio_data, initial_prompt=None, beam_size=5, hotwords=None,
                  permitir_groq=True, modelo=None, prompt_groq_extra=None):
    # FIX: usar cache de motor en vez de llamar motor_a_usar() cada vez
    motor = _motor_transcripcion_actual() if permitir_groq else "ollama"

    if permitir_groq and motor == "groq":
        from groq_cliente import transcribir_groq

        wav_bytes = audio_data.get_wav_data(convert_rate=16000, convert_width=2)

        partes_contexto = [p for p in (initial_prompt, prompt_groq_extra, hotwords) if p]
        contexto = ". ".join(partes_contexto) if partes_contexto else None

        texto = transcribir_groq(wav_bytes, prompt_contexto=contexto)

        if texto is not None:
            return _filtrar_resultado(texto.lower(), origen="groq")

        print("[Groq] Transcripción falló, usando Whisper local como respaldo")
        log.warning("Groq Whisper falló, cayendo a Whisper local")
        # FIX: invalidar cache para que la próxima transcripción use Whisper
        _invalidar_cache_transcripcion()

    texto = _transcribir_con_timeout(
        audio_data, initial_prompt=initial_prompt, beam_size=beam_size,
        hotwords=hotwords, modelo=modelo
    )

    if texto is not None:
        return _filtrar_resultado(texto.lower(), origen="whisper-local")

    print("[Whisper] No disponible, usando Google como respaldo")

    try:
        return _filtrar_resultado(recognizer.recognize_google(
            audio_data,
            language="es-CO"
        ).lower(), origen="google")
    except sr.UnknownValueError:
        return ""
    except sr.RequestError:
        return ""


# =========================================================
# HOTWORDS
# =========================================================

_LIMITE_CARACTERES_HOTWORDS = 600
_indice_rotacion_hotwords   = 0


def _construir_hotwords():
    global _indice_rotacion_hotwords
    try:
        import app_finder
        from aliases import aliases as alias_dict
    except Exception as e:
        log.debug(f"No se pudieron cargar aliases para hotwords: {e}")
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

    vistos = set()
    unicos = []
    for nombre in candidatos:
        clave = nombre.lower().strip()
        if clave and clave not in vistos:
            vistos.add(clave)
            unicos.append(clave)

    if not unicos:
        return None

    n = len(unicos)
    inicio = _indice_rotacion_hotwords % n
    orden_rotado = unicos[inicio:] + unicos[:inicio]

    resultado = []
    largo = 0
    for nombre in orden_rotado:
        if largo + len(nombre) + 2 > _LIMITE_CARACTERES_HOTWORDS:
            break
        resultado.append(nombre)
        largo += len(nombre) + 2

    _indice_rotacion_hotwords = (inicio + len(resultado)) % n
    return ", ".join(resultado) if resultado else None


# =========================================================
# FUNCIONES PÚBLICAS
# =========================================================

def escuchar_wake_word(wake_word):
    print("Escuchando...")
    set_modo_escucha(ModoEscucha.WAKE_WORD)
    silencio_ms, limite, umbral_fin = PERFILES_ESCUCHA[ModoEscucha.WAKE_WORD]

    try:
        audio = _escuchar_con_vad(
            timeout=5,
            phrase_time_limit=limite,
            silencio_ms=silencio_ms,
            umbral_fin=umbral_fin
        )
    except sr.WaitTimeoutError:
        return ""

    prompt = f"Comandos de voz en español. Palabra de activación: {wake_word}."

    return _transcribir(
        audio, initial_prompt=prompt, beam_size=1, permitir_groq=False,
        modelo=_modelo_whisper_wakeword, hotwords=wake_word,
    )


def escuchar_confirmacion(timeout=8):
    print("Escuchando...")
    set_modo_escucha(ModoEscucha.CONFIRMACION)
    silencio_ms, limite, umbral_fin = PERFILES_ESCUCHA[ModoEscucha.CONFIRMACION]

    try:
        audio = _escuchar_con_vad(
            timeout=timeout,
            phrase_time_limit=limite,
            silencio_ms=silencio_ms,
            umbral_fin=umbral_fin
        )
    except sr.WaitTimeoutError:
        return ""

    prompt = "Responde sí, no, confirmo, dale, cancela u otra confirmación corta."
    return _transcribir(audio, initial_prompt=prompt, beam_size=8)


def escuchar():
    print("Escuchando...")
    set_modo_escucha(ModoEscucha.CONVERSACION)
    silencio_ms, limite, umbral_fin = PERFILES_ESCUCHA[ModoEscucha.CONVERSACION]

    try:
        audio = _escuchar_con_vad(
            timeout=5,
            phrase_time_limit=limite,
            silencio_ms=silencio_ms,
            umbral_fin=umbral_fin
        )
    except sr.WaitTimeoutError:
        return ""

    hotwords = _construir_hotwords()
    prompt_groq = PROMPT_GROQ_COMANDOS if PROMPT_GROQ_HABILITADO else None
    return _transcribir(audio, beam_size=8, hotwords=hotwords,
                        prompt_groq_extra=prompt_groq)


def escuchar_rapido(timeout=2, phrase_time_limit=3):
    set_modo_escucha(ModoEscucha.COMANDO)
    silencio_ms, limite, umbral_fin = PERFILES_ESCUCHA[ModoEscucha.COMANDO]

    try:
        audio = _escuchar_con_vad(
            timeout=timeout,
            phrase_time_limit=min(phrase_time_limit, limite),
            silencio_ms=silencio_ms,
            umbral_fin=umbral_fin
        )
    except sr.WaitTimeoutError:
        return ""

    try:
        return _transcribir(audio)
    except Exception:
        return ""


# =========================================================
# DETECTAR VOZ BREVE
# =========================================================

def detectar_voz_breve(timeout=1, umbral=UMBRAL_VAD_INICIO):
    try:
        modelo_vad = get_vad_model()
    except Exception as e:
        log.warning(f"VAD no disponible, intentando fallback de energía: {e}")
        return _detectar_voz_por_energia(timeout)

    muestras_por_grupo = _VENTANA_VAD_MUESTRAS * _GRUPO_VENTANAS_VAD
    duracion_grupo_seg = muestras_por_grupo / 16000
    grupos_totales = max(1, round(timeout / duracion_grupo_seg))

    with _lock_microfono:
        source = _obtener_microfono()
        try:
            for _ in range(grupos_totales):
                audio = _leer_muestras_crudas(source, muestras_por_grupo)
                probabilidades = modelo_vad(audio)
                if float(np.max(probabilidades)) >= umbral:
                    return True
        except Exception as e:
            log.warning(f"Error leyendo audio para VAD: {e}")
            return False

    return False


def _detectar_voz_por_energia(timeout=1):
    with _lock_microfono:
        source = _obtener_microfono()
        umbral_energia = recognizer.energy_threshold * 1.5
        muestras_por_grupo = _VENTANA_VAD_MUESTRAS * _GRUPO_VENTANAS_VAD
        duracion_grupo_seg = muestras_por_grupo / 16000
        grupos_totales = max(1, round(timeout / duracion_grupo_seg))
        try:
            for _ in range(grupos_totales):
                audio = _leer_muestras_crudas(source, muestras_por_grupo)
                energia = np.sqrt(np.mean(audio ** 2))
                if energia > umbral_energia / 32768.0:
                    return True
        except Exception as e:
            log.warning(f"Error en fallback de energía: {e}")
            return False
    return False