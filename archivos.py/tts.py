import asyncio
import io
import os
import threading
import time
import hashlib
import edge_tts
import pygame
from pathlib import Path
from logger import log

# =========================================================
# CONFIGURACIÓN DE VOZ
# =========================================================
# FIX: voz configurable. El usuario puede cambiarla editando
# config.py o el archivo de configuración. Por ahora, leer
# de config.py si existe, sino usar default.
# =========================================================

VOZ_DEFAULT = "es-CO-SalomeNeural"

# Voces disponibles en español por Edge TTS
VOCES_DISPONIBLES = {
    # Femeninas
    "salome": "es-CO-SalomeNeural",
    "elvira": "es-ES-ElviraNeural",
    "dalia": "es-MX-DaliaNeural",
    "karina": "es-ES-KarinaNeural",
    "lucia": "es-ES-LuciaNeural",
    "mexicanaf": "es-MX-LorenaNeural",
    # Masculinas
    "alvaro": "es-ES-AlvaroNeural",
    "jorge": "es-MX-JorgeNeural",
    "tomas": "es-AR-TomasNeural",
    "gerardo": "es-MX-GerardoNeural",
    "mexicanom": "es-MX-RaulNeural",
    "neerlandes": "es-NL-MaartenNeural",
}

try:
    from config import VOZ_ASISTENTE
    VOZ = VOZ_ASISTENTE
except ImportError:
    VOZ = VOZ_DEFAULT


# =========================================================
# CACHE DE AUDIO LOCAL
# =========================================================
# NUEVO: precarga frases comunes como archivos de audio locales.
# La primera vez que el asistente arranca, genera los audios de
# las frases más frecuentes y los guarda en disco. Las próximas
# veces, reproduce directo desde el archivo — sin red, sin delay.
# =========================================================

_CARPETA_CACHE_TTS = Path.home() / ".asistente_ia" / "cache_tts"
_CARPETA_CACHE_TTS.mkdir(parents=True, exist_ok=True)

# Frases que se precargan en cache al inicio
_FRASES_PRECARGAR = [
    "Asistente listo",
    "¿En qué puedo ayudarte?",
    "¿Algo más?",
    "¿Necesitás algo más?",
    "Cancelado",
    "Hasta luego",
    "Sesión finalizada",
    "No entendí qué quieres que haga, ¿podés repetirlo?",
    "Te escucho, dime qué necesitas",
    "Ya estoy de vuelta",
    "Me quedo en silencio",
    "No tengo forma de procesar eso ahora",
    "Se está demorando mucho en responder, intenta de nuevo en un momento",
    "Todavía no dije nada",
    "Tuve un error inesperado, sigamos",
    "¿Sigues ahí?",
]

_cache_audio = {}  # texto normalizado -> bytes de audio


def _hash_frase(texto, voz):
    """Genera un nombre de archivo único para una frase+voz."""
    return hashlib.md5(f"{texto}|{voz}".encode()).hexdigest()[:16]


def _ruta_cache(texto, voz):
    """Devuelve la ruta del archivo cacheado para una frase."""
    nombre = _hash_frase(texto, voz) + ".mp3"
    return _CARPETA_CACHE_TTS / nombre


def _precargar_cache():
    """Genera archivos de audio en cache para las frases comunes."""
    global _cache_audio
    print(f"[TTS] Precargando cache de audio para voz '{VOZ}'...")
    
    for frase in _FRASES_PRECARGAR:
        ruta = _ruta_cache(frase, VOZ)
        if ruta.exists():
            # Ya existe en disco, cargar a memoria
            with open(ruta, "rb") as f:
                _cache_audio[frase.lower()] = f.read()
            continue
        
        # Generar con edge_tts y guardar
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            audio = loop.run_until_complete(_generar_audio_edge(frase))
            loop.close()
            
            if audio:
                with open(ruta, "wb") as f:
                    f.write(audio)
                _cache_audio[frase.lower()] = audio
                print(f"[TTS]  ✓ Cacheado: {frase!r}")
            else:
                print(f"[TTS]  ✗ Falló: {frase!r}")
        except Exception as e:
            print(f"[TTS]  ✗ Error cacheando {frase!r}: {e}")
    
    print(f"[TTS] Cache listo: {len(_cache_audio)} frases precargadas")


def _obtener_audio_cacheado(texto):
    """Devuelve audio bytes si la frase está en cache, None si no."""
    return _cache_audio.get(texto.lower().strip())


async def _generar_audio_edge(texto):
    """Genera audio con Edge TTS. Devuelve bytes o None."""
    try:
        communicate = edge_tts.Communicate(texto, voice=VOZ)
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return audio_data if audio_data else None
    except Exception as e:
        print(f"[TTS] Error generando audio con Edge: {e}")
        return None


# Precargar cache al importar el módulo (en segundo plano)
threading.Thread(target=_precargar_cache, daemon=True, name="TTSCache").start()


# =========================================================
# ENFRIAMIENTO POST-TTS
# =========================================================

RECALIBRAR_TRAS_HABLAR = True

_DEMORA_BASE_MS = 300
_DEMORA_CONVERSACION_MS = 500
_DEMORA_SUPERPOSICION_MS = 400


def _calcular_demora_eco(hubo_superposicion=False, modo_escucha=None):
    demora = _DEMORA_BASE_MS
    try:
        from voice import get_modo_escucha, ModoEscucha
        if modo_escucha is None:
            modo_escucha = get_modo_escucha()
        if modo_escucha == ModoEscucha.CONVERSACION:
            demora = max(demora, _DEMORA_CONVERSACION_MS)
    except Exception:
        pass
    if hubo_superposicion:
        demora += _DEMORA_SUPERPOSICION_MS
    return demora / 1000.0


# =========================================================
# INICIALIZAR PYGAME MIXER
# =========================================================

pygame.mixer.init()

# =========================================================
# LOCK DE VOZ
# =========================================================

_lock_voz = threading.Lock()

# =========================================================
# ÚLTIMO MENSAJE
# =========================================================

_ultimo_mensaje = None


def ultimo_mensaje():
    return _ultimo_mensaje


# =========================================================
# RESPALDO LOCAL (SAPI5/pyttsx3) — SOLO EN ERRORES GRAVES
# =========================================================

def _hablar_respaldo(texto):
    """Último recurso si todo lo demás falla. Voz del sistema."""
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
# REPRODUCIR AUDIO DESDE BYTES
# =========================================================

def _reproducir_audio(audio_bytes):
    """Reproduce audio desde bytes en memoria."""
    try:
        pygame.mixer.music.load(io.BytesIO(audio_bytes))
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(50)
        return True
    except Exception as e:
        print(f"[TTS] Error reproduciendo audio: {e}")
        return False


# =========================================================
# ESCUCHA EN PARALELO (para interrupciones)
# =========================================================

UMBRAL_VAD_SUPERPONER = 0.6
PHRASE_TIME_LIMIT_SUPERPOSICION = 10
INTENTO_POST_TTS = True


def _vigilar_interrupcion(evento_detener, resultado, info_superposicion):
    from voice import detectar_voz_breve, escuchar_rapido
    while not evento_detener.is_set():
        try:
            hay_voz = detectar_voz_breve(timeout=1, umbral=UMBRAL_VAD_SUPERPONER)
        except Exception:
            continue
        if evento_detener.is_set():
            return
        if hay_voz:
            info_superposicion["hubo"] = True
            info_superposicion["timestamp_inicio"] = time.time()
            try:
                texto = escuchar_rapido(
                    timeout=2,
                    phrase_time_limit=PHRASE_TIME_LIMIT_SUPERPOSICION
                )
            except Exception:
                texto = ""
            info_superposicion["texto"] = texto or None
            info_superposicion["timestamp_fin"] = time.time()
            resultado[0] = texto or None
            return


# =========================================================
# HABLAR PRINCIPAL — CACHE PRIMERO, EDGE TTS DESPUÉS
# =========================================================

async def _hablar_async(texto, permitir_interrupcion):
    # FIX: intentar cache primero (instantáneo, misma voz)
    audio_cacheado = _obtener_audio_cacheado(texto)
    if audio_cacheado:
        print(f"[TTS] Cache hit: {texto!r}")
        _reproducir_audio(audio_cacheado)
        # No hay interrupción en cache (reproducción síncrona simple)
        # pero sí recalibramos
        if RECALIBRAR_TRAS_HABLAR:
            await asyncio.sleep(_calcular_demora_eco())
            try:
                from voice import recalibrar
                recalibrar()
            except Exception:
                pass
        return None

    # No está en cache → generar con Edge TTS
    audio_data = await _generar_audio_edge(texto)
    
    if not audio_data:
        raise RuntimeError("Edge TTS no devolvió audio")

    _reproducir_audio(audio_data)

    resultado_interrupcion = [None]
    info_superposicion = {"hubo": False}
    hilo_vigilancia = None
    evento_detener = threading.Event()

    if permitir_interrupcion:
        hilo_vigilancia = threading.Thread(
            target=_vigilar_interrupcion,
            args=(evento_detener, resultado_interrupcion, info_superposicion),
            daemon=True
        )
        hilo_vigilancia.start()

    while pygame.mixer.music.get_busy():
        pygame.time.wait(50)

    evento_detener.set()

    if hilo_vigilancia is not None and hilo_vigilancia.is_alive():
        hilo_vigilancia.join(timeout=3)

    if (INTENTO_POST_TTS
        and info_superposicion["hubo"]
        and not resultado_interrupcion[0]):
        try:
            from voice import escuchar_rapido
            print("[TTS] Superposición sin texto claro, intentando post-TTS...")
            texto_post = escuchar_rapido(timeout=2, phrase_time_limit=5)
            if texto_post:
                resultado_interrupcion[0] = texto_post
                print(f"[TTS] Segundo intento exitoso: {texto_post!r}")
        except Exception:
            pass

    if RECALIBRAR_TRAS_HABLAR:
        demora = _calcular_demora_eco(hubo_superposicion=info_superposicion["hubo"])
        await asyncio.sleep(demora)
        try:
            from voice import recalibrar
            recalibrar()
        except Exception as e:
            log.warning(f"No se pudo recalibrar: {e}")

    return resultado_interrupcion[0]


def hablar(texto, permitir_interrupcion=False):
    global _ultimo_mensaje
    _ultimo_mensaje = texto

    with _lock_voz:
        print("Asistente:", texto)

        try:
            return asyncio.run(_hablar_async(texto, permitir_interrupcion))
        except Exception as e:
            print("[TTS] Error con Edge TTS, usando respaldo:", e)
            log.warning(f"Edge TTS falló. Texto: '{texto}'. Motivo: {e}")
            # FIX: en error, intentar reproducir desde cache si existe
            audio_cacheado = _obtener_audio_cacheado(texto)
            if audio_cacheado:
                print("[TTS] Usando cache de respaldo por error")
                _reproducir_audio(audio_cacheado)
                return None
            if not _hablar_respaldo(texto):
                log.error(f"El asistente quedó MUDO para: '{texto}'")
            return None